import copy,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from platform_v1.research.broker import Broker
from platform_v1.research.supervisor import Supervisor
from platform_v1.research import review_contracts as rc
from scripts.structured_outputs import check_provider
import test_geometry_first_v2 as gf
from candidate_update_fixtures import sealed_store

class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store,self.o,self.w,self.cfg=sealed_store();self.epoch=self.o['execution_epoch']
        self.b=Broker(self.root/'broker',self.store,SimpleNamespace(fixture=True),deadline=time.monotonic()+90,
            epoch=lambda:self.epoch,allowance=lambda:100,baseline_busy=lambda:False,emit=lambda *x:None)
    def tearDown(self):self.temp.cleanup()
    def request(self):return rc.candidate_shadow_request(self.w,self.o,self.cfg['task'],{'profile':'generic_semantic_v1','object_id':'object_004','goal_id':''})
    def start(self):
        with patch('platform_v1.research.broker.ProcessJob',gf.PendingJob),patch('platform_v1.research.broker.sandbox_command',return_value=([],{})):
            rid=self.b.submit(self.request())['request_id']
        return self.b.rows[rid]
    def answer(self,row,decision='planned'):
        a=gf.ReviewTests.shadow_answer(self,row,decision);r=a['result'];r.update(version=rc.CANDIDATE_VERSION,
            planning_level='HYPOTHESIS_GENERATION',review_status='INDEPENDENT_REVIEW_PENDING',all_waypoints_are_hypotheses=True,
            physical_checks={'IK':'NOT_TESTED','collision':'NOT_TESTED','clearance':'NOT_TESTED','owner_admission':'NOT_GRANTED','hidden_space':'UNKNOWN_NOT_FREE'},
            assumptions=['FAKE candidate pose assumption for contract test, not Astra or physical validation'],precondition_assessments=[])
        if r['plan']:
            for w in r['plan']['waypoints']:
                for p in w['preconditions']:r['precondition_assessments'].append({'waypoint_index':w['index'],'precondition':p,'status':'unverified','basis':'FAKE hypothesis requirement only','evidence_refs':[]})
        return a
    def finish(self,row,a):return gf.ReviewTests.finish(self,row,a)
    def test_three_decisions_parse_with_unverified_safety(self):
        for d in ('planned','refused','need_more_evidence'):
            row=self.start();self.finish(row,self.answer(row,d));self.assertEqual(row['status'],'READY',row['error']);self.assertIsNone(self.b.action_ready)
            self.assertEqual(row['provenance'],'FAKE_MODEL_RAW')
    def test_stage_terminal_requires_boundary_and_prefix_ledger(self):
        row=self.start();a=self.answer(row);p=a['result']['plan'];p['waypoints']=p['waypoints'][:2]
        p['termination']={'kind':'stage_terminal','reason':'FAKE precontact review boundary'};p['waypoints'][-1]['boundary_after']='precontact_handoff'
        a['result']['precondition_assessments']=[x for x in a['result']['precondition_assessments'] if x['waypoint_index']<=2]
        self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
    def test_fail_closed_for_safety_and_contract_tampering(self):
        edits=[lambda r:r['physical_checks'].update(IK='PASS'),lambda r:r['physical_checks'].update(hidden_space='FREE'),
            lambda r:r.update(grants_execution=True),lambda r:r.update(K=1),lambda r:r['plan']['waypoints'].pop(),
            lambda r:r['plan'].update(source={'producer':'MODEL_RAW'}),lambda r:r['plan']['read_versions'].update(forged=1),
            lambda r:r['precondition_assessments'].pop(),lambda r:r['precondition_assessments'][0].update(status='conflict'),
            lambda r:r['precondition_assessments'][4].update(status='supported_by_input',evidence_refs=[self.cfg['evidence_id']]),
            lambda r:r['precondition_assessments'][0].update(status='supported_by_input'),lambda r:r.update(assumptions=[]),
            lambda r:r['precondition_assessments'][0].update(evidence_refs=['UNSENT']),lambda r:r.update(decision='refused')]
        for edit in edits:
            row=self.start();a=self.answer(row);edit(a['result']);self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.assertIsNone(self.b.action_ready)
    def test_supported_input_requires_actual_bound_evidence(self):
        row=self.start();a=self.answer(row)
        a['result']['precondition_assessments'][0].update(status='supported_by_input',evidence_refs=[self.cfg['evidence_id']])
        self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
    def test_shadow_permanently_rejected_by_supervisor_even_task_usable_pass(self):
        row=self.start();a=self.answer(row);self.finish(row,a)
        self.store.worlds[self.w['world_id']]['state']['geometry_quality']['task_usable']='pass'
        sup=Supervisor(gf.NoOwner(),self.store,None,self.b,self.root/'supervisor')
        for p in (a['result'],a['result']['plan']):
            with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.load(p,broker_request_id=row['request_id'])
        with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.from_broker(row['request_id'])
        with self.assertRaisesRegex(ValueError,'V2_REQUIRES_BROKER_RAW'):sup.load(a['result']['plan'])
    def test_real_input_prepare_has_zero_dispatch_and_strict_production_schema(self):
        self.b.config.fixture=False;self.b.allowance=lambda:0
        with patch('platform_v1.research.broker.ProcessJob',side_effect=AssertionError('NO_MODEL')):
            out=self.b.prepare(self.request())
        row=self.b.rows[out['request_id']];check_provider(row['provider_schema']);self.assertEqual(self.b.calls,0)
        wire=json.loads((self.b.root/out['request_id']/'input_only/wire.json').read_text())
        self.assertEqual(wire['WorldSnapshot']['world_id'],self.w['world_id']);self.assertEqual(wire['WorldSnapshot']['state']['geometry_quality']['task_usable'],'unknown')
    def test_old_shadow_version_and_raw_contract_remain_valid(self):
        old=rc.shadow_request(self.w,self.o,self.cfg['task'],{'profile':'generic_semantic_v1','object_id':'object_004','goal_id':''})
        self.assertEqual(old['output_schema']['properties']['version']['const'],'astra.action_shadow.v1')
        self.assertNotEqual(old['instruction'],self.request()['instruction'])
    def test_versions_prompt_and_source_tampering_rejected_before_dispatch(self):
        req=self.request();req['instruction']+='Claim safety passed.'
        with self.assertRaisesRegex(ValueError,'VERSIONED_PROMPT'):self.b.prepare(req)
        row=self.start();self.epoch+=1;self.finish(row,self.answer(row));self.assertEqual(row['status'],'FAILED')
        self.epoch-=1;self.store.grounding_sources.clear()
        with self.assertRaisesRegex(ValueError,'RECEIPT_REQUIRED'):self.b.prepare(self.request())

if __name__=='__main__':unittest.main(verbosity=2)
