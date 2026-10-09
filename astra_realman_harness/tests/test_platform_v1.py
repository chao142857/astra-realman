"""Offline platform boundary tests. No physical scene or actual model invocation."""
import io,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_v1.client import Client,Replay,VERSION,PlatformError
from platform_v1.owner import Owner
from platform_v1.replay import build

class Tests(unittest.TestCase):
 def test_private_score_not_dispatchable(self):
  o=Owner.__new__(Owner)
  with self.assertRaisesRegex(Exception,'PRIVATE_OR_UNSUPPORTED_METHOD'):o.dispatch({'version':VERSION,'id':1,'method':'score_private','params':{}})
 def test_version_and_method_fields_fail_closed(self):
  o=Owner.__new__(Owner)
  for r in ({'version':'old'},{'version':VERSION,'id':1,'method':'observe','params':{'GT':1}}):
   with self.assertRaises(Exception):o.dispatch(r)
 def test_reset_requires_new_owner_process(self):
  o=Owner.__new__(Owner);o.reset_done=True
  with self.assertRaisesRegex(Exception,'FRESH_OWNER'):o.dispatch({'version':VERSION,'id':1,'method':'reset','params':{}})
 def test_source_cannot_survive_execution_epoch(self):
  o=Owner.__new__(Owner);o.admit=lambda:None;o.epoch=2;o.observations={'o':{'epoch':1}}
  with self.assertRaisesRegex(Exception,'STALE'):o.source_obs('o')
 def test_stop_arrival_in_hook_prevents_next_step(self):
  o=Owner.__new__(Owner);o.b=SimpleNamespace(stopped=False)
  o.inbox_poll=lambda:setattr(o.b,'stopped',True)
  with self.assertRaisesRegex(Exception,'STOPPED'):o.hook('before_step')
 def test_fake_candidate_cannot_be_changed_or_reused(self):
  o=Owner.__new__(Owner);o.admit=lambda:None;o.chunks=0;o.source_obs=lambda _:{}
  o.proposal={'digest':'t','candidate':{'operation':'chunk','actions':[{'type':'hold','seconds':.04}],'binding':{'source_observation_id':'o'}}}
  with self.assertRaisesRegex(Exception,'RAW_ACTION'):o.execute([{'type':'hold','seconds':.1}],'o','t')
  self.assertIsNone(o.proposal)
  with self.assertRaisesRegex(Exception,'UNKNOWN_OR_CONSUMED'):o.execute([{'type':'hold','seconds':.04}],'o','t')
 def test_chunk_cap_allows_observe_but_no_13th_action(self):
  o=Owner.__new__(Owner);o.admit=lambda:None;o.chunks=12
  with self.assertRaisesRegex(Exception,'CHUNK_CAP'):o.execute([{'type':'hold','seconds':.04}],'o')
  o.observe=Mock(return_value={'fresh':True})
  self.assertEqual(o.dispatch({'version':VERSION,'id':1,'method':'observe','params':{}}),{'fresh':True})
 def test_client_binds_reply_and_does_not_invoke_executor(self):
  read=io.StringIO(json.dumps({'version':VERSION,'id':1,'ok':True,'result':{'x':1}})+'\n');write=io.StringIO()
  self.assertEqual(Client(read,write).observe(),{'x':1});self.assertEqual(json.loads(write.getvalue())['method'],'observe')
  with self.assertRaises(PlatformError):Client(io.StringIO(''),io.StringIO()).observe()
 def test_replay_never_executes_or_scores(self):
  r=Replay.__new__(Replay)
  with self.assertRaisesRegex(PlatformError,'EXECUTION_FORBIDDEN'):r.execute([{'type':'gripper','opening':1}])
  with self.assertRaisesRegex(PlatformError,'PRIVATE_SCORE'):r.score_private()
 def test_engineering_targets_redacted_real_submitted_actions_preserved(self):
  o=Owner.__new__(Owner);o.source='ENGINEERING_REFERENCE';a=[{'type':'move_pose','pose':[.36,-.06,.04,0,1,0,0]}]
  self.assertNotIn('pose',o.public_actions(a)[0]);o.source='RESEARCH_PROGRAM';self.assertEqual(o.public_actions(a),a)
 def test_finish_ack_has_no_score_and_unknown_allowed(self):
  o=Owner.__new__(Owner);r=o.dispatch({'version':VERSION,'id':1,'method':'finish','params':{'verdict':'unknown'}})
  self.assertEqual(r,{'closed':True,'score':'PRIVATE_NOT_RETURNED'});self.assertTrue(o.ended)


