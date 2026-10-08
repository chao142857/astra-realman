"""Offline protocol qualification. Nothing in this suite calls Astra or hardware."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.async_v1 import AsyncRuntime,Gate,Rejected,StubSlot,worker_environment
from sim_skills.async_fixture import FixtureBackend

TARGETS=json.loads((Path(__file__).resolve().parents[1]/'config/sim_rm65_targets.json').read_text())

class AsyncTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def episode(self,name,**kwargs):
        b=FixtureBackend(self.root/name/'scene')
        r=AsyncRuntime(b,TARGETS,self.root/name/'episode',delay_s=.06,lookahead_steps=20,
                       hold_limit_s=.04,request_timeout_s=2,**kwargs)
        summary=r.run();return r,summary
    def overlap(self,r):
        actions=[e for e in r.events if e['kind'].startswith('PRIMITIVE_') and e['data']['primitive']['name']=='approach']
        requests=[e for e in r.events if e['kind']=='REQUEST_END' and e['data']['request']==2]
        if not requests:return 0
        rec=requests[0]['data']['record']
        return max(0,min(actions[1]['wall_monotonic'],rec['worker_finished_monotonic'])-
                     max(actions[0]['wall_monotonic'],rec['worker_started_monotonic']))
    def test_b0_b1_overlap_adoption_and_same_pacing(self):
        sync,s0=self.episode('sync',condition='B0');async_,s1=self.episode('async',condition='B1')
        for r,s in ((sync,s0),(async_,s1)):
            self.assertEqual(s['status'],'PASS',s);self.assertEqual(s['stub_calls'],2)
            self.assertEqual(s['model_calls'],0);self.assertEqual(s['max_in_flight'],1);self.assertEqual(s['max_pending'],1)
            self.assertGreaterEqual(s['step_interval_min_s'],s['dt']*.99)
            self.assertEqual(len([e for e in r.events if e['kind']=='CANDIDATE_ADOPTED']),2)
        self.assertEqual(self.overlap(sync),0);self.assertGreater(self.overlap(async_),.04)
        self.assertEqual(s0['primitive_sequence_sha256'],s1['primitive_sequence_sha256'])
        adopted=[e for e in async_.events if e['kind']=='CANDIDATE_ADOPTED'][1]['data']
        self.assertGreater(adopted['fresh_commit_evidence']['commit_state_step'],adopted['binding']['source_step'])
    def test_known_goal_keeps_one_shot_strong_baseline(self):
        for condition in ('B0','B1'):
            r,s=self.episode(condition,condition=condition,scenario='known-goal')
            self.assertEqual(s['status'],'PASS');self.assertEqual(s['stub_calls'],1)
            self.assertEqual(len(s['primitive_sequence']),4)
    def test_goal_change_invalidates_and_holds_without_releasing(self):
        r,s=self.episode('changed',case='target-change')
        self.assertEqual(s['status'],'HOLD_NO_VALID_CONTINUATION')
        self.assertEqual(len(s['primitive_sequence']),1)
        self.assertIn('TARGET_OR_GOAL_CHANGED',[e['data'].get('reason') for e in r.events])
        snapshots=list((r.root/'worker').glob('*/input_only/snapshot.json'))
        self.assertTrue(all(json.loads(p.read_text())['binding']['target_revision']==TARGETS['revision'] for p in snapshots))
    def test_execution_failure_invalidates_future(self):
        r,s=self.episode('failure',case='execution-failure')
        self.assertEqual(s['status'],'FAIL');self.assertIn('INJECTED_EXECUTION_FAILURE',s['error'])
        self.assertIsNone(r.slot.pending);self.assertIsNone(r.slot.job)
        self.assertEqual(len(s['primitive_sequence']),1)
    def test_external_stop_cancels_worker_and_no_new_action(self):
        r,s=self.episode('stop',case='stop');self.assertEqual(s['status'],'STOPPED')
        self.assertEqual(len(s['primitive_sequence']),1)
        step=r.b.steps
        with self.assertRaises(Rejected):r.admit()
        self.assertEqual(step,r.b.steps);self.assertIsNone(r.slot.job)
    def test_model_stop_is_terminal(self):
        r,s=self.episode('model-stop',case='model-stop')
        self.assertEqual(s['status'],'STOPPED');self.assertTrue(r.b.stopped)
        self.assertEqual(len(s['primitive_sequence']),1)
        self.assertFalse(any(e['kind']=='PRIMITIVE_END' for e in r.events))
    def test_late_task_hold_is_meaningful_no_release(self):
        r,s=self.episode('deny',case='deny');self.assertEqual(s['status'],'HOLD_NO_VALID_CONTINUATION')
        self.assertEqual(len(s['primitive_sequence']),1)
        self.assertTrue(any(e['kind']=='CANDIDATE_HOLD' for e in r.events))
    def test_timeout_cancels_no_retry_and_no_candidate_holds(self):
        b=FixtureBackend(self.root/'scene')
        r=AsyncRuntime(b,TARGETS,self.root/'episode',case='late',delay_s=.01,lookahead_steps=20,
                       request_timeout_s=.3,hold_limit_s=.04)
        s=r.run();self.assertEqual(s['stub_calls'],2);self.assertEqual(s['status'],'HOLD_NO_VALID_CONTINUATION')
        self.assertIn('REQUEST_TIMEOUT',[e['data'].get('reason') for e in r.events])
        self.assertTrue(any(e['kind']=='NO_VALID_CANDIDATE' for e in r.events))
    def test_wire_snapshot_hash_projection_owner_and_slots(self):
        b=FixtureBackend(self.root/'scene');r=AsyncRuntime(b,TARGETS,self.root/'episode')
        obs=b.observe();r.request('approach_checkpoint',obs)
        snap=r.slot.job['snapshot'];path=r.slot.job['run']/'input_only/snapshot.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),r.slot.job['digest'])
        text=path.read_text()
        for secret in ('private_object_truth','contact_truth','final_score','MUST_NOT_REACH'):self.assertNotIn(secret,text)
        self.assertEqual(len(snap['observation']['attachments']),3)
        self.assertEqual(snap['expected_join']['evidence_status'],'EXPECTED_NOT_OBSERVED')
        self.assertEqual(len(snap['catalog']['expanded_sequence']),4)
        with self.assertRaisesRegex(Rejected,'SINGLE_SLOT_OCCUPIED'):r.request('approach_checkpoint',obs)
        errors=[]
        def other():
            try:r.slot.poll()
            except Exception as exc:errors.append(str(exc))
        t=threading.Thread(target=other);t.start();t.join();self.assertEqual(errors,['OWNER_ONLY'])
        r.slot.job['process'].wait(timeout=2);r.slot.poll()
        with self.assertRaisesRegex(Rejected,'SINGLE_SLOT_OCCUPIED'):r.request('approach_checkpoint',obs)
        r.stop();b.step_hook=None;r.stream.close()
    def test_gate_rejects_duplicate_stale_plan_revision_join_invalid_state(self):
        r,s=self.episode('base')
        path=r.root/'worker/request-02';snap=json.loads((path/'input_only/snapshot.json').read_text())
        candidate=json.loads((path/'worker.json').read_text())['candidate']
        item={'candidate':candidate,'snapshot':snap,'digest':candidate['binding']['snapshot_sha256'],'deadline':100}
        state={'actual_grasp_center_world':TARGETS['approach'][:3],'flange_pose_world':TARGETS['approach'],'sim_step':999}
        kw=dict(state=state,parent_plan=snap['binding']['parent_plan_id'],join_id='AFTER_APPROACH',revision=TARGETS['revision'],goal_epoch=1,parent_ok=True,now=10,stopped=False)
        gate=Gate();self.assertEqual(gate.validate(item,**kw)[0],'finish_place')
        with self.assertRaisesRegex(Rejected,'DUPLICATE_COMMIT'):gate.validate(item,**kw)
        for change,reason in (({'parent_plan':'other'},'PLAN_OR_JOIN_CHANGED'),({'revision':'other'},'TARGET_OR_GOAL_CHANGED'),
                              ({'parent_ok':False},'PARENT_EXECUTION_FAILED'),({'now':101},'CANDIDATE_EXPIRED'),
                              ({'stopped':True},'STOPPED'),({'join_id':'different'},'PLAN_OR_JOIN_CHANGED'),({'state':dict(state,actual_grasp_center_world=[0,0,0])},'JOIN_STATE_MISMATCH'),
                              ({'state':dict(state,flange_pose_world=[0,0,0,0,0,0,0])},'INVALID_JOIN_STATE')):
            with self.assertRaisesRegex(Rejected,reason):Gate().validate(item,**dict(kw,**change))
    def test_late_completed_result_is_never_adopted(self):
        b=FixtureBackend(self.root/'scene');r=AsyncRuntime(b,TARGETS,self.root/'episode',delay_s=.01)
        r.request('approach_checkpoint',b.observe());r.slot.job['process'].wait(timeout=2)
        r.slot.job['deadline']=time.monotonic()-1;r.slot.poll()
        self.assertIsNone(r.slot.pending)
        self.assertIn('LATE_RESULT',[e['data'].get('reason') for e in r.events])
        r.stop();b.step_hook=None;r.stream.close()
    def test_original_common_check_failure_prevents_execution(self):
        b=FixtureBackend(self.root/'scene');r=AsyncRuntime(b,TARGETS,self.root/'episode',delay_s=.01)
        with patch.object(b,'check',return_value={'ok':False,'reason':'fixture holding lost'}):s=r.run()
        self.assertEqual(s['status'],'FAIL');self.assertIn('COMMON_CHECK_FAILED',s['error'])
        self.assertEqual(s['primitive_sequence'],[]);self.assertEqual(s['stub_calls'],1)
    def test_episode_budget_includes_request_preparation(self):
        b=FixtureBackend(self.root/'scene');r=AsyncRuntime(b,TARGETS,self.root/'episode',budget_s=.01)
        with patch('sim_skills.async_v1.worker_environment',side_effect=lambda *a:(time.sleep(.02) or worker_environment(*a))):
            with self.assertRaisesRegex(Rejected,'NO_REQUEST_BUDGET'):r.request('approach_checkpoint',b.observe())
        self.assertIsNone(r.slot.job);r.stop();b.step_hook=None;r.stream.close()

if __name__=='__main__':unittest.main()
