"""Offline/SYNTHETIC only; no CLI model, physics or hardware dispatch."""
import copy,inspect,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research.broker import Broker
from platform_v1.research.supervisor import Supervisor
from platform_v1.research import review_contracts as rc, rgbd_world, model_context
from platform_v1.research.review_schedule import ScheduleContract,SEMANTIC_EVENTS
from scripts.structured_outputs import check_provider

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/research_public_rgb'

class PendingJob:
    def __init__(self,*args,**kw):self.proc=SimpleNamespace(pid=-1);self.result=None
    def poll(self):return self.result

class NoOwner:
    def __getattr__(self,name):raise AssertionError('SHADOW_ACCESSED_OWNER:'+name)

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.o=json.loads((FIX/'observation.json').read_text());self.o.update(episode_id='SYNTHETIC',execution_epoch=0,observation_id='SYNTHETIC:01',captured_monotonic=10.)
        self.store=PublicStore(FIX,'SYNTHETIC');self.store.observe(self.o,0);self.epoch=0
        self.e=self.store.evidence_record('SYNTHETIC','semantic_e0',{'marker':'SYNTHETIC_NOT_A_REAL_ANSWER'},'FAKE_MODEL_RAW',[self.o['observation_id']],[])
        ent={'entity_id':'object_001','geometry_instance_id':'object_001','identity_status':'hypothesis','semantic_status':'unknown','status':'coarse','kind':'object','point_world_m':[.4,0,.03],
            'bounds_world_m':[[.38,-.03,.01],[.42,.03,.05]],'uncertainty_radius_m':.020166111,'measurement_kind':'current_depth_region','surface_cloud':[[.4,0,.05]],'views':[],
            'visibility':{'fixed':'visible_support'},'current_evidence':[{'camera':'fixed','private_score':'POISON'}]}
        state={'backend':'semantic_lwh_v1','initialization':'geometry_first_v2','geometry_only':True,'observation_id':self.o['observation_id'],'captured_monotonic':10.,'robot_state':copy.deepcopy(self.o['state']),
            'entities':{'object_001':ent},'semantic_evidence_id':self.e['evidence_id'],'geometry_quality':{'numeric_valid':'pass','self_consistent':'unknown','task_usable':'unknown','grants_execution':False},'unknowns':['SYNTHETIC']}
        self.w=self.store.publish_world(state,{'observation_ids':[self.o['observation_id']],'execution_epoch':0,'evidence_ids':[self.e['evidence_id']]},'FAKE_MODEL_RAW',{'calibration/SYNTHETIC':1,'visibility/v1':1})
        self.b=Broker(self.root/'broker',self.store,SimpleNamespace(fixture=True),deadline=time.monotonic()+100,epoch=lambda:self.epoch,allowance=lambda:100,baseline_busy=lambda:False,emit=lambda *x:None)
        self.task={'id':'SYNTHETIC','revision':'1','stage':'T1_PREGRASP_APPROACH'};self.tb={'profile':'generic_semantic_v1','object_id':'object_001','goal_id':''}
    def tearDown(self):self.temp.cleanup()
    def start(self,request):
        with patch('platform_v1.research.broker.ProcessJob',PendingJob),patch('platform_v1.research.broker.sandbox_command',return_value=([],{})):
            rid=self.b.submit(request)['request_id']
        return self.b.rows[rid]
    def finish(self,row,answer,raw=None):
        record={'raw':json.dumps(answer) if raw is None else raw,'usage':None,'usage_events':[],'return_code':0,'error':None,'source':'SYNTHETIC_OFFLINE'}
        self.b.job[1].result={'bytes':json.dumps(record).encode(),'return_code':0,'cancel_reason':None};self.b.tick();return row
    def shadow(self):return rc.shadow_request(self.w,self.o,self.task,self.tb)
    def shadow_answer(self,row,decision='planned'):
        result={'version':rc.SHADOW_VERSION,'intent':'action_shadow','decision':decision,'plan':None,'reason':'SYNTHETIC CONTRACT TEST','unknowns':['clearance unknown'],'K':0,'grants_execution':False}
        if decision=='planned':
            props=row['authoritative_schema']['properties']['result']['properties']['plan']['anyOf'][0]['properties']
            plan={k:copy.deepcopy(v['const']) for k,v in props.items() if 'const' in v};start=plan['origin_pose_world']
            plan['waypoints']=[{'index':i,'type':'move_pose','pose':[start[0]+.03*i,*start[1:]],'nominal_end_offset_s':2.*i,'preconditions':copy.deepcopy(props['waypoints']['items']['properties']['preconditions']['const']),'prediction_dependencies':list(range(1,i)),'boundary_after':'none'} for i in range(1,5)]
            plan['termination']={'kind':'horizon_filled','reason':'SYNTHETIC'};result['plan']=plan
        return {'evidence_refs':[a['id'] for a in row['attachments']]+row['binding']['evidence_ids'],'result':result}
    def grounding(self):return rc.grounding_request(self.w,self.o,'SYNTHETIC task')
    def grounding_answer(self,row):
        refs=[a['id'] for a in row['attachments']]
        return {'evidence_refs':refs,'result':{'version':rc.GROUNDING_VERSION,'objects':[{'geometry_instance_id':'object_001','category':None,'attributes':[],'disposition':'unknown','semantic_status':'unknown','evidence_refs':refs}],
            'task_target_geometry_id':None,'target_status':'unknown','requests':[],'unknowns':['cannot identify SYNTHETIC candidate']}}
    def test_exact_preparation_zero_attempts_no_worker_or_auth_environment(self):
        self.b.allowance=lambda:0
        with patch('platform_v1.research.broker.ProcessJob',side_effect=AssertionError('NO_WORKER')),patch('platform_v1.research.broker.sandbox_command',side_effect=AssertionError('NO_ENV')):
            out=self.b.prepare(self.shadow())
        self.assertEqual(out['status'],'PREPARED_NOT_DISPATCHED');self.assertEqual(self.b.calls,0)
        self.assertEqual(self.b.infer_calls,0);self.assertIsNone(self.b.job);self.assertIsNone(self.b.action_ready)
        self.assertEqual(self.b.rows[out['request_id']]['provenance'],'UNGENERATED_MODEL_RESULT')

    def test_shadow_ready_never_action_ready_or_executable(self):
        row=self.start(self.shadow());answer=self.shadow_answer(row);self.finish(row,answer)
        self.assertEqual(row['status'],'READY',row['error']);self.assertIsNone(self.b.action_ready)
        self.assertFalse(self.b.poll(row['request_id'])['grants_execution']);self.assertEqual(self.b.poll(row['request_id'])['K'],0)
        self.assertFalse(self.store.get_evidence(row['evidence_id'])['grants_execution']);self.assertIsNone(row['usage_raw'])
    def test_shadow_task_usable_pass_cannot_enter_supervisor(self):
        self.store.worlds[self.w['world_id']]['state']['geometry_quality']['task_usable']='pass'
        row=self.start(self.shadow());a=self.shadow_answer(row);self.finish(row,a)
        sup=Supervisor(NoOwner(),self.store,None,self.b,self.root/'supervisor')
        for plan in (a['result'],a['result']['plan']):
            with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.load(plan,broker_request_id=row['request_id'])
        with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.from_broker(row['request_id'])
        with self.assertRaisesRegex(ValueError,'V2_REQUIRES_BROKER_RAW'):sup.load(a['result']['plan'])
        self.assertEqual(sup.plans,{});self.assertIsNone(self.b.action_ready)
    def test_shadow_refusal_and_need_evidence_accepted(self):
        for decision in ('refused','need_more_evidence'):
            row=self.start(self.shadow());self.finish(row,self.shadow_answer(row,decision));self.assertEqual(row['status'],'READY',row['error']);self.assertIsNone(self.b.action_ready)
    def test_shadow_contradictory_refusal_rejected(self):
        row=self.start(self.shadow());a=self.shadow_answer(row);a['result']['decision']='refused';self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_shadow_true_grant_or_nonzero_K_rejected(self):
        for field,val in [('grants_execution',True),('K',1)]:
            row=self.start(self.shadow());a=self.shadow_answer(row);a['result'][field]=val;self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_shadow_H_length_and_read_versions_rejected(self):
        for edit in (lambda p:p['waypoints'].pop(),lambda p:p['read_versions'].update(forged=1),lambda p:p.update(H=8),lambda p:p.update(execution_epoch=1)):
            row=self.start(self.shadow());a=self.shadow_answer(row);edit(a['result']['plan']);self.finish(row,a);self.assertEqual(row['status'],'FAILED',edit)
    def test_shadow_stage_terminal_and_illegal_terminal(self):
        row=self.start(self.shadow());a=self.shadow_answer(row);p=a['result']['plan'];p['waypoints']=p['waypoints'][:2];p['termination']={'kind':'stage_terminal','reason':'SYNTHETIC boundary'};p['waypoints'][-1]['boundary_after']='precontact_handoff';self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
        row=self.start(self.shadow());a=self.shadow_answer(row);a['result']['plan']['termination']['kind']='stage_terminal';self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_shadow_no_fake_source_stamp_or_unattached_evidence(self):
        for edit in (lambda a:a['result'].update(source={'producer':'MODEL_RAW'}),lambda a:a['evidence_refs'].append('unsent-image')):
            row=self.start(self.shadow());a=self.shadow_answer(row);edit(a);self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_shadow_stale_epoch_and_revision(self):
        row=self.start(self.shadow());self.epoch=1;self.finish(row,self.shadow_answer(row));self.assertEqual(row['status'],'FAILED');self.epoch=0
        row=self.start(self.shadow());self.store.revision+=1;self.finish(row,self.shadow_answer(row));self.assertEqual(row['status'],'FAILED')
    def test_shadow_schema_cannot_be_replaced(self):
        req=self.shadow();req['output_schema']={'type':'object','properties':{},'required':[],'additionalProperties':False}
        with self.assertRaisesRegex(ValueError,'BOUND_SCHEMA'):self.start(req)
        self.assertEqual(self.b.calls,0)
    def test_review_eligibility_does_not_change_legacy_20mm_gate(self):
        before=copy.deepcopy(self.w);r=rc.planning_review_eligibility(self.w,self.o)
        self.assertTrue(r['eligible_to_review']);self.assertFalse(r['grants_execution']);self.assertEqual(self.w,before)
        e=r['entities']['object_001'];self.assertIsNone(e['localization_confidence_radius_m']);self.assertGreater(e['legacy_surface_disagreement_radius_m'],.02)
    def test_review_nonfinite_rejected(self):
        bad=copy.deepcopy(self.w);bad['state']['entities']['object_001']['bounds_world_m'][0][0]=float('nan')
        with self.assertRaisesRegex(ValueError,'NONFINITE'):rc.planning_review_eligibility(bad,self.o)
    def test_grounding_broker_parse_and_closed_schema_no_xyz_metadata_echo(self):
        row=self.start(self.grounding());self.assertNotIn('binding',row['provider_schema']['properties']);check_provider(row['provider_schema'])
        self.finish(row,self.grounding_answer(row));self.assertEqual(row['status'],'READY',row['error']);self.assertIsNone(self.b.action_ready)
        self.assertNotIn('XYZ',json.dumps(row['provider_schema']));self.assertFalse(self.store.get_evidence(row['evidence_id'])['grants_execution'])
    def test_grounding_ids_unknown_extra_xyz_and_target_rejected(self):
        edits=[lambda r:r['objects'][0].update(geometry_instance_id='invented'),lambda r:r['objects'][0].update(XYZ=[1,2,3]),lambda r:r['objects'].append(copy.deepcopy(r['objects'][0])),lambda r:r.update(task_target_geometry_id='object_001',target_status='hypothesis')]
        for edit in edits:
            row=self.start(self.grounding());a=self.grounding_answer(row);edit(a['result']);self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_grounding_reassociation_request_refs_and_bbox(self):
        row=self.start(self.grounding());a=self.grounding_answer(row);a['result']['requests']=[{'kind':'segmentation','geometry_instance_ids':['object_001'],'camera':'fixed','bbox':[.1,.1,.4,.4],'reason':'SYNTHETIC','evidence_refs':[next(x['id'] for x in row['attachments'] if x['camera']=='fixed')]}];self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
        row=self.start(self.grounding());a=self.grounding_answer(row);a['result']['objects'][0]['evidence_refs']=['private'];self.finish(row,a);self.assertEqual(row['status'],'FAILED')
    def test_grounding_bbox_requires_its_camera_evidence(self):
        row=self.start(self.grounding());a=self.grounding_answer(row)
        a['result']['requests']=[{'kind':'segmentation','geometry_instance_ids':['object_001'],'camera':'fixed','bbox':[.1,.1,.4,.4],'reason':'SYNTHETIC','evidence_refs':[next(x['id'] for x in row['attachments'] if x['camera']=='assembly')]}]
        self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.assertIn('GROUNDING_BBOX_CAMERA_EVIDENCE',row['error'])
    def test_grounding_partial_or_semantic_input_request_forbidden(self):
        req=self.grounding();req['images'][0]['roi']=[0,0,.5,.5]
        with self.assertRaisesRegex(ValueError,'THREE_FROZEN'):self.start(req)
        req=self.grounding();req['evidence_ids']=[self.e['evidence_id']]
        with self.assertRaisesRegex(ValueError,'GEOMETRY_ONLY'):self.start(req)
    def test_review_wire_whitelist_and_three_images(self):
        self.store.observations[self.o['observation_id']]['private_truth']='POISON'
        self.store.observations[self.o['observation_id']]['state']['private_score']='POISON'
        self.store.worlds[self.w['world_id']]['state']['private_truth']='POISON'
        row=self.start(self.grounding());wire=json.loads((self.b.root/row['request_id']/'input_only/wire.json').read_text())
        self.assertEqual(len(wire['attachments']),3);self.assertEqual(wire['evidence'],[])
        self.assertNotIn('POISON',json.dumps(wire));self.assertNotIn('robot_state',wire['WorldSnapshot']['state']);self.assertIn('geometry_relations',wire['WorldSnapshot']['state'])
    def test_shadow_actual_robot_state_and_compact_context(self):
        row=self.start(self.shadow());wire=json.loads((self.b.root/row['request_id']/'input_only/wire.json').read_text())
        self.assertEqual(wire['observations'][self.o['observation_id']]['state']['actual_grasp_center_world'],self.o['state']['actual_grasp_center_world'])
        self.assertNotIn('surface_cloud',json.dumps(wire));self.assertFalse(wire['WorldSnapshot']['planning_review']['grants_execution'])
    def test_duplicate_or_nonjson_raw_rejected_no_retries(self):
        for raw in ('{"result":{},"result":{}}','not json'):
            row=self.start(self.shadow());self.finish(row,None,raw);self.assertEqual(row['status'],'FAILED');self.assertIsNone(row['usage_raw']);self.assertIsNone(self.b.action_ready)
    def test_geometry_update_not_misrepresented_as_accepted(self):
        head=WorldHead(self.root,self.store,epoch=lambda:0,deadline=time.monotonic()+10,emit=lambda *x:None)
        with self.assertRaisesRegex(ValueError,'UPDATE_CONTRACT_ONLY'):head.update(self.w['world_id'],self.o['observation_id'],0)

