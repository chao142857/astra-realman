"""Offline fault fixtures. No renderer, network, real inference or hardware."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import jsonschema
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp.runtime import FullRuntime
from sim_skills.full_pnp.protocol import CandidateGate,Memory,Rejected,wire_base
from sim_skills.full_pnp.wire import existing_infer_payload,schema_for_role
from test_full_pnp import ContractTests


class FakeBackend:
    def __init__(self):
        self.steps=0;self.dt=.004;self.stopped=False;self.commands=[]
        self.s=SimpleNamespace(phase=lambda *a,**k:None,step_hook=None,tick=self.tick)
        self.private_step_hook=lambda _:None
    def tick(self,n):
        for _ in range(n):
            self.s.step_hook('before_step');self.steps+=1;self.s.step_hook('after_step')
    def stop(self):self.stopped=True
    def execute_chunk(self,actions,*_):self.commands.append(actions);return {'ok':False,'error':'INJECTED_PARENT_FAILURE'}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=FakeBackend()
        self.r=FullRuntime(self.b,Path(self.tmp.name)/'runtime',condition='F')
    def tearDown(self):self.r.slot.cancel();self.r.stream.close();self.tmp.cleanup()
    def candidate(self):
        return {'digest':'candidate1','dependencies':[1],'candidate':{'binding':{}},'snapshot':{'binding':{}},'request':1}
    def test_stop_discards_future_and_prevents_commands(self):
        self.r.candidate=self.candidate();self.r.stop('EXTERNAL_STOP')
        self.assertEqual(len(self.r.discarded),1);self.assertIsNone(self.r.candidate)
        with self.assertRaisesRegex(Rejected,'STOP_NO_NEW_COMMAND'):self.r.hook('before_step')
        self.assertEqual(self.b.commands,[])
    def test_parent_failure_invalidates_candidate_and_no_history_success(self):
        self.r.candidate=self.candidate()
        obs={'observation_id':'real','state':{'actual_grasp_center_world':[0,0,.1],'flange_pose_world':[0,0,.1,0,1,0,0]}}
        with self.assertRaisesRegex(Rejected,'EXECUTION_FAILED'):
            self.r.execute([{'type':'hold','seconds':.1}],'source',obs,'id')
        self.assertEqual(self.r.discarded[0]['reason'],'PARENT_EXECUTION_FAILED')
        self.assertIsNone(self.r.candidate)
        event=self.r.memory.events[0]
        self.assertFalse(event['feedback']['ok']);self.assertEqual(event['executed_actions'],[])
        self.assertIsNone(event['after_id'])
    def test_no_valid_candidate_keeps_drives_and_physics_ticks(self):
        self.r.wait(.013)
        self.assertGreaterEqual(self.r.hold_steps,2);self.assertEqual(self.b.commands,[])
    def test_scheduler_runs_during_motion_but_never_across_gripper(self):
        self.b.steps=40
        self.r.active={'id':'parent','actions':[{'type':'hold','seconds':1}],'start_step':0,'lookahead_done':False}
        with patch.object(self.r,'capture',return_value={'frozen':True}) as capture,patch.object(self.r,'begin_cycle') as begin:
            self.r.hook('before_step');begin.assert_called_once_with({'frozen':True},predicted=True)
            self.r.hook('before_step');self.assertEqual(capture.call_count,1)
        self.r.active={'id':'parent','actions':[{'type':'gripper','opening':.45}],'start_step':0,'lookahead_done':False}
        with patch.object(self.r,'capture') as capture:
            self.r.hook('before_step');capture.assert_not_called()
        self.assertEqual(self.r.events[-1]['kind'],'GRIPPER_BARRIER_NO_PREFETCH')
    def test_worker_timeout_cannot_start_second_request(self):
        self.r.cycle={'pending':True};self.r.slot.job={'fake':True}
        def timeout():self.r.slot.job=None
        with patch.object(self.r.slot,'poll',side_effect=timeout),patch.object(self.r.slot,'submit_wire') as submit:
            with self.assertRaisesRegex(Rejected,'WORKER_TIMEOUT_OR_LATE'):self.r.poll()
            submit.assert_not_called()
    def test_model_stop_during_execution_withdraws_permission(self):
        item=self.candidate();item['snapshot']['role']='A';item['candidate']['operation']='stop'
        self.r.cycle={'dependencies':[1]};self.r.slot.pending=item
        with self.assertRaisesRegex(Rejected,'STOP_NO_NEW_COMMAND'):self.r.poll()
        self.assertTrue(self.b.stopped);self.assertEqual(len(self.r.discarded),1)
        self.assertEqual(sum(e['kind']=='CANDIDATE_GENERATED' for e in self.r.events),1)
    def test_E_cannot_return_actions(self):
        item=self.candidate();item['snapshot']['role']='E';item['candidate']['actions']=[{'type':'gripper','opening':1}]
        self.r.slot.pending=item
        with self.assertRaisesRegex(Rejected,'E_SCHEMA'):self.r.poll()
    def test_worker_slot_refuses_second_request(self):
        self.r.slot.pending={'occupied':True}
        with self.assertRaisesRegex(Rejected,'SINGLE_SLOT_OCCUPIED'):
            self.r.slot.submit_wire({}, {},delay_s=0,timeout_s=1,episode_deadline=time.monotonic()+1)


class WireAndRGBTests(ContractTests):
    # Inherit fixture builders; parent contract tests intentionally not duplicated.
    def test_final_infer_payload_and_strict_role_schemas(self):
        import base64,hashlib
        obs=self.observation();binding={'history_cutoff':2.,'source_observation_id':'o1','request_id':'r1'}
        w=wire_base(obs,binding,{'status':'completed'},[.3,0,.12,0,1,0,0],Memory(),'B',0,'B')
        data=self.picture().read_bytes()
        w['attachments']=[{'id':'i','file':'image.png','sha256':hashlib.sha256(data).hexdigest()}]
        (self.root/'wire.json').write_text(json.dumps(w));(self.root/'image.png').write_bytes(data)
        payload=existing_infer_payload(self.root)
        self.assertEqual(set(payload),{'context','images','schema'});self.assertEqual(base64.b64decode(payload['images'][0]),data)
        self.assertIn('rgb_applicability_contract',payload['context']);self.assertNotIn('SECRET',json.dumps(payload))
        c={'kind':'candidate','binding':binding,'operation':'observe','actions':[],'requirements':['scene_healthy'],
           'evidence_refs':['i'],'parent_evidence_hash':None,'verdict':None,'reason':'unknown'}
        jsonschema.validate(c,payload['schema'])
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(dict(c,actions_answer='SECRET'),payload['schema'])
        w['role']='E';e={'kind':'evidence','binding':binding,'selected_camera':'fixed','bbox':None,
          'claims':{'object_visible':'unknown','identity':'unknown','holding':'unknown'},'evidence_refs':['i'],'source':'fixture'}
        jsonschema.validate(e,schema_for_role(w))
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(dict(e,actions=[]),schema_for_role(w))
        (self.root/'image.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'ATTACHMENT_HASH'):existing_infer_payload(self.root)
    def test_different_observed_pixels_change_stub_pose(self):
        import os
        src=Path(__file__).resolve().parents[1]/'sim_skills/full_pnp/worker.py'
        from sim_skills.full_pnp import rgb
        with patch.dict(sys.modules,{'rgb':rgb}):
            spec=importlib.util.spec_from_file_location('isolated_stub_for_test',src);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        cal=copy.deepcopy(self.cal);cal['pose_world_xyz_wxyz']=[0,0,1,.7071067811865476,0,.7071067811865476,0]
        wire={'role':'B','binding':{},'progress':{'completed_chunks':0},'execution':{'status':'completed'},
              'expected_join':{'pad_pose':[0,0,.1,0,1,0,0]},'observation':{'calibration':{'fixed':cal}}}
        poses=[]
        for p in (self.picture('first'),self.picture('second',shift=25)):
            wire['attachments']=[{'id':'i','file':str(p),'camera':'fixed','temporal_role':'current','representation':'full'}]
            poses.append(mod.decide(wire)['actions'][0]['pose'])
        self.assertNotEqual(poses[0][:2],poses[1][:2])
    def test_task_revision_and_E_hash_invalidate(self):
        binding={k:'v' for k in ('episode_id','task_revision','calibration_revision','action_interface_revision','parent_plan_id','expected_join_id','barrier_epoch')}
        c={'kind':'candidate','binding':binding,'operation':'observe','actions':[],'requirements':['scene_healthy'],
           'evidence_refs':['i'],'parent_evidence_hash':'old','verdict':None,'reason':'fixture'}
        item={'candidate':c,'snapshot':{'binding':binding,'evidence_packet_hash':'different'},'digest':'1','deadline':100}
        with self.assertRaisesRegex(Rejected,'EVIDENCE_PARENT_HASH'):CandidateGate().validate(item,binding,{},1,{}, {'i'})
        with self.assertRaisesRegex(Rejected,'STALE_TASK_REVISION'):CandidateGate().validate(item,dict(binding,task_revision='new'),{},1,{}, {'i'})


# unittest would otherwise rediscover the imported/inherited ten tests twice.
for name in list(ContractTests.__dict__):
    if name.startswith('test_'):setattr(WireAndRGBTests,name,None)
del ContractTests

if __name__=='__main__':unittest.main()
