"""Review regressions: synthetic RGB geometry and fake process/scene, never model/hardware."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp import dependencies as dep,rgb
from sim_skills.full_pnp.backend import FullTaskBackend
from sim_skills.full_pnp.protocol import Memory,wire_base,CandidateGate
from sim_skills.full_pnp.slot import FullSlot
from sim_skills.full_pnp.wire import parse_actual_raw,parse_bridge_record
from sim_skills.async_v1 import Rejected,sha
from scripts.audit_full_pnp_offline import audit


def geometry(tool=(0,0,.15),obj=(0,0,.025),goal=(.2,.1,0),q=-.3):
    cal={};features={}
    for name,origin in zip(('assembly','fixed','wrist'),((0,-.5,.45),(.5,0,.45),(0,.5,.5))):
        p=np.array(origin);x=-p/np.linalg.norm(p);y=np.cross([0,0,1],x);y/=np.linalg.norm(y);z=np.cross(x,y)
        quat=np.roll(Rotation.from_matrix(np.column_stack((x,y,z))).as_quat(),1)
        c={'pose_world_xyz_wxyz':[*origin,*quat],'intrinsic':[[300,0,320],[0,300,240],[0,0,1]],'resolution':[640,480]}
        f={'healthy':True}
        for key,point in (('object',obj),('goal',goal)):
            u,v=rgb.project(point,c);f[key]={'status':'visible','centroid':[u,v],'bbox':[u-15,v-15,u+15,v+15],
             'visible_pixels':900,'color_unit':[1,0,0] if key=='object' else [0,1,0]}
        cal[name]=c;features[name]=f
    obs={'observation_id':'synthetic','calibration':cal,'state':{'actual_grasp_center_world':list(tool),'flange_pose_world':[*tool,0,1,0,0],'gripper_master_rad':q,'sim_step':10}}
    return obs,features


class DependencyTests(unittest.TestCase):
    def check(self,actions,old,new):return dep.check(actions,old[0],new[0],old[1],new[1],model_requirements=['scene_healthy'])
    def move(self,p):return {'type':'move_pose','pose':[*p,0,1,0,0]}
    def test_empty_move_cannot_omit_object_anchor(self):
        old=geometry();new=geometry(obj=(.1,0,.025))
        out=self.check([self.move((.1,0,.10))],old,new)
        self.assertIn('object_static',out['owner_required']);self.assertEqual(out['status'],'invalid')
    def test_carry_allows_object_motion_with_tool_but_rejects_changed_goal(self):
        old=geometry(tool=(0,0,.10),obj=(0,0,.10));new=geometry(tool=(.1,0,.10),obj=(.1,0,.10))
        action=self.move((.2,.1,.10));out=self.check([action],old,new)
        self.assertEqual(out['status'],'valid');self.assertNotIn('object_static',out['owner_required'])
        changed=geometry(tool=(.1,0,.10),obj=(.1,0,.10),goal=(.35,.1,0))
        self.assertEqual(self.check([action],old,changed)['status'],'invalid')
    def test_carry_rejects_relative_slip(self):
        old=geometry(tool=(0,0,.10),obj=(0,0,.10));new=geometry(tool=(0,0,.10),obj=(.045,0,.10))
        self.assertEqual(self.check([self.move((.2,.1,.10))],old,new)['status'],'invalid')
    def test_upward_retreat_does_not_require_static_goal_or_object(self):
        old=geometry(tool=(0,0,.05),obj=(0,0,.025));new=geometry(tool=(0,0,.05),obj=(.01,0,.025),goal=(.4,.1,0))
        out=self.check([self.move((0,0,.12))],old,new)
        self.assertEqual(out['status'],'valid');self.assertEqual(out['action_kinds'],['bounded_upward_withdrawal'])
    def test_clear_empty_pregrasp_open_needs_no_goal(self):
        old=geometry()
        for f in old[1].values():f['goal']={'status':'unknown'}
        out=self.check([{'type':'gripper','opening':1}],old,old)
        self.assertEqual(out['current_hand_evidence']['status'],'empty');self.assertEqual(out['status'],'valid')
        self.assertEqual(out['action_kinds'],['empty_open'])
    def test_noop_unknown_and_possible_release_are_distinct(self):
        old=geometry(tool=(0,0,.025),q=-.3)
        release=self.check([{'type':'gripper','opening':1}],old,old)
        self.assertEqual(release['action_kinds'],['release']);self.assertEqual(release['status'],'invalid')
        for f in old[1].values():f['object']={'status':'unknown'}
        self.assertEqual(self.check([{'type':'gripper','opening':1}],old,old)['status'],'unknown')
        noop=self.check([{'type':'gripper','opening':1-.3/.91}],old,old)
        self.assertEqual(noop['status'],'valid');self.assertEqual(noop['action_kinds'],['noop'])
    def test_release_at_goal_valid_and_degenerate_cameras_unknown(self):
        old=geometry(tool=(.2,.1,.025),obj=(.2,.1,.025))
        self.assertEqual(self.check([{'type':'gripper','opening':1}],old,old)['status'],'valid')
        for k in old[0]['calibration']:old[0]['calibration'][k]=old[0]['calibration']['fixed']
        for k in old[1]:old[1][k]=old[1]['fixed']
        self.assertEqual(dep.hand_evidence(old[1],old[0]['calibration'],old[0]['state'])['status'],'unknown')
    def test_move_open_defers_spatial_release_check_until_boundary(self):
        old=geometry(tool=(0,0,.1),obj=(0,0,.1))
        out=self.check([self.move((.2,.1,.04)),{'type':'gripper','opening':1}],old,old)
        self.assertEqual(out['status'],'valid');self.assertIn('gripper_deferred_to_actual_boundary',out['action_kinds'])
    def test_gate_rejects_model_only_rgb_vote_for_move(self):
        b={k:'v' for k in ('episode_id','task_revision','calibration_revision','action_interface_revision','parent_plan_id','expected_join_id','barrier_epoch')}
        c={'kind':'candidate','binding':b,'operation':'chunk','actions':[self.move((.1,0,.1))],'requirements':['scene_healthy'],
           'evidence_refs':['i'],'parent_evidence_hash':None,'verdict':None,'reason':'fixture'}
        item={'candidate':c,'snapshot':{'binding':b,'evidence_packet_hash':None},'digest':'x','deadline':100}
        with self.assertRaisesRegex(Rejected,'OWNER_DEPENDENCIES_MISSING'):CandidateGate().validate(item,b,{},0,{'status':'valid'},{'i'})


class BoundaryTests(unittest.TestCase):
    def test_partial_prefix_survives_guard_rejection_and_no_gripper(self):
        with tempfile.TemporaryDirectory() as temp:
            b=object.__new__(FullTaskBackend);b.owner=threading.get_ident();b.commit_counter=0;b.s=SimpleNamespace(output=Path(temp))
            calls=[];moved=[]
            def dispatch(r):
                calls.append(r);moved.append(True)
                return {'ok':True,'results':[{'action':r['actions'][0],'result':{'ok':True}}]}
            b.adapter=SimpleNamespace(dispatch=dispatch)
            def guard(a):self.assertTrue(moved);return {'observation_id':'fresh'},{'status':'invalid','action_kinds':['close']}
            b.gripper_guard=guard
            actions=[{'type':'move_pose','pose':[0,0,.05,0,1,0,0]},{'type':'gripper','opening':.45}]
            result=b.execute_chunk(actions,{'owner_admitted':True,'commit_observation_id':'c','candidate_id':'x'},{'observation_id':'c'})
            self.assertFalse(result['ok']);self.assertEqual(result['unexecuted_count'],1);self.assertEqual(len(result['results']),1)
            self.assertEqual(len(calls),1);self.assertEqual(calls[0]['actions'],actions[:1])
    def test_guard_pass_dispatches_using_real_fresh_observation_and_noop_skips(self):
        with tempfile.TemporaryDirectory() as temp:
            b=object.__new__(FullTaskBackend);b.owner=threading.get_ident();b.commit_counter=0;b.s=SimpleNamespace(output=Path(temp))
            calls=[]
            def dispatch(r):calls.append(r);return {'ok':True,'results':[{'action':a,'result':{'ok':True}} for a in r['actions']]}
            b.adapter=SimpleNamespace(dispatch=dispatch)
            action={'type':'gripper','opening':1};ticket={'owner_admitted':True,'commit_observation_id':'c','candidate_id':'x'}
            b.gripper_guard=lambda _ :({'observation_id':'actual-new'},{'status':'valid','action_kinds':['empty_open']})
            self.assertTrue(b.execute_chunk([action],ticket,{'observation_id':'c'})['ok']);self.assertEqual(calls[0]['observation_id'],'actual-new')
            b.gripper_guard=lambda _ :({'observation_id':'actual-new2'},{'status':'valid','action_kinds':['noop']})
            self.assertTrue(b.execute_chunk([action],ticket,{'observation_id':'c'})['results'][0]['result']['noop'])
            self.assertEqual(len(calls),1)
    def test_chunk_13_rejected_but_observe_finish_allowed_after_12(self):
        from test_full_pnp_runtime import FakeBackend
        from sim_skills.full_pnp.runtime import FullRuntime
        with tempfile.TemporaryDirectory() as temp:
            b=FakeBackend();b.finish=lambda _: {'status':'PASS'}
            r=FullRuntime(b,Path(temp)/'episode',condition='B');r.completed=11
            obs=geometry()[0]
            b.execute_chunk=lambda actions,*_: {'ok':True,'results':[{'action':actions[0],'result':{'ok':True}}]}
            with patch.object(r,'capture',return_value=obs):r.execute([{'type':'hold','seconds':.1}],'s',obs,'twelfth')
            self.assertEqual(r.completed,12)
            with self.assertRaisesRegex(Rejected,'CHUNK_CAP_12'):r.execute([{'type':'hold','seconds':1}],'s',{},'c')
            operations=[({'operation':'observe'},{}),({'operation':'finish','verdict':'unknown'}, {})]
            with patch.object(r,'begin_cycle'),patch.object(r,'capture',return_value={}),patch.object(r,'wait'),patch.object(r,'adopt',side_effect=operations):
                result=r.run()
            self.assertEqual(result['status'],'PASS');self.assertEqual(b.commands,[]);self.assertEqual(result['completed_chunks'],12)
    def test_actual_boundary_captures_RGB_and_rejects_object_motion(self):
        from test_full_pnp_runtime import FakeBackend
        from sim_skills.full_pnp.runtime import FullRuntime
        with tempfile.TemporaryDirectory() as temp:
            r=FullRuntime(FakeBackend(),Path(temp)/'episode',condition='F')
            old,fo=geometry(tool=(0,0,.05));new,fn=geometry(tool=(0,0,.05),obj=(.15,0,.025))
            r.active={'guard_source':old,'expected':[0,0,.05,0,1,0,0]}
            with patch.object(r,'capture',return_value=new) as capture,patch('sim_skills.full_pnp.runtime.rgb.features',side_effect=[fo,fn]):
                _,check=r.before_gripper({'type':'gripper','opening':.45})
            capture.assert_called_once_with('PRE_GRIPPER_FRESH');self.assertEqual(check['status'],'invalid')
            self.assertEqual(r.slot.calls,0);r.stream.close()
    def test_thirteenth_candidate_is_discarded_before_adoption(self):
        from test_full_pnp_runtime import FakeBackend
        from sim_skills.full_pnp.runtime import FullRuntime
        with tempfile.TemporaryDirectory() as temp:
            r=FullRuntime(FakeBackend(),Path(temp)/'episode',condition='B');r.completed=12
            r.candidate={'candidate':{'operation':'chunk'},'cycle':{'obs':{'observation_id':'source'}},'digest':'x','request':13,'dependencies':[]}
            with patch.object(r,'capture') as capture:
                with self.assertRaisesRegex(Rejected,'CHUNK_CAP_12'):r.adopt()
                capture.assert_not_called()
            self.assertEqual(r.adopted,[]);self.assertEqual(len(r.discarded),1);r.stream.close()


def audit_fixture(root,case):
    """Persist explicitly synthetic failed-attempt evidence using actual slot/auditor code."""
    root=Path(root);(root/'scene').mkdir(parents=True,exist_ok=False)
    image=Image.new('RGB',(640,480),'gray');d=ImageDraw.Draw(image);d.rectangle((100,100,150,150),fill='red');d.rectangle((300,300,360,340),fill='green')
    path=root/'scene/image.png';image.save(path)
    started=time.monotonic()
    obs,_=geometry();obs.update(observation_id='SYNTHETIC_OBSERVATION',images={c:str(path) for c in ('assembly','fixed','wrist')},captured_monotonic=started,capture_span_s=0.)
    binding={'episode_id':'fixture','request_id':'request-001','source_observation_id':obs['observation_id'],'source_step':10,
     'source_observation_sha256':sha({'id':obs['observation_id'],'state':obs['state'],'images':{k:hashlib.sha256(path.read_bytes()).hexdigest() for k in obs['images']}}),
     'history_cutoff':started,'preparation_started_monotonic':time.monotonic()}
    wire=wire_base(obs,binding,{'status':'completed'},[0,0,.15,0,1,0,0],Memory(),'B',0,'B')
    events=[{'kind':'OBSERVATION','wall_monotonic':started,'wall_elapsed_s':0.,'physics_elapsed_s':0.,'data':dict(obs,reason='SYNTHETIC_FIXTURE')}]
    def emit(k,d):
        now=time.monotonic();events.append({'kind':k,'wall_monotonic':now,'wall_elapsed_s':now-started,'physics_elapsed_s':0.,'data':d})
    slot=FullSlot(root/'episode/workers',emit)
    class Process:
        pid=12345;returncode=None
        def poll(self):return self.returncode
        def terminate(self):self.returncode=-15
        def kill(self):self.returncode=-9
        def wait(self,**_):return self.returncode
    proc=Process()
    def launch(*args,**kwargs):
        if case=='launch_failure':raise OSError('INJECTED_LAUNCH_FAILURE')
        raw='{"candidate":'
        if case in ('nonzero_exit','missing_candidate'):raw=json.dumps({'usage':{'input_tokens':42,'cached_input_tokens':7}})
        if case=='late':
            snapshot=json.loads((kwargs['cwd']/'wire.json').read_text())
            candidate={'kind':'candidate','binding':snapshot['binding'],'operation':'observe','actions':[],'requirements':['scene_healthy'],
               'evidence_refs':[v['id'] for v in snapshot['attachments']],'parent_evidence_hash':None,'verdict':None,'reason':'LATE_RAW_FIXTURE'}
            raw=json.dumps({'candidate':candidate,'usage':None})
        kwargs['stdout'].write(raw);kwargs['stdout'].flush()
        if case in ('partial_raw','missing_candidate','late'):proc.returncode=0
        if case=='nonzero_exit':proc.returncode=7
        return proc
    if case=='prepare_failure':obs['images']['fixed']=str(root/'missing.png')
    try:
        with patch('sim_skills.full_pnp.slot.subprocess.Popen',side_effect=launch):
            slot.submit_wire(wire,obs,delay_s=0,timeout_s=1,episode_deadline=time.monotonic()+10)
            if case=='cancelled':slot.cancel()
            elif case in ('timeout','late'):
                slot.job['deadline']=time.monotonic()-1;slot.poll()
            else:slot.poll()
    except Exception as exc:emit('FAULT',{'error':repr(exc),'expected_fixture_failure':True})
    finally:slot.cancel()
    (root/'episode/timeline.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    (root/'result.json').write_text(json.dumps({'status':'FAIL','condition':'B','source':'SYNTHETIC_FAKE_PROCESS_NOT_MODEL_OR_PHYSICS',
      'real_model_calls':0,'hardware_calls':0,'episode':{'candidate_generated':0,'candidate_adopted':0,'candidate_discarded':0}}))
    return audit(root)


class AttemptTests(unittest.TestCase):
    def test_all_failure_stages_produce_audit_and_keep_null_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            for case in ('prepare_failure','launch_failure','partial_raw','cancelled','timeout'):
                with self.subTest(case=case):
                    report=audit_fixture(Path(temp)/case,case)
                    self.assertTrue(report['audit_complete']);self.assertEqual(report['episode_status'],'FAIL')
                    self.assertEqual(len(report['requests']),1);self.assertIsNone(report['requests'][0]['usage_raw'])
                    self.assertIsNone(report['requests'][0]['candidate'])
                    self.assertTrue(report['requests'][0]['stages'])
    def test_nonzero_missing_candidate_usage_and_late_raw_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            for case in ('nonzero_exit','missing_candidate','late'):
                report=audit_fixture(Path(temp)/case,case);row=report['requests'][0]
                self.assertTrue(report['audit_complete'])
                if case=='late':
                    self.assertEqual(row['status'],'LATE_OR_CANCELLED');self.assertIsNotNone(row['candidate'])
                    self.assertIsNone(row['phase_duration_s']['submit'])
                else:
                    self.assertEqual(row['usage_raw'],{'input_tokens':42,'cached_input_tokens':7})
                    self.assertIsNone(row['candidate']);self.assertEqual(row['status'],'PARSE_FAILED')
    def test_actual_raw_preserved_B_A_E_and_failure_never_falls_back(self):
        b={'request_id':'r'};w={'role':'B','binding':b,'attachments':[{'id':'i'}],'evidence_packet_hash':None}
        answer={'kind':'candidate','binding':b,'operation':'chunk','actions':[{'type':'gripper','opening':.731}],
         'requirements':['scene_healthy'],'evidence_refs':['i'],'parent_evidence_hash':None,'verdict':None,'reason':'RAW_FIXTURE'}
        for role in ('B','A'):
            w['role']=role;self.assertEqual(parse_bridge_record({'return_code':0,'error':None,'raw':json.dumps(answer)},w),answer)
        w['role']='E';e={'kind':'evidence','binding':b,'selected_camera':'wrist','bbox':[.13,.24,.66,.87],
            'claims':{'object_visible':'unknown','identity':'hypothesis','holding':'unknown'},'evidence_refs':['i'],'source':'RAW_FIXTURE'}
        self.assertEqual(parse_actual_raw(json.dumps(e),w),e)
        for record in ({'return_code':1,'raw':json.dumps(e)},{'return_code':0,'error':'API','raw':json.dumps(e)},
                       {'return_code':0,'raw':'{"partial":'},{'return_code':0,'raw':'{}'}):
            with self.assertRaises(Exception):parse_bridge_record(record,w)


if __name__=='__main__':unittest.main()