class ScheduleTests(unittest.TestCase):
    def ready(self):
        s=ScheduleContract();s.owner_action_completed(10);s.observed({'observation_id':'SYNTHETIC','captured_monotonic':11,'execution_epoch':1});s.updated({'world_id':'w','world_revision':2,'state':{'observation_id':'SYNTHETIC'},'binding':{'execution_epoch':1}});return s
    def run_check(self,**kw):
        args={'geometry_loss':{'position_residual_m':None},'association_uncertainty':'unknown','visibility':'partial','task_relevance':True,'chunk_finished':False,'deviation':False,'identity_clear':True,'semantic_events':dict.fromkeys(SEMANTIC_EVENTS,False)};args.update(kw);return self.ready().checked(**args)
    def test_chunk_end_requests_A_not_semantic(self):
        r=self.run_check(chunk_finished=True);self.assertEqual(r['A_intent'],'request_next_chunk');self.assertEqual(r['semantic_intent'],'none');self.assertFalse(r['dispatch'])
    def test_geometry_deviation_clear_identity_cheap_update_no_semantic(self):
        r=self.run_check(deviation=True);self.assertTrue(r['cheap_update_preferred_for_geometry_only_change']);self.assertTrue(r['L_chunk']['terminate_suffix']);self.assertEqual(r['semantic_intent'],'none')
    def test_each_semantic_event_only_if_task_relevant(self):
        for key in SEMANTIC_EVENTS:
            ev=dict.fromkeys(SEMANTIC_EVENTS,False);ev[key]=True
            r=self.run_check(semantic_events=ev,identity_clear=False);self.assertEqual(r['semantic_reasons'],[key])
            self.assertEqual(self.run_check(semantic_events=ev,identity_clear=False,task_relevance=False)['semantic_intent'],'none')
    def test_missing_or_out_of_order_update_rejected(self):
        s=ScheduleContract();s.owner_action_completed(10)
        with self.assertRaisesRegex(ValueError,'POSTCHECK'):s.owner_action_completed(11)
        with self.assertRaisesRegex(ValueError,'BEFORE_COMPLETION'):s.observed({'captured_monotonic':9})
        with self.assertRaisesRegex(ValueError,'UPDATE_ORDER'):s.updated({})
    def test_nonfinite_time_and_stale_update_rejected(self):
        s=ScheduleContract()
        with self.assertRaisesRegex(ValueError,'COMPLETION_TIME'):s.owner_action_completed(float('nan'))
        s.owner_action_completed(1)
        with self.assertRaisesRegex(ValueError,'OBSERVATION_TIME'):s.observed({'captured_monotonic':float('nan')})
        s.observed({'captured_monotonic':2,'observation_id':'o','execution_epoch':1})
        with self.assertRaisesRegex(ValueError,'REVISION'):s.updated({'world_id':'w','world_revision':0,'state':{'observation_id':'o'},'binding':{'execution_epoch':1}})
    def test_critical_identity_event_interrupts_even_without_geometric_loss(self):
        ev=dict.fromkeys(SEMANTIC_EVENTS,False);ev['critical_identity_ambiguous']=True
        r=self.run_check(semantic_events=ev,identity_clear=False,deviation=False)
        self.assertTrue(r['L_chunk']['terminate_suffix']);self.assertEqual(r['A_intent'],'wait_for_semantic_then_replan')

    def test_world_observation_epoch_binding(self):
        s=ScheduleContract();s.owner_action_completed(1);s.observed({'captured_monotonic':2,'observation_id':'o','execution_epoch':3})
        with self.assertRaisesRegex(ValueError,'BINDING'):s.updated({'state':{'observation_id':'old'},'binding':{'execution_epoch':2}})

