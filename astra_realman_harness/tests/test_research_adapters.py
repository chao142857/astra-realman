"""No Astra, SDK or SAPIEN: real isolated OS fixtures plus public geometry workers."""
import copy,hashlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_v1.research.contracts import plan_schema,semantic_schema,micro_chunks,validate_plan
from platform_v1.research.native_subagent import NativeCodexSubagentBackend
from platform_v1.research.task_evidence import TaskEvidenceAdapter
from sim_skills.full_pnp.infer_process import InferConfig,isolated_preflight
from scripts.prepare_research_fake_cli import prepare
from research_fixtures import owner,wait_job,initial_world,plan,step

class ResearchTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(os.environ.get('RESEARCH_TEST_EVIDENCE',cls.tmp.name));cls.base.mkdir(parents=True,exist_ok=True)
  cls.launcher=prepare(cls.base/'fake_cli');cls.config=InferConfig(str(cls.launcher),fixture=True)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def setUp(self):
  self.root=self.base/self._testMethodName;self.root.mkdir();self.mode('normal')
  self.o=owner(self.root/'owner',self.config);self.a=self.o.research;self.obs=self.o.observe()
 def tearDown(self):self.o.close()
 def mode(self,mode,delay=0):
  p=self.launcher.parent.parent/'fixture.json';r=json.loads(p.read_text());r.update(mode=mode,delay_ms=delay);p.write_text(json.dumps(r))
 def request(self,role='semantic_e0',world=None,camera='fixed',roi=None,evidence=None,timeout=5):
  return {'backend':'existing_codex_infer','role':role,'instruction':'OFFLINE FIXTURE ONLY; bbox in selected attachment normalized coordinates.',
   'images':[{'observation_id':self.obs['observation_id'],'camera':camera,'roi':roi}],
   'evidence_ids':evidence or [],'world_id':world['world_id'] if world else None,
   'output_schema':plan_schema() if role=='action' else semantic_schema(),'timeout_s':timeout}
 def submit_wait(self,request):
  r=self.a.broker.submit(request);return wait_job(self.a.broker,r['request_id'])
 def test_preflight_existing_node_env_no_model(self):
  r=isolated_preflight(self.config,self.root/'preflight');self.assertEqual(r['status'],'PASS',r)
  self.assertEqual(r['model_calls'],0);self.assertIn('v22.23.2',r['worker']['probes'][0]['stdout'])
 def test_roles_have_actual_distinct_images_schema_and_raw_provenance(self):
  e=self.submit_wait(self.request(roi=[.1,.2,.8,.9]));self.assertEqual(e['status'],'READY',e)
  self.obs,w=initial_world(self.o)
  a=self.submit_wait(self.request('action',w,'wrist',evidence=[e['evidence_id']]))
  l=self.submit_wait(self.request('local_reground',w,'assembly'))
  self.assertEqual([a['status'],l['status']],['READY','READY']);self.assertEqual(self.o.b.commands,[])
  contexts=[]
  for row in (e,a,l):
   folder=self.a.broker.root/row['request_id'];payload=json.loads((folder/'input_payload.json').read_text());contexts.append(payload)
   actual=json.loads((folder/'worker.json').read_text());self.assertEqual(row['parsed'],json.loads(actual['raw']))
   received=next(json.loads(s) for s in actual['events'].splitlines() if json.loads(s)['type']=='fixture.received')
   self.assertEqual(received['images'],[i['sha256'] for i in payload['context']['attachments']]);self.assertFalse(received['native_subagent'])
   image=payload['context']['attachments'][0];original=payload['context']['observations'][image['observation_id']]['calibration'][image['camera']]['intrinsic']
   crop=image['transform']['crop_xyxy_pixels'];self.assertEqual(image['selected_intrinsic'][0][2],original[0][2]-(crop[0] if crop else 0))
   self.assertEqual(row['usage_raw']['output_tokens_details'],{'reasoning_tokens':2})
  self.assertEqual(len({p['context']['attachments'][0]['sha256'] for p in contexts}),3)
  self.assertNotEqual(contexts[0]['schema'],contexts[1]['schema']);self.assertEqual(contexts[1]['context']['WorldSnapshot']['version'],'astra.world.public.v1')
 def test_unknown_ids_bad_roi_schema_fail_without_launch(self):
  cases=[]
  r=self.request();r['images'][0]['observation_id']='private:object';cases.append(r)
  r=self.request();r['images'][0]['roi']=[.8,0,.2,1];cases.append(r)
  r=self.request();r['output_schema']={'$ref':'https://invalid/schema'};cases.append(r)
  for r in cases:
   with self.assertRaises(Exception):self.a.broker.submit(r)
  self.assertEqual(self.a.broker.calls,3);self.assertEqual(self.a.broker.infer_calls,0)
  self.assertTrue(all(r['status']=='FAILED' and r['usage_raw'] is None for r in self.a.broker.rows.values()))
 def test_parse_and_api_failure_no_execution_retry_or_stub(self):
  for mode in ('malformed','api'):
   self.mode(mode);r=self.submit_wait(self.request());self.assertEqual(r['status'],'FAILED');self.assertIsNone(r['parsed'])
  self.assertEqual(self.a.broker.calls,2);self.assertEqual(self.o.b.commands,[])
  self.assertEqual(self.a.broker.rows['broker-001']['raw'],'{broken')
  self.assertIsNone(self.a.broker.rows['broker-002']['usage_raw'])
 def test_submit_is_actual_process_and_overlaps_approved_execution(self):
  self.mode('normal',600);r=self.a.broker.submit(self.request());proc=self.a.broker.job[1].proc
  self.assertIsNone(proc.poll());self.assertNotEqual(proc.pid,os.getpid())
  self.o.execute([{'type':'hold','seconds':.2}],self.obs['observation_id'])
  out=wait_job(self.a.broker,r['request_id']);self.assertEqual(out['status'],'FAILED')
  self.assertIn('STALE_EXECUTION_EPOCH',self.a.broker.rows[r['request_id']]['error'])
  trace=self.o.b.commands[0];stages=self.a.broker.rows[r['request_id']]['stages']
  start=next(s['monotonic'] for s in stages if s['stage']=='STARTED');end=next(s['monotonic'] for s in stages if s['stage']=='RETURNED')
  overlap=max(0,min(end,trace['end'])-max(start,trace['start']));self.assertGreater(overlap,.05)
  (self.root/'overlap.json').write_text(json.dumps({'source':'FAKE_CLI_AND_FAKE_EXECUTION_NOT_NATIVE_SUBAGENTS','overlap_s':overlap,'pid':proc.pid},indent=2))
 def test_single_model_slot_and_shared_baseline_budget(self):
  self.mode('normal',400);r=self.a.broker.submit(self.request())
  with self.assertRaisesRegex(Exception,'ONE_MODEL'):self.a.broker.submit(self.request())
  with self.assertRaisesRegex(Exception,'ONE_MODEL'):self.o.infer(self.obs['observation_id'])
  wait_job(self.a.broker,r['request_id']);self.o.max_requests=2;self.o.slot.calls=1
  with self.assertRaisesRegex(Exception,'SHARED_MODEL'):self.a.broker.submit(self.request())
 def test_cancel_retains_partial_raw_null_usage(self):
  self.mode('partial');r=self.a.broker.submit(self.request());folder=self.a.broker.root/r['request_id']
  end=time.monotonic()+3
  while not list((folder/'infer_output').rglob('last_message.json')) and time.monotonic()<end:time.sleep(.01)
  self.a.broker.cancel(r['request_id']);out=wait_job(self.a.broker,r['request_id'])
  self.assertEqual(out['status'],'CANCELLED');self.assertEqual(self.a.broker.rows[r['request_id']]['raw'],'{"partial":');self.assertIsNone(out['usage_raw'])
 def test_timeout_and_stop_cancel_without_second_request(self):
  self.mode('partial');r=self.a.broker.submit(self.request(timeout=.3));out=wait_job(self.a.broker,r['request_id'])
  self.assertEqual(out['status'],'CANCELLED');self.assertEqual(self.a.broker.calls,1)
  r=self.a.broker.submit(self.request());self.o.stop();out=wait_job(self.a.broker,r['request_id']);self.assertEqual(out['status'],'CANCELLED')
 def test_native_subagent_explicitly_unverified_never_coroutine_acceptance(self):
  self.assertEqual(NativeCodexSubagentBackend.capabilities()['status'],'UNVERIFIED_DISABLED')
  r=self.request();r['backend']='native_codex_subagent'
  with self.assertRaisesRegex(Exception,'NOT_ACCEPTED'):self.a.broker.submit(r)
  self.assertEqual(self.a.broker.calls,0)
 def test_world_process_source_timestamps_version_and_no_private_inputs(self):
  self.obs,w=initial_world(self.o);row=self.a.world.rows['world-001']
  self.assertEqual(w['version'],'astra.world.public.v1');self.assertEqual(w['binding']['execution_epoch'],0)
  self.assertEqual(w['binding']['capture_times'],[self.obs['captured_monotonic']]);self.assertFalse(w['state']['task_identity_verified'])
  raw=(self.a.world.root/'world-001/input_only/world_input.json').read_text()
  for field in ('score_private','object_pose','bilateral_contact','expert_grasp'):self.assertNotIn('"'+field+'"',raw)
  self.assertNotEqual(row['pid'],os.getpid());self.assertTrue(all(e['uncertainty_radius_m']>=.02 for e in w['state']['entities'].values() if e['status']=='coarse'))
 def test_roi_bbox_is_bound_to_actual_attachment_not_other_view(self):
  e=self.submit_wait(self.request(roi=[.1,.2,.8,.9]));r=self.a.world.submit([self.obs['observation_id']],[e['evidence_id']],'bbox_rays_v1')
  out=wait_job(self.a.world,r['request_id']);self.assertEqual(out['status'],'READY')
  wire=json.loads((self.a.world.root/r['request_id']/'input_only/world_input.json').read_text())
  self.assertEqual(wire['regions'][0]['camera'],'fixed');self.assertAlmostEqual(wire['regions'][0]['bbox'][0],.275)
  self.assertEqual(out['result']['state']['entities']['fixture-object']['status'],'unknown') # one view
 def test_h8_eight_m1_submissions_with_fresh_epochs(self):
  self.obs,w=initial_world(self.o);p=self.a.supervisor.load(plan(self.obs,w))
  for _ in range(8):p=step(self.o,p)
  self.assertEqual(p['status'],'COMPLETED');self.assertEqual((p['H'],p['K_adopted'],p['K_completed']),(8,8,8))
  self.assertEqual([len(c['actions']) for c in self.o.b.commands],[1]*8)
  self.assertEqual([t['origin']['execution_epoch'] for t in p['trace']],list(range(8)))
  self.assertEqual(len({t['origin']['source_observation_id'] for t in p['trace']}),8)
  self.assertEqual(step(self.o,p)['status'],'COMPLETED');self.assertEqual(len(self.o.b.commands),8)
 def test_model_raw_plan_not_autocommitted_and_cannot_be_modified(self):
  self.obs,w=initial_world(self.o);row=self.submit_wait(self.request('action',w));self.assertEqual(self.o.b.commands,[])
  changed=copy.deepcopy(row['parsed']['result']);changed['waypoints'][0]['seconds']=.04
  with self.assertRaisesRegex(Exception,'RAW_PLAN'):self.a.supervisor.load(changed,broker_request_id=row['request_id'])
  p=self.a.supervisor.from_broker(row['request_id']);self.assertEqual(self.a.supervisor.plans[p['plan_id']]['source'],'FAKE_MODEL_RAW')
  self.assertEqual(self.o.b.commands,[])
 def test_epoch_or_world_revision_change_discards_remaining(self):
  self.obs,w=initial_world(self.o);p=self.a.supervisor.load(plan(self.obs,w));p=step(self.o,p);self.assertEqual(p['K_completed'],1)
  self.o.epoch+=1;p=step(self.o,p);self.assertEqual(p['reason'],'EXECUTION_EPOCH_CHANGED');self.assertEqual(len(self.o.b.commands),1)
 def test_revision_change_in_motion_stops_and_preserves_unknown(self):
  self.obs,w=initial_world(self.o);p=self.a.supervisor.load(plan(self.obs,w));p=self.a.supervisor.step(p['plan_id'])
  wait_job(self.a.world,self.a.supervisor.plans[p['plan_id']]['world_job'])
  def change():self.a.store.revision+=1;self.o.b.s.inject=None
  self.o.b.s.inject=change;p=self.a.supervisor.step(p['plan_id'])
  self.assertEqual(p['status'],'DISCARDED');self.assertTrue(self.o.b.stopped);self.assertEqual(len(self.o.b.commands),1)
  self.assertIsNone(p['K_adopted']);self.assertEqual(p['trace'][0]['feedback']['execution_outcome'],'UNKNOWN_AFTER_BACKEND_EXCEPTION')
 def test_gripper_barrier_discards_future_even_if_geometry_unchanged(self):
  self.obs,w=initial_world(self.o);actions=[{'type':'hold','seconds':.02},{'type':'gripper','opening':1.},{'type':'hold','seconds':.02},{'type':'hold','seconds':.02}]
  pplan=plan(self.obs,w,actions,H=4);pplan['task_binding']={'profile':'legacy_red_green_v1','object_id':'red_task_object','goal_id':'green_goal'}
  p=self.a.supervisor.load(pplan)
  # Only task admission is patched to isolate barrier routing. Actual gripper physics is NOT tested here.
  with patch.object(TaskEvidenceAdapter,'check',return_value={'status':'valid'}):
   p=step(self.o,p);p=step(self.o,p)
  self.assertEqual(p['reason'],'GRIPPER_BARRIER_REQUIRES_NEW_EVIDENCE_AND_PLAN');self.assertEqual(p['K_adopted'],2)
  self.assertEqual([len(x) for x in micro_chunks(actions)],[1,1,1,1]);self.assertEqual(len(self.o.b.commands),2)
 def test_partial_failure_preserves_completed_prefix_and_remainder(self):
  self.obs,w=initial_world(self.o);p=self.a.supervisor.load(plan(self.obs,w));p=step(self.o,p)
  self.o.b.failure='first';p=step(self.o,p)
  self.assertEqual(p['status'],'DISCARDED');self.assertEqual((p['K_submitted'],p['K_adopted'],p['K_completed']),(2,2,1))
  self.assertEqual(p['trace'][1]['feedback']['unexecuted_count'],0);self.assertEqual(len(self.o.b.commands),2)
 def test_generic_identity_cannot_be_declared_verified_by_model(self):
  self.obs,w=initial_world(self.o);pplan=plan(self.obs,w);pplan['task_binding']={'profile':'generic_semantic_v1','object_id':'mug42','goal_id':'shelf2'}
  p=self.a.supervisor.load(pplan);p=step(self.o,p);self.assertEqual(p['reason'],'TASK_EVIDENCE_UNKNOWN');self.assertEqual(self.o.b.commands,[])
 def test_fixture_evidence_cannot_enter_real_provider(self):
  e=self.submit_wait(self.request());self.a.broker.config=InferConfig(str(self.launcher),fixture=False)
  with self.assertRaisesRegex(Exception,'FIXTURE_CANNOT_ENTER_REAL_MODEL'):self.a.broker.submit(self.request(evidence=[e['evidence_id']]))
  self.assertEqual(self.a.broker.infer_calls,1)
 def test_supported_horizons_and_mismatched_lengths(self):
  self.obs,w=initial_world(self.o)
  for h in (1,4,6,8):
   candidate=plan(self.obs,w,H=h);validate_plan(candidate)
   self.assertEqual(sum(map(len,micro_chunks(candidate['waypoints']))),h)
  p=plan(self.obs,w);p['H']=6
  with self.assertRaises(Exception):validate_plan(p)
 def test_epoch_change_inside_micro_chunk_invalidates_and_stops(self):
  self.obs,w=initial_world(self.o);p=self.a.supervisor.load(plan(self.obs,w));p=self.a.supervisor.step(p['plan_id'])
  wait_job(self.a.world,self.a.supervisor.plans[p['plan_id']]['world_job'])
  def change():self.o.epoch+=1;self.o.b.s.inject=None
  self.o.b.s.inject=change;p=self.a.supervisor.step(p['plan_id'])
  self.assertEqual(p['reason'],'EXECUTION_EPOCH_CHANGED');self.assertTrue(self.o.b.stopped);self.assertEqual(len(self.o.b.commands),1)
 def test_world_cancel_stale_epoch_and_expired_budget(self):
  r=self.a.world.submit([self.obs['observation_id']],[],'legacy_rgb_rays_v1')
  self.a.world.cancel(r['request_id']);out=wait_job(self.a.world,r['request_id']);self.assertEqual(out['status'],'CANCELLED')
  r=self.a.world.submit([self.obs['observation_id']],[],'legacy_rgb_rays_v1');self.o.epoch+=1
  out=wait_job(self.a.world,r['request_id']);self.assertEqual(out['status'],'FAILED');self.assertIn('EPOCH',out['error'])
  self.obs=self.o.observe();self.a.world.deadline=time.monotonic()-1
  with self.assertRaisesRegex(Exception,'NO_REMAINING'):self.a.world.submit([self.obs['observation_id']],[],'legacy_rgb_rays_v1')
 def test_historical_bbox_does_not_become_current_object_state(self):
  old=self.obs['observation_id'];e=self.submit_wait(self.request());self.obs=self.o.observe()
  r=self.a.world.submit([old,self.obs['observation_id']],[e['evidence_id']],'bbox_rays_v1')
  out=wait_job(self.a.world,r['request_id']);self.assertEqual(out['status'],'READY')
  entity=out['result']['state']['entities']['fixture-object'];self.assertEqual(entity['status'],'unknown');self.assertEqual(entity['sources'],[])
 def test_cancelled_supervisor_never_executes_or_reclassifies_completed(self):
  self.obs,w=initial_world(self.o);p=self.a.supervisor.load(plan(self.obs,w));self.a.supervisor.cancel(p['plan_id'])
  out=step(self.o,p);self.assertEqual(out['status'],'DISCARDED');self.assertEqual(self.o.b.commands,[])
 def test_late_finished_model_result_is_not_ready(self):
  r=self.a.broker.submit(self.request());job=self.a.broker.job[1];job.proc.wait(timeout=5)
  job.deadline=time.monotonic()-1
  out=self.a.broker.poll(r['request_id']);self.assertEqual(out['status'],'CANCELLED');self.assertIsNone(out['parsed']);self.assertIsNotNone(out['usage_raw'])

 def test_bbox_clipped_by_selected_roi_remains_unknown(self):
  self.mode('clipped');req=self.request(roi=[.1,.2,.8,.9]);req['images'].append({'observation_id':self.obs['observation_id'],'camera':'assembly','roi':[.1,.2,.8,.9]})
  e=self.submit_wait(req);r=self.a.world.submit([self.obs['observation_id']],[e['evidence_id']],'bbox_rays_v1')
  out=wait_job(self.a.world,r['request_id']);self.assertEqual(out['status'],'READY')
  entity=out['result']['state']['entities']['fixture-object'];self.assertEqual(entity['status'],'unknown');self.assertEqual(entity['sources'],[])

