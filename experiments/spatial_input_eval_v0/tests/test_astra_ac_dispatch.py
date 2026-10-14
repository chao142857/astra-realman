import copy,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
from astra_ac import runtime as r,dispatch as d
from astra_ac.offline_acceptance import controls,fixed_strategies
from pilot02_mock import mock_bridge
class ACTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='astra-ac-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.job=r.frozen()['ordered_samples'][0]
  p=patch('subprocess.Popen',side_effect=AssertionError('NO_MODEL_PROCESS'));p.start();self.addCleanup(p.stop)
  original=socket.socket.connect
  def only_fixture(sock,address):
   if address[0]!='127.0.0.1' or address[1] in (18766,18767):raise AssertionError('NO_PRODUCTION_NETWORK')
   return original(sock,address)
  p=patch('socket.socket.connect',only_fixture);p.start();self.addCleanup(p.stop)
 def batch(self):
  root=self.root/'batch';s=d.prepare(root);s.update(mode='OFFLINE_FIXTURE',status='READY');r.save(root/'ledger.json',s);return root,s
 def invoke(self,server,name,timeout=180):
  server['raw']=json.dumps(controls(self.job)['witness']);c,images,*_=r.job_input(self.job);folder=self.root/name;r.Adapter(server['config'],self.job,offline_test=True).infer(c,images,folder,timeout_s=timeout);return r.record_and_rescore(folder,self.job),folder
 def test_default_dry_run_no_permission_no_old_ledger_and_no_reset(self):
  root=self.root/'dry';s=d.prepare(root)
  with patch.object(r,'perform',side_effect=AssertionError('NO_DISPATCH')):
   self.assertEqual(d.run(root)['generation_requests'],0)
   with self.assertRaises(ValueError):d.run(root,real=True)
  self.assertEqual(d.load(root)['reserved_budget'],0)
  with self.assertRaises(FileExistsError):d.prepare(root)
  for path in (r.M/'evidence/pilot02_runs/pilot02_real_01',r.M/'evidence/astra_ac_plan_20261014'):
   with self.assertRaises(ValueError):d.load(path)
  self.assertEqual((root/'ledger.json').stat().st_mode&0o777,0o600)
 def test_grant_scope_budget_cannot_expand_or_replace(self):
  s=d.prepare(self.root/'grant');g={'generation_authorized':True,'batch_id':s['batch_id'],'output_root':s['root'],'order_sha256':s['order_sha256'],'release_sha256':s['release_sha256'],'implementation_sha256':s['implementation_sha256'],'max_dispatches':24,'deadline_s':180,'server_timeout_s':190,'concurrency':1,'user_authorization_statement':'OFFLINE TEST FIXTURE ONLY; not a real user grant'};p=self.root/'fixture.json'
  for k,v in [('max_dispatches',25),('batch_id','other'),('deadline_s',90),('server_timeout_s',180),('concurrency',8),('release_sha256','changed'),('generation_authorized',False)]:
   bad=dict(g,**{k:v});r.save(p,bad)
   with self.assertRaises(ValueError):d.authorize(copy.deepcopy(s),p)
  r.save(p,g);bound=d.authorize(s,p);r.save(p,dict(g,max_dispatches=23))
  with self.assertRaises(ValueError):d.authorize(bound,p)
 def test_production_preflight_binding_and_age(self):
  s=d.prepare(self.root/'check');config=self.root/'config.json';r.save(config,{'fixture':True});p=self.root/'preflight.json'
  receipt={'status':'PASS','batch_id':s['batch_id'],'execution_host':'ubuntu-robot','actual_hostname':'Ubuntu-Robot','order_sha256':s['order_sha256'],'release_sha256':s['release_sha256'],'implementation_sha256':s['implementation_sha256'],'bridge_config_sha256':r.sha(config),'server_timeout_s':190,'client_timeout_s':180,'single_worker':True,'non_generating_auth_and_tunnel_check':True,'model':'gpt-6-astra','reasoning':'medium','ephemeral':True,'checked_at':r.now()}
  with patch.object(socket,'gethostname',return_value='Ubuntu-Robot'):
   r.save(p,receipt);d.check_preflight(s,p,config)
   for k,v in [('server_timeout_s',180),('batch_id','old'),('checked_at','2000-01-01T00:00:00+00:00'),('non_generating_auth_and_tunnel_check',False),('model','other')]:
    r.save(p,dict(receipt,**{k:v}))
    with self.assertRaises(ValueError):d.check_preflight(s,p,config)
 def test_atomic_reservation_interruption_and_reconcile_never_resume(self):
  root,s=self.batch()
  def interrupted(job,path):
   self.assertEqual(r.read(root/'ledger.json')['reserved_budget'],1);raise KeyboardInterrupt()
  with self.assertRaises(KeyboardInterrupt):d.advance(root,s,interrupted,24)
  self.assertEqual(d.load(root)['status'],'STOPPED');d.reconcile(root);self.assertEqual(d.load(root)['reserved_budget'],1)
  with self.assertRaises(ValueError):d.advance(root,d.load(root),interrupted,24)
 def test_abrupt_process_loss_reserved_record_stops_before_runner(self):
  root,s=self.batch();s['runs']=[{'index':1,'job':s['jobs'][0],'artifact':'run-001','status':'RESERVED'}];s['reserved_budget']=1;r.save(root/'ledger.json',s)
  with self.assertRaises(ValueError):d.advance(root,d.load(root),lambda *a:self.fail('retried'),24)
  self.assertEqual(d.load(root)['status'],'STOPPED')
 def test_lock_and_ledger_tamper(self):
  with r.lock():
   with self.assertRaises(ValueError):
    with r.lock():pass
  root,s=self.batch();s['reserved_budget']=1;r.save(root/'ledger.json',s)
  with self.assertRaises(ValueError):d.load(root)
 def test_no_inference_for_context_policy_schema_or_rgb_tamper(self):
  with mock_bridge(self.root) as server:
   c,images,*_=r.job_input(self.job)
   for mutate in ('policy','schema','GT','prompt'):
    cc=copy.deepcopy(c)
    if mutate=='policy':cc.pop('task_policy')
    if mutate=='schema':cc['output_schema']={}
    if mutate=='GT':cc['ground_truth']={'witness':'PRIVATE'}
    if mutate=='prompt':cc['instruction']+='tamper'
    with self.assertRaises(ValueError):r.Adapter(server['config'],self.job,offline_test=True).infer(cc,images,self.root/mutate)
   img=self.root/'wrong.png';img.write_bytes(images[0].read_bytes()+b'x')
   with self.assertRaises(ValueError):r.Adapter(server['config'],self.job,offline_test=True).infer(c,[img,*images[1:]],self.root/'wrong')
   self.assertEqual(server['decide_calls'],0)
 def test_protocol_errors_stop_batch_single_attempt(self):
  with mock_bridge(self.root) as server:
   for i,mode in enumerate(['invalid_json','empty','no_completed','duplicate_completed','failed_event','return_error','transport_error','parameter_drift','code_mode_drift']):
    root=self.root/f'batch{i}';s=d.prepare(root);s.update(mode='OFFLINE_FIXTURE',status='READY');r.save(root/'ledger.json',s);server['mode']=mode;server['raw']=json.dumps(controls(self.job)['witness']);before=server['decide_calls']
    d.advance(root,s,lambda j,p:r.perform(j,p,server['config'],offline=True),24)
    self.assertEqual(s['status'],'STOPPED',mode);self.assertEqual(s['reserved_budget'],1);self.assertIsNone(s['runs'][0]['assessment']['score']);self.assertEqual(server['decide_calls']-before,1)
 def test_http_403_409_and_timeout_cancel(self):
  with mock_bridge(self.root) as server:
   server['config'].token_file.write_text('WRONG_OFFLINE_CREDENTIAL_123')
   result,folder=self.invoke(server,'403');self.assertIsNone(result['score']);self.assertEqual(r.read(folder/'transport.json')['http_status'],403)
   server['config'].token_file.write_text('OFFLINE_FIXTURE_NOT_A_REAL_CREDENTIAL');server['busy'].acquire()
   try:result,folder=self.invoke(server,'409')
   finally:server['busy'].release()
   self.assertEqual(r.read(folder/'transport.json')['http_status'],409);self.assertIsNone(result['score'])
   server['mode']='timeout';result,folder=self.invoke(server,'timeout',.05);self.assertIsNone(result['score']);self.assertEqual(server['cancel_calls'],1);self.assertEqual(server['decide_calls'],3)
 def test_reconnect_diagnostics_even_after_completed(self):
  with mock_bridge(self.root) as server:
   _,folder=self.invoke(server,'reconnected')
   # Alter all corresponding fixture receipts consistently, retaining valid JSON and completion.
   for name in ('response.json','bridge_result.json'):
    data=r.read(folder/name);data['stderr']='Reconnecting... 1/5';r.save(folder/name,data)
   self.assertEqual(r.assess(folder,self.job)['failure'],'NATIVE_CLI_ERROR_OR_RECONNECT')
 def test_reused_thread_is_rejected_and_valid_zero_continues(self):
  root,s=self.batch()
  with mock_bridge(self.root) as server:
   server['fixed_thread_id']='same';server['raw']=json.dumps(next(iter(controls(self.job)['negative_controls'].values())))
   d.advance(root,s,lambda j,p:r.perform(j,p,server['config'],offline=True),24)
   self.assertEqual(s['reserved_budget'],2);self.assertEqual(s['runs'][0]['assessment']['score'],0);self.assertEqual(s['runs'][1]['assessment']['failure'],'REUSED_SESSION_OR_REQUEST')
 def test_frozen_failure_stops_before_new_reservation(self):
  root,s=self.batch()
  with patch.object(r,'frozen',side_effect=ValueError('FROZEN_HASH_CHANGED')):
   with self.assertRaises(ValueError):d.advance(root,s,lambda *a:self.fail('network'),24)
  self.assertEqual(r.read(root/'ledger.json')['status'],'STOPPED');self.assertEqual(r.read(root/'ledger.json')['reserved_budget'],0)
 def test_archive_tamper_blocks_recovery(self):
  root,s=self.batch()
  with mock_bridge(self.root) as server:
   server['raw']=json.dumps(controls(self.job)['witness']);d.advance(root,s,lambda j,p:r.perform(j,p,server['config'],offline=True),1)
   # Simulate a saved VALID checkpoint with capacity left, then corrupt its raw.
   s['status']='READY';r.save(root/'ledger.json',s);(root/'run-001/raw.txt').write_text('{}')
   before=server['decide_calls']
   with self.assertRaises(ValueError):d.advance(root,d.load(root),lambda j,p:r.perform(j,p,server['config'],offline=True),24)
   self.assertEqual(server['decide_calls'],before);self.assertEqual(d.load(root)['status'],'STOPPED')
 def test_adapter_real_requires_reservation_and_exact_180(self):
  with mock_bridge(self.root) as server:
   c,images,*_=r.job_input(self.job);adapter=r.Adapter(server['config'],self.job)
   with self.assertRaises(ValueError):adapter.infer(c,images,self.root/'never',real=True)
   adapter._reserved_dispatch=True
   with self.assertRaises(ValueError):adapter.infer(c,images,self.root/'never',real=True,timeout_s=90)
   self.assertEqual(server['decide_calls'],0)
 def test_fixed_strategy_yaw01_initial_orientation(self):
  rows=fixed_strategies();row=next(x for x in rows if x['scene']=='v2_val_yaw_01');self.assertTrue(row['strategies']['public_center_initial_orientation']['score']['success'])
if __name__=='__main__':unittest.main()