class GeometryTests(unittest.TestCase):
    def test_geometry_build_signature_cannot_accept_semantics(self):
        self.assertEqual(list(inspect.signature(WorldHead.build_geometry_first).parameters),['self','observation_id','config'])
        self.assertNotIn('images',inspect.signature(rgbd_world.build_geometry_first).parameters)
    def test_all_depth_holes_unknown_no_models(self):
        o=json.loads((FIX/'observation.json').read_text());o['execution_epoch']=0
        cfg=json.loads((ROOT/'config/research/geometry_first_v2.json').read_text())
        depths={c:(np.zeros((480,640)),np.zeros((480,640),bool),{}) for c in ('assembly','fixed','wrist')}
        out=rgbd_world.build_geometry_first(o,depths,cfg,{'normal':[0,0,1],'offset':0})
        self.assertEqual(out['entities'],{});self.assertEqual(out['geometry_quality']['numeric_valid'],'unknown');self.assertEqual(out['resource_metrics']['Astra_calls'],0)
    def test_invalid_plane_rejected(self):
        o=json.loads((FIX/'observation.json').read_text());cfg=json.loads((ROOT/'config/research/geometry_first_v2.json').read_text())
        with self.assertRaisesRegex(ValueError,'UNIT_PLANE'):rgbd_world.build_geometry_first(o,{},cfg,{'normal':[0,0,2],'offset':0})