class RpcMultiplexTests(unittest.TestCase):
 def test_out_of_order_replies_preserve_execution_result_binding(self):
  import io
  from platform_v1.client import Client,VERSION,PlatformError
  rows=[{'version':VERSION,'id':2,'ok':True,'result':{'status':'READY'}},{'version':VERSION,'id':1,'ok':True,'result':{'ok':True}}]
  client=Client(io.StringIO('\n'.join(map(json.dumps,rows))+'\n'),io.StringIO())
  first=client.begin('execute',chunk=[{'type':'hold','seconds':.02}],source_observation_id='o',proposal_id=None)
  second=client.begin('broker_poll',request_id='r')
  self.assertEqual(client.wait(first),{'ok':True});self.assertEqual(client.wait(second),{'status':'READY'})
  with self.assertRaisesRegex(PlatformError,'UNKNOWN_PENDING'):client.wait(first)
 def test_already_queued_proposals_drain_during_motion_without_nested_execute(self):
  from scripts.run_research_platform import motion_requests
  pending=[{'method':'execute','id':1},{'method':'broker_submit','id':2},{'method':'observe','id':3},{'method':'broker_poll','id':4},{'method':'commit','id':5}]
  self.assertEqual([r['id'] for r in motion_requests(pending)],[2,4]);self.assertEqual([r['id'] for r in pending],[1,3,5])
 def test_current_observation_projection_drops_private_state_poison(self):
  with tempfile.TemporaryDirectory() as d:
   o=owner(Path(d)/'owner')
   try:
    o.b.state.update(object_pose='PRIVATE_SENTINEL',contact_truth='PRIVATE_SENTINEL',score='PRIVATE_SENTINEL')
    obs=o.observe();self.assertNotIn('PRIVATE_SENTINEL',json.dumps(o.research.store.get(obs['observation_id'])))
   finally:o.close()

if __name__=='__main__':unittest.main(verbosity=2)