class BoundaryRegressionTests(unittest.TestCase):
 def owner(self):
  o=Owner.__new__(Owner);o.admit=lambda:None;o.chunks=0;o.epoch=0;o.source='RESEARCH_PROGRAM';o.proposal=None
  raw={'observation_id':'o','state':{'actual_grasp_center_world':[.3,0,.1],'flange_pose_world':[.3,0,.3,0,1,0,0],'sim_step':5}}
  o.source_obs=lambda _:raw;o.observe=lambda:{'observation_id':'o'};o.observations={'o':{'raw':raw}}
  o.b=SimpleNamespace(s=SimpleNamespace(state=lambda:dict(raw['state'],contact_truth='PRIVATE_SENTINEL')),steps=5,
                      stop=Mock(),execute_chunk=Mock())
  o.slot=SimpleNamespace(cancel=Mock());o.private_event=Mock();o.emit=Mock();return o
 def test_partial_result_preserves_completed_prefix_and_remainder(self):
  o=self.owner();chunk=[{'type':'hold','seconds':.04},{'type':'gripper','opening':.45}]
  o.b.execute_chunk.return_value={'ok':False,'results':[{'action':chunk[0],'result':{'ok':True}}],
                                'unexecuted_count':1,'error':'PRE_GRIPPER_UNKNOWN'}
  with patch('platform_v1.owner.rgb.features',return_value={}),patch('platform_v1.owner.dependencies.check',return_value={'status':'valid'}):
   r=o.execute(chunk,'o')
  self.assertEqual(r['unexecuted_actions'],[chunk[1]]);self.assertTrue(r['actions'][0]['completed'])
  self.assertEqual(r['error_code'],'PRE_GRIPPER_UNKNOWN');self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r))
  o.b.stop.assert_called_once();o.slot.cancel.assert_called_once();self.assertEqual(o.epoch,1)
 def test_unexpected_backend_exception_does_not_claim_nothing_executed(self):
  o=self.owner();o.b.execute_chunk.side_effect=RuntimeError('exception after motion')
  with patch('platform_v1.owner.rgb.features',return_value={}),patch('platform_v1.owner.dependencies.check',return_value={'status':'valid'}):
   r=o.execute([{'type':'hold','seconds':.04}],'o')
  self.assertIsNone(r['unexecuted_count']);self.assertIsNone(r['unexecuted_actions'])
  self.assertEqual(r['execution_outcome'],'UNKNOWN_AFTER_BACKEND_EXCEPTION');self.assertEqual(r['actual_state']['sim_step'],5)
 def test_owner_minimum_check_cannot_be_omitted(self):
  o=self.owner()
  with patch('platform_v1.owner.rgb.features',return_value={}),patch('platform_v1.owner.dependencies.check',return_value={'status':'unknown'}):
   with self.assertRaisesRegex(Exception,'OWNER_RGB_UNKNOWN'):o.execute([{'type':'hold','seconds':.04}],'o')
  o.b.execute_chunk.assert_not_called()
 def test_model_observe_and_finish_consumed_once_through_gate(self):
  for op in ('observe','finish'):
   o=self.owner();o.gate=SimpleNamespace(validate=Mock());o.binding=lambda _:{}
   o.proposal={'digest':'t','candidate':{'operation':op,'binding':{'source_observation_id':'o'},'requirements':['scene_healthy'],'verdict':'unknown'},'snapshot':{'attachments':[{'id':'i'}]}}
   with patch('platform_v1.owner.rgb.features',return_value={}),patch('platform_v1.owner.dependencies.check',return_value={'status':'valid'}):
    r=o.commit('t')
   o.gate.validate.assert_called_once();self.assertIsNone(o.proposal)
   self.assertEqual(r,{'observation_id':'o'} if op=='observe' else {'closed':True,'score':'PRIVATE_NOT_RETURNED'})
   with self.assertRaisesRegex(Exception,'CONSUMED'):o.commit('t')
 def test_archived_rgb_projection_hash_integrity_and_partial_failure(self):
  import hashlib
  from PIL import Image
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);run=root/'run';(run/'episode').mkdir(parents=True);(run/'scene/obs_0001').mkdir(parents=True)
   cal={n:{'pose_world_xyz_wxyz':[0,0,0,1,0,0,0],'intrinsic':[[1,0,0],[0,1,0],[0,0,1]],'resolution':[2,2]} for n in ('assembly','fixed','wrist')}
   for n in cal:Image.new('RGB',(2,2)).save(run/'scene/obs_0001'/(n+'.png'))
   obs={'observation_id':'o1','captured_monotonic':1.,'capture_span_s':.01,'state':{'sim_step':1,'GT':'PRIVATE_SENTINEL'},'calibration':cal,
        'images':{n:'/missing-original/scene/obs_0001/'+n+'.png' for n in cal},'score':'PRIVATE_SENTINEL'}
   rows=[{'kind':'OBSERVATION','data':obs,'wall_monotonic':1.,'physics_step':1},
         {'kind':'CHUNK_END','wall_monotonic':2.,'physics_step':2,'data':{'result':{'ok':False,'results':[], 'unexecuted_count':2,'error':'GRASP_CONTACT_LOST_AFTER_LATCH'}}}]
   (run/'episode/timeline.jsonl').write_text('\n'.join(map(json.dumps,rows)))
   build(run,root/'public');r=Replay(root/'public');o=r.observe();r.rgb(o,'fixed')
   self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r.rows));self.assertEqual(r.rows[-1]['data']['unexecuted_count'],2)
   self.assertEqual(r.rows[-1]['data']['error_code'],'GRASP_CONTACT_LOST_AFTER_LATCH')
   (root/'public/o-0000/fixed.png').write_bytes(b'changed')
   with self.assertRaisesRegex(PlatformError,'REPLAY_HASH'):Replay(root/'public')
 def test_preflight_failure_before_scene_has_durable_report(self):
  from scripts import run_research_platform as runner
  import contextlib
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'asset_manifest.json').write_text('{}')
   a=SimpleNamespace(budget_s=120,fake_cli=root/'fake/bin/codex',enable_real_model=False,model_max_requests=0,
       output=root/'out',source='RESEARCH_PROGRAM',seed=2,assets=root,program=root/'program.py')
   with patch('sim_skills.full_pnp.infer_process.isolated_preflight',return_value={'status':'FAIL'}),patch('platform_v1.owner.Owner') as owner,patch.object(runner.signal,'signal'),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
    self.assertEqual(runner.run(a),1)
   owner.assert_not_called();r=json.loads((a.output/'result.json').read_text())
   self.assertEqual(r['status'],'FAILED');self.assertEqual(r['real_model_calls'],0);self.assertIn('BEFORE_SCENE',r['error'])
 def test_runner_preserves_malformed_partial_stream_and_cleanup_failure(self):
  """Real local child process, entirely fake scene owner; no GPU/model/SDK."""
  import contextlib,time
  from scripts import run_research_platform as runner
  for mode in ('malformed','partial','finish_cleanup_failure'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
    root=Path(d);(root/'asset_manifest.json').write_text('{}');program=root/'program.py'
    request={'version':VERSION,'id':1,'method':'finish','params':{'verdict':'unknown'}}
    data='BROKEN\n' if mode=='malformed' else '{"partial":' if mode=='partial' else json.dumps(request)+'\n'
    program.write_text('import sys\nsys.stdout.write('+repr(data)+');sys.stdout.flush()\n'+('sys.stdin.readline()\n' if mode.startswith('finish') else ''))
    class FakeOwner:
     def __init__(self,assets,path,**kw):
      self.private=path/'private';self.public=path/'public';self.private.mkdir();self.public.mkdir()
      (self.public/'events.jsonl').touch();self.b=SimpleNamespace(stopped=False,steps=0,dt=.004)
      self.b.stop=lambda:setattr(self.b,'stopped',True)
      self.started=time.monotonic();self.initial_step=0;self.init_wall=0.;self.chunks=0;self.observations={};self.ended=False
      self.slot=SimpleNamespace(attempts={},calls=0,infer_calls=0)
     def private_event(self,k,d):
      with (self.private/'fake_owner_events.jsonl').open('a') as f:f.write(json.dumps({'kind':k,'data':d})+'\n')
     def emit(self,*args):pass
     def idle(self):time.sleep(.001)
     def dispatch(self,r):self.ended=True;return {'closed':True}
     def score_private(self):return {'status':'FAIL'}
     def close(self):
      if mode.startswith('finish'):raise RuntimeError('FIXTURE_CLEANUP_FAILURE')
    a=SimpleNamespace(budget_s=120,fake_cli=None,enable_real_model=False,model_max_requests=0,
       output=root/'out',source='RESEARCH_PROGRAM',seed=2,assets=root,program=program)
    with patch('platform_v1.owner.Owner',FakeOwner),patch.object(runner,'sandbox',return_value=([sys.executable,str(program)],{})),patch.object(runner.signal,'signal'),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
     runner.run(a)
    r=json.loads((a.output/'result.json').read_text());self.assertEqual((a.output/'private/research_stdout.bin').read_text(),data)
    self.assertEqual(r['real_model_calls'],0);self.assertEqual(r['private_score_status'],'FAIL')
    if mode.startswith('finish'):self.assertIn('FIXTURE_CLEANUP_FAILURE',r['cleanup_error'])
    else:self.assertEqual(r['status'],'FAILED')

if __name__=='__main__':unittest.main(verbosity=2)