class ArchivedShadowTests(unittest.TestCase):
    """Opt-in real INPUT replay with explicitly fake output; never new Astra."""
    def setUp(self):
        import os
        ws=os.environ.get('GEOMETRY_FIRST_ARCHIVE_ROOT')
        if not ws: self.skipTest('set GEOMETRY_FIRST_ARCHIVE_ROOT for sealed-input contract replay')
        ws=Path(ws);self.case=ReviewTests();self.case.setUp();c=self.case
        c.o=json.loads((ws/'semantic-s1-capture-20261009/OBSERVATION.json').read_text())
        c.w=json.loads((ws/'s1-real-e0-rgbd-grounding-20261009/results/association/WORLD.json').read_text())
        c.e=json.loads(next((ws/'semantic-s1-e0-authorized-03-20261009').glob('e-*.json')).read_text())
        c.store=PublicStore(ws/'semantic-s1-capture-20261009/public',c.o['episode_id']);c.store.observe(c.o,c.o['execution_epoch'])
        c.store.evidence[c.e['evidence_id']]=c.e;c.store.worlds[c.w['world_id']]=copy.deepcopy(c.w);c.store.current_world_id=c.w['world_id'];c.store.revision=c.w['world_revision'];c.store.read_versions=c.w['read_versions'];c.epoch=c.o['execution_epoch']
        c.b=Broker(c.root/'actual_input_broker',c.store,SimpleNamespace(fixture=True),deadline=time.monotonic()+90,epoch=lambda:c.epoch,allowance=lambda:100,baseline_busy=lambda:False,emit=lambda *x:None)
        c.tb={'profile':'generic_semantic_v1','object_id':c.w['state']['task_target_id'],'goal_id':''}
        self.before=copy.deepcopy(c.w)
    def tearDown(self):
        if hasattr(self,'case'):self.case.tearDown()
    def test_real_partial_W0_review_keeps_legacy_failure_and_schema(self):
        c=self.case;r=rc.planning_review_eligibility(c.w,c.o)
        self.assertTrue(r['eligible_to_review']);self.assertGreater(r['entities']['red_left']['legacy_surface_disagreement_radius_m'],.02)
        self.assertEqual(c.w['state']['geometry_quality']['task_usable'],'unknown')
        with patch('platform_v1.research.broker.ProcessJob',side_effect=AssertionError('NO_WORKER')):
            prepared=c.b.prepare(c.shadow())
        check_provider(c.b.rows[prepared['request_id']]['provider_schema']);self.assertEqual(c.b.calls,0);self.assertEqual(c.w,self.before)
    def test_real_input_fake_shadow_plan_never_reaches_owner(self):
        c=self.case;row=c.start(c.shadow());answer=c.shadow_answer(row);c.finish(row,answer)
        self.assertEqual(row['status'],'READY',row['error']);self.assertEqual(row['provenance'],'FAKE_MODEL_RAW');self.assertIsNone(c.b.action_ready)
        sup=Supervisor(NoOwner(),c.store,None,c.b,c.root/'supervisor')
        with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.from_broker(row['request_id'])
        self.assertEqual(c.w,self.before)
    def test_real_input_rejects_wrong_world_read_set_and_unsent_images(self):
        c=self.case
        for edit in (lambda a:a['result']['plan']['read_versions'].update(forged=2),lambda a:a['evidence_refs'].append('unsent')):
            row=c.start(c.shadow());answer=c.shadow_answer(row);edit(answer);c.finish(row,answer);self.assertEqual(row['status'],'FAILED')
        self.assertEqual(c.w,self.before)

if __name__=='__main__':unittest.main(verbosity=2)
