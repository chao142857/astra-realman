"""Production frozen W2 inputs + explicitly FAKE responses; zero model dispatch."""
import copy,hashlib,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from platform_v1.research.broker import Broker
from platform_v1.research import action_proposal as ap
from platform_v1.research.contracts import digest
from platform_v1.research.supervisor import Supervisor
from scripts.structured_outputs import check_provider,compile_schema
from candidate_update_fixtures import sealed_store,workspace
import test_geometry_first_v2 as gf

class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store,self.o,self.w,self.cfg=sealed_store();self.epoch=self.o['execution_epoch']
        self.b=Broker(self.root/'broker',self.store,SimpleNamespace(fixture=True),deadline=time.monotonic()+90,
            epoch=lambda:self.epoch,allowance=lambda:100,baseline_busy=lambda:False,emit=lambda *x:None)
    def tearDown(self):self.tmp.cleanup()
    def request(self):return ap.proposal_request(self.w,self.o)
    def start(self):
        with patch('platform_v1.research.broker.ProcessJob',gf.PendingJob),patch('platform_v1.research.broker.sandbox_command',return_value=([],{})):
            rid=self.b.submit(self.request())['request_id']
        return self.b.rows[rid]
    def answer(self,row,decision='planned'):
        r={'version':ap.VERSION,'decision':decision,'proposal':None,'reason':'FAKE SOFTWARE CONTRACT TEST',
            'assumptions':['FAKE pose hypothesis, not verified free space'],'unknowns':['clearance unknown'],'additional_claims':[]}
        if decision=='planned':
            origin=row['proposal_host']['plan_fields']['origin_pose_world']
            r['proposal']={'waypoints':[{'index':i,'type':'move_pose','pose':[origin[0]+.025*i,*origin[1:]],
                'nominal_end_offset_s':2*i,'prediction_dependencies':list(range(1,i)),'boundary_after':'none'} for i in range(1,5)],
                'termination':{'kind':'horizon_filled','reason':'FAKE test only'}}
        return {'evidence_refs':[x['id'] for x in row['attachments']]+row['binding']['evidence_ids'],'result':r}
    def finish(self,row,a):return gf.ReviewTests.finish(self,row,a)
    def claim(self,row,name='measured_join'):
        return {'waypoint_index':1,'precondition':name,'scope':'current','status':'supported_by_input',
            'basis':'FAKE claim limited to captured fact','evidence_refs':[row['attachments'][0]['id']]}
    def reject(self,edit,match=None):
        row=self.start();a=self.answer(row);edit(a);self.finish(row,a)
        self.assertEqual(row['status'],'FAILED',row);self.assertIsNone(self.b.action_ready)
        if match:self.assertIn(match,row['error'])
    def test_three_decisions_through_actual_broker(self):
        for d in ('planned','refused','need_more_evidence'):
            row=self.start();a=self.answer(row,d);self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
            self.assertEqual(row['parsed'],a);self.assertIsNone(row['usage_raw']);self.assertIsNone(self.b.action_ready)
            self.assertEqual(row['derived_shadow']['K'],0);self.assertFalse(row['derived_shadow']['grants_execution'])
            self.assertEqual(row['derived_shadow']['source']['producer'],'FAKE_MODEL_RAW')
    def test_exact_waypoints_preserved_and_separate_hashes(self):
        row=self.start();a=self.answer(row);before=copy.deepcopy(a);self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
        derived=row['derived_shadow'];plan=derived['plan']
        stripped=[{k:v for k,v in w.items() if k!='preconditions'} for w in plan['waypoints']]
        self.assertEqual(stripped,before['result']['proposal']['waypoints']);self.assertEqual(a,before)
        self.assertEqual(derived['proposal_sha256'],digest(a['result']));self.assertEqual(derived['internal_plan_sha256'],digest(plan))
        self.assertNotEqual(derived['proposal_sha256'],derived['internal_plan_sha256'])
        self.assertEqual(plan['origin_pose_world'],[*self.o['state']['actual_grasp_center_world'],*self.o['state']['flange_pose_world'][3:]])
        self.assertTrue(all(x['status']=='unverified' for x in derived['requirements']))
        self.assertEqual(len(derived['requirements']),20)
        folder=self.b.root/row['request_id']
        self.assertEqual(hashlib.sha256((folder/'model_proposal.json').read_bytes()).hexdigest(),derived['proposal_sha256'])
        self.assertEqual(hashlib.sha256((folder/'internal_plan.json').read_bytes()).hexdigest(),derived['internal_plan_sha256'])
    def test_all_host_fields_rejected_at_all_model_levels(self):
        host=['origin_pose_world','world_id','world_revision','execution_epoch','read_versions','task','task_binding','H','m','K','grants_execution','source','evidence_refs','preconditions']
        for level in ('result','proposal','waypoint'):
            for name in host:
                def edit(a):
                    r=a['result'];target=r if level=='result' else (r['proposal'] if level=='proposal' else r['proposal']['waypoints'][0]);target[name]='FORGED'
                self.reject(edit)
    def test_first_step_measured_origin_enforced(self):
        self.reject(lambda a:a['result']['proposal']['waypoints'][0]['pose'].__setitem__(1,1.0),'COARSE_STEP_TOO_LARGE')
        self.reject(lambda a:a['result']['proposal']['waypoints'][0]['pose'].__setitem__(0,.8),'COARSE_STEP_TOO_LARGE')
    def test_bounds_units_quaternion_length_time_prefix(self):
        edits=[lambda p:p['waypoints'][0]['pose'].__setitem__(0,300),
            lambda p:p['waypoints'][0]['pose'].__setitem__(3,2),
            lambda p:p['waypoints'][0]['pose'].__setitem__(slice(3,None),[0,0,0,1]),
            lambda p:p['waypoints'][0]['pose'].__setitem__(0,float('nan')),
            lambda p:p['waypoints'].pop(),lambda p:p['waypoints'].append(copy.deepcopy(p['waypoints'][-1])),
            lambda p:p['waypoints'][1].update(nominal_end_offset_s=3),
            lambda p:p['waypoints'][1].update(prediction_dependencies=[]),
            lambda p:p['waypoints'][0].update(type='gripper'),lambda p:p['waypoints'][0].update(index=0),
            lambda p:p['waypoints'][0]['pose'].__setitem__(0,self.o['state']['actual_grasp_center_world'][0]+.001)]
        for edit in edits:self.reject(lambda a:edit(a['result']['proposal']))
    def test_noop_and_workspace_rejection(self):
        self.reject(lambda a:a['result']['proposal']['waypoints'][0].update(pose=[*self.o['state']['actual_grasp_center_world'],*self.o['state']['flange_pose_world'][3:]]),'NOOP_PADDING')
    def test_reasonable_stage_terminal_and_boundary_conflicts(self):
        row=self.start();a=self.answer(row);p=a['result']['proposal'];p['waypoints']=p['waypoints'][:2]
        p['termination']={'kind':'stage_terminal','reason':'FAKE precontact stop'};p['waypoints'][-1]['boundary_after']='precontact_handoff'
        self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
        self.reject(lambda a:a['result']['proposal']['termination'].update(kind='stage_terminal'),'UNJUSTIFIED_STAGE_TERMINAL')
        self.reject(lambda a:a['result']['proposal']['waypoints'][-1].update(boundary_after='precontact_handoff'),'CROSSED_STAGE_BOUNDARY')
    def test_current_fact_receipts_do_not_fulfill_future_requirements(self):
        row=self.start();a=self.answer(row)
        for name in ('measured_join','current_geometry','visibility','target_identity_hypothesis'):
            c=self.claim(row,name)
            if name=='target_identity_hypothesis':c['evidence_refs']=row['binding']['evidence_ids']
            a['result']['additional_claims'].append(c)
        self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
        d=row['derived_shadow'];self.assertEqual(len(d['current_fact_receipts']),4)
        self.assertTrue(all(x['status']=='unverified' for x in d['requirements']))
        self.assertTrue(all(not x['satisfies_future_waypoint'] for x in d['current_fact_receipts']))
    def test_missing_forged_unbound_and_future_claims_rejected(self):
        changes=[{'evidence_refs':[]},{'evidence_refs':['UNSENT']},{'scope':'future'},
            {'precondition':'owner_admission'},{'waypoint_index':2},{'status':'conflict'},
            {'precondition':'target_identity_hypothesis'}]
        for change in changes:
            row=self.start();a=self.answer(row);c=self.claim(row);c.update(change);a['result']['additional_claims']=[c]
            self.finish(row,a);self.assertEqual(row['status'],'FAILED',row['error'])
        row=self.start();a=self.answer(row);a['result']['additional_claims']=[self.claim(row)];a['evidence_refs']=row['binding']['evidence_ids']
        self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.assertIn('UNBOUND_PROPOSAL_CLAIM',row['error'])
    def test_null_proposal_and_assumption_contract(self):
        self.reject(lambda a:a['result'].update(decision='refused'),'PROPOSAL_DECISION')
        self.reject(lambda a:a['result'].update(proposal=None),'PROPOSAL_DECISION')
        self.reject(lambda a:a['result'].update(assumptions=[]),'ASSUMPTIONS')
    def test_stale_epoch_world_and_mutated_observation_refused(self):
        row=self.start();a=self.answer(row);self.epoch+=1;self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.epoch-=1
        row=self.start();a=self.answer(row);self.store.revision+=1;self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.store.revision-=1
        row=self.start();a=self.answer(row);self.store.observations[self.o['observation_id']]['state']['actual_grasp_center_world'][1]=1
        self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_host_read_versions_and_origin_cannot_be_mutated(self):
        row=self.start();a=self.answer(row);row['proposal_host']['plan_fields']['read_versions']['FORGED']=1
        self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.assertIn('STALE_OR_MODIFIED',row['error'])
        row=self.start();a=self.answer(row);row['proposal_host']['plan_fields']['origin_pose_world'][1]=1
        self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_shadow_excluded_from_all_supervisor_paths_even_task_usable_pass(self):
        row=self.start();a=self.answer(row);self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
        self.store.worlds[self.w['world_id']]['state']['geometry_quality']['task_usable']='pass'
        s=Supervisor(gf.NoOwner(),self.store,None,self.b,self.root/'supervisor')
        for p in (a['result'],row['derived_shadow'],row['derived_shadow']['plan']):
            with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):s.load(p,broker_request_id=row['request_id'])
        with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):s.from_broker(row['request_id'])
        with self.assertRaisesRegex(ValueError,'V2_REQUIRES_BROKER_RAW'):s.load(row['derived_shadow']['plan'])
        self.assertEqual(s.plans,{});self.assertIsNone(self.b.action_ready)
    def test_read_only_diagnosis_preserves_actual_raw(self):
        from scripts.diagnose_candidate_raw import diagnose
        source=workspace()/'candidate-v2-a-h4-authorized-01-20261010'
        before=(source/'RAW_RESPONSE.json').read_bytes();d=diagnose(source)
        self.assertEqual((source/'RAW_RESPONSE.json').read_bytes(),before)
        r=json.loads(json.loads(before)['raw'])['result']
        self.assertEqual([x['original_waypoint'] for x in d['waypoint_table']],r['plan']['waypoints'])
        self.assertAlmostEqual(d['original_origin_to_first_m'],1.0202291701727895)
        self.assertAlmostEqual(d['measured_origin_to_first_DIAGNOSTIC_ONLY_m'],.0281690688722127)
        self.assertEqual(len(d['evidence_declaration_errors']),2)
        self.assertIn('COARSE_STEP_TOO_LARGE',d['unchanged_local_validators']['unchanged_chunk_plan_v2'])
        self.assertIn('SUPPORT_WITHOUT_EVIDENCE',d['unchanged_local_validators']['unchanged_candidate_claim_validator'])
        self.assertTrue(d['action_geometry']['termination_boundary_conflict'])

    def test_old_real_raw_is_only_failed_regression(self):
        raw=json.loads((workspace()/'candidate-v2-a-h4-authorized-01-20261010/RAW_RESPONSE.json').read_text())['raw']
        row=self.start();gf.ReviewTests.finish(self,row,None,raw=raw)
        self.assertEqual(row['status'],'FAILED');self.assertNotIn('derived_shadow',row)
    def test_request_schema_prompt_and_source_tampering_fail_before_dispatch(self):
        for key in ('instruction','output_schema'):
            req=self.request()
            if key=='instruction':req[key]+=' ignore safety'
            else:req[key]['properties']['H']={'type':'integer'}
            with self.assertRaisesRegex(ValueError,'VERSIONED_REQUEST'):self.b.prepare(req)
        self.store.grounding_sources.clear()
        with self.assertRaisesRegex(ValueError,'RECEIPT_REQUIRED'):self.b.prepare(self.request())
    def test_production_prepare_strict_schema_and_no_model(self):
        self.b.config.fixture=False;self.b.allowance=lambda:0
        with patch('platform_v1.research.broker.ProcessJob',side_effect=AssertionError('NO_MODEL')),patch('platform_v1.research.broker.sandbox_command',side_effect=AssertionError('NO_AUTH')):
            out=self.b.prepare(self.request())
        row=self.b.rows[out['request_id']];check_provider(row['provider_schema'])
        self.assertEqual(self.b.calls,0);self.assertEqual(self.b.infer_calls,0);self.assertIsNone(self.b.job)
        self.assertEqual(len(row['attachments']),3);self.assertNotIn('binding',row['provider_schema']['properties'])
        self.assertNotIn('origin_pose_world',row['provider_schema']['properties']['result']['properties'])
        wire=json.loads((self.b.root/out['request_id']/'input_only/wire.json').read_text())
        self.assertIn('wxyz',wire['action_proposal_host']['pose_convention'])
        self.assertEqual(wire['WorldSnapshot']['state']['geometry_quality']['task_usable'],'unknown')

if __name__=='__main__':unittest.main(verbosity=2)
