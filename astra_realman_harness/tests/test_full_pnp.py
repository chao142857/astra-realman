"""Full-task offline contracts. Synthetic RGB / fake scene tests are not physics evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp import rgb
from sim_skills.full_pnp.backend import FullTaskBackend
from sim_skills.full_pnp.protocol import CandidateGate,Memory,INTERFACE,Rejected,validate_actions,wire_base
from sim_skills.async_v1 import sha


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.cal={'pose_world_xyz_wxyz':[0,0,1,0,1,0,0],'intrinsic':[[200,0,160],[0,200,120],[0,0,1]],'resolution':[320,240]}
    def tearDown(self):self.tmp.cleanup()
    def picture(self,name='image',shift=0,blank=False,double=False):
        image=Image.new('RGB',(320,240),(100,100,100));d=ImageDraw.Draw(image)
        if not blank:
            d.rectangle((70+shift,80,100+shift,110),fill=(220,10,10))
            d.rectangle((200,160,260,185),fill=(5,160,10))
        if double:d.rectangle((130,80,160,110),fill=(220,10,10))
        p=self.root/(name+'.png');image.save(p);return p
    def observation(self):
        p=self.picture();return {'observation_id':'o1','images':{c:str(p) for c in ('assembly','fixed','wrist')},
          'state':{'sim_step':10,'actual_grasp_center_world':[.3,0,.12],'flange_pose_world':[.3,0,.12,0,1,0,0],
                   'object_pose_gt':[9,9,9],'contact_latch':True,'final_score':'SECRET'},
          'captured_monotonic':1.,'capture_span_s':.01,'calibration':{c:copy.deepcopy(self.cal) for c in ('assembly','fixed','wrist')},
          'private_score':'SECRET','script_answers':[1,2,3]}
    def packet(self,obs):
        return {'kind':'evidence','binding':{'source_observation_id':obs['observation_id'],'request_id':'E1'},
                'selected_camera':'fixed','bbox':[.2,.3,.4,.5],'claims':{'holding':'unknown'}}
    def test_setup_held_disabled(self):
        with self.assertRaisesRegex(RuntimeError,'SETUP_HELD_FORBIDDEN'):FullTaskBackend.setup_held(None)
    def test_chunk_barrier_absolute_poses_and_nan(self):
        validate_actions([{'type':'move_pose','pose':[.3,0,.1,0,1,0,0]},{'type':'gripper','opening':.45}])
        for actions in ([{'type':'gripper','opening':.5},{'type':'hold','seconds':1}],
                        [{'type':'move_delta','delta':[0,0,.1]}],[{'type':'move_pose','pose':[float('nan'),0,.1,0,1,0,0]}],
                        [{'type':'gripper','opening':True}]):
            with self.assertRaises(Rejected):validate_actions(actions)
    def test_rgb_static_motion_and_unknown_not_hash_pass(self):
        old=rgb.detect(self.picture());same=rgb.detect(self.picture('same'));moved=rgb.detect(self.picture('moved',shift=25))
        blank=rgb.detect(self.picture('blank',blank=True));cal={'fixed':self.cal}
        check=lambda a,b:rgb.compare({'fixed':a},{'fixed':b},cal,cal,['object_static'],{})['status']
        self.assertEqual(check(old,same),'valid');self.assertEqual(check(old,moved),'invalid')
        self.assertEqual(check(blank,blank),'unknown') # identical bytes must NOT pass
        self.assertEqual(check(old,blank),'unknown')
        double=rgb.detect(self.picture('double',double=True));self.assertEqual(double['object']['status'],'unknown')
    def test_bbox_identity_current_state_are_distinct(self):
        obs=self.observation();old=rgb.features(obs);new=copy.deepcopy(old)
        new['fixed']['object']={'status':'unknown','reason':'occluded'}
        out=rgb.reuse_packet(self.packet(obs),old,new,obs['calibration'],obs['calibration'],'o2')
        self.assertEqual(out['old_bbox']['source_observation_id'],'o1')
        self.assertEqual(out['identity_hypothesis']['status'],'unconfirmed')
        self.assertEqual(out['current_object_state']['status'],'unknown');self.assertEqual(out['current_roi']['status'],'unknown')
        moved=copy.deepcopy(obs['calibration']);moved['fixed']['pose_world_xyz_wxyz'][0]+=.1
        out=rgb.reuse_packet(self.packet(obs),old,old,obs['calibration'],moved,'o3')
        self.assertEqual(out['current_roi']['status'],'unknown');self.assertFalse(out['camera_unchanged'])
    def test_wire_excludes_private_answers_and_truth(self):
        obs=self.observation();m=Memory();binding={'history_cutoff':2}
        obs['calibration']['fixed']['hidden_goal']='SECRET'
        w=wire_base(obs,binding,{'status':'completed'},[.3,0,.12,0,1,0,0],m,'B',0,'B')
        raw=json.dumps(w)
        for forbidden in ('object_pose_gt','contact_latch','final_score','SECRET','script_answers','sim_rm65_targets'):self.assertNotIn(forbidden,raw)
        self.assertEqual(w['observation']['state']['sim_step'],10)
        self.assertEqual(w['expected_join']['status'],'PREDICTED_NOT_MEASURED')
    def test_memory_only_completed_once_and_hypothesis_not_fact(self):
        m=Memory();obs=self.observation();result={'ok':True,'results':[{'action':{'type':'hold','seconds':1},'result':{'ok':True,'object_pose_gt':[9,9,9]}}]}
        m.complete('one',obs,obs,[{'type':'hold','seconds':1}],result,2.)
        with self.assertRaisesRegex(Rejected,'DUPLICATE_COMPLETION'):m.complete('one',obs,obs,[],result,3.)
        with self.assertRaisesRegex(Rejected,'FUTURE_HISTORY'):m.project('F',1.)
        m.hypothesis(self.packet(obs));w=m.project('F',3.)
        self.assertFalse(w['visual_hypotheses'][0]['confirmed']);self.assertNotIn('object_pose_gt',json.dumps(w))
        self.assertEqual(len(w['completed_transitions']),1)
    def test_gate_new_state_binding_barrier_refs_duplicate_and_rgb(self):
        binding={k:'v' for k in ('episode_id','task_revision','calibration_revision','action_interface_revision','parent_plan_id','expected_join_id')}
        binding['barrier_epoch']=2
        c={'kind':'candidate','binding':binding,'operation':'chunk','actions':[{'type':'hold','seconds':1}],
           'requirements':['scene_healthy'],'evidence_refs':['i1'],'parent_evidence_hash':None,'verdict':None,'reason':'fixture'}
        item={'candidate':c,'digest':'unique','deadline':100.,'snapshot':{'binding':binding,'evidence_packet_hash':None,'expected_join':{'pad_pose':[.3,0,.12,0,1,0,0]}}}
        state={'actual_grasp_center_world':[.3,0,.12],'flange_pose_world':[.3,0,.12,0,1,0,0]}
        gate=CandidateGate();gate.validate(item,binding,state,10,{'status':'valid'},{'i1'})
        with self.assertRaisesRegex(Rejected,'DUPLICATE_SUBMISSION'):gate.validate(item,binding,state,10,{'status':'valid'},{'i1'})
        for new_bind,new_state,now,check,refs,reason in (
            (dict(binding,barrier_epoch=3),state,10,{'status':'valid'},{'i1'},'STALE_BARRIER'),
            (binding,dict(state,actual_grasp_center_world=[0,0,0]),10,{'status':'valid'},{'i1'},'ACTUAL_JOIN'),
            (binding,state,101,{'status':'valid'},{'i1'},'LATE'),
            (binding,state,10,{'status':'unknown'},{'i1'},'RGB_UNKNOWN'),
            (binding,state,10,{'status':'valid'},{'other'},'UNSEEN')):
            with self.assertRaisesRegex(Rejected,reason):CandidateGate().validate(item,new_bind,new_state,now,check,refs)
    def test_rgb_calibration_round_trip(self):
        # Camera points down: SAPIEN +x transformed to world -z.
        cal=copy.deepcopy(self.cal);cal['pose_world_xyz_wxyz']=[0,0,1,.7071067811865476,0,.7071067811865476,0]
        point=rgb.pixel_world_on_plane({'status':'visible','centroid':[170,130]},cal,.025)
        np.testing.assert_allclose(rgb.project(point,cal),[170,130],atol=1e-7)
    def test_frozen_legacy_copy(self):
        path=Path(__file__).resolve().parents[1]/'sim_skills/full_pnp/legacy_model_bridge.py'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'12ca47cfec8a1fa2a03387303bf9d0a6d343e512b608fd6eace05c8428731e59')


class PayloadTests(unittest.TestCase):
    def test_legacy_closing_preserves_payload_and_only_opening_detaches(self):
        # Load exact class definition without importing scene/service dependencies.
        import ast
        src=Path(__file__).resolve().parents[1]/'sim_skills/full_pnp/legacy_model_bridge.py'
        tree=ast.parse(src.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ModelAdapter')
        scope={'np':np,'time':time,'json':json};exec(compile(ast.Module(body=[cls],type_ignores=[]),str(src),'exec'),scope)
        with tempfile.TemporaryDirectory() as directory:
            payload=[];q=[0.];stopped=SimpleNamespace(is_set=lambda:False)
            s=SimpleNamespace(output=Path(directory),step=0,stopped=stopped,step_hook=None,master=0,
                object_pose=lambda:[.3,0,.025,1,0,0,0],state=lambda:{'sim_step':0},
                robot=SimpleNamespace(get_qpos=lambda:q),scene=SimpleNamespace(get_contacts=lambda:[]),
                bilateral_pad_contact=lambda:q[0]<0,set_planning_payload=lambda carried:payload.append(carried))
            def gripper(opening):q[0]=-.91*(1-opening);return {'ok':True,'after':s.state(),'contact_latch':'PRIVATE'}
            s.gripper=gripper;adapter=scope['ModelAdapter'](s)
            for i,opening in enumerate((.45,.3,1.)):
                s.latest={'id':str(i),'time':time.monotonic(),'consumed':False}
                result=adapter.dispatch({'method':'chunk','observation_id':str(i),'actions':[{'type':'gripper','opening':opening}],'reason':'test'})
                self.assertTrue(result['ok']);self.assertNotIn('contact_latch',json.dumps(result))
                self.assertEqual(payload,[True] if i<2 else [True,False])
            adapter.records.close();adapter.private.close()

if __name__=='__main__':unittest.main()
