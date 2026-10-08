"""Fake CLI processes only. No network/auth/model/physics/hardware acceptance."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp.infer_process import InferConfig,isolated_preflight,sandbox_command
from sim_skills.full_pnp.slot import FullSlot
from sim_skills.full_pnp.runtime import FullRuntime
from sim_skills.full_pnp.protocol import Memory,wire_base
from sim_skills.full_pnp.wire import existing_infer_payload
from sim_skills.async_v1 import Rejected
from scripts import run_full_pnp_pair as pair
import test_full_pnp as contracts
from test_full_pnp_runtime import FakeBackend


def fake_cli(root,mode='finish'):
    prefix=Path(root)/'node22';(prefix/'bin').mkdir(parents=True);(prefix/'package').mkdir()
    config=prefix/'fixture.json';config.write_text(json.dumps({'mode':mode}))
    node=prefix/'bin/node'
    node.write_text('#!'+sys.executable+'\nimport os,sys\nif sys.argv[1:]==["--version"]:\n print("v22.23.2 FAKE");sys.exit(0)\nos.execv(sys.executable,[sys.executable]+sys.argv[1:])\n');node.chmod(0o700)
    script=prefix/'package/codex.py'
    script.write_text('''#!/usr/bin/env node
import json,os,sys,time,signal
from pathlib import Path
assert not Path('/home/alex/.codex/auth.json').exists()
assert not Path('/home/alex/astra-realman_ws').exists()
assert not Path('/code/rgb.py').exists()
assert not Path('/code/backend.py').exists()
assert set(os.environ)<=set('HOME USER LOGNAME LANG LC_ALL SSL_CERT_FILE SSL_CERT_DIR PATH TMPDIR LC_CTYPE'.split())
a=sys.argv[1:]
if a==['--version']:assert sys.stdin.read()=='';print('codex-cli FAKE');sys.exit(0)
if a==['exec','--help']:assert sys.stdin.read()=='';print('Usage: codex exec FAKE');sys.exit(0)
assert Path.cwd().name=='input_only'
assert a[a.index('--model')+1]=='gpt-6-astra'
assert 'model_reasoning_effort="medium"' in a
assert '--ignore-user-config' in a and '--ignore-rules' in a
w=json.load(sys.stdin)
assert 'SECRET' not in json.dumps(w)
mode=json.loads((Path(__file__).resolve().parents[1]/'fixture.json').read_text())['mode']
p=Path(a[a.index('--output-last-message')+1])
if mode=='api':print('fixture API failure',file=sys.stderr);sys.exit(17)
if mode in ('partial','forkchild'):
 p.write_text('{"partial":')
 if mode=='forkchild':
  signal.signal(signal.SIGTERM,signal.SIG_IGN)
  if os.fork()==0:
   heartbeat=p.parent/'heartbeat'
   while True:heartbeat.write_text(str(time.monotonic()));time.sleep(.03)
 time.sleep(60);sys.exit(0)
if mode=='missing':sys.exit(0)
if w['role']=='E':
 out={'kind':'evidence','binding':w['binding'],'selected_camera':'wrist','bbox':[.23,.31,.47,.59],
      'claims':{'object_visible':'unknown','identity':'fixture hypothesis','holding':'unknown'},
      'evidence_refs':[w['attachments'][0]['id']],'source':'FAKE_CLI_RAW_NOT_ASTRA'}
else:
 out={'kind':'candidate','binding':w['binding'],'operation':'chunk' if mode=='chunk' else 'stop' if mode=='stop' else 'finish',
      'actions':[{'type':'move_pose','pose':[.321,.012,.181,0,1,0,0]}] if mode=='chunk' else [],
      'requirements':['scene_healthy'],'evidence_refs':[w['attachments'][0]['id']],
      'parent_evidence_hash':w['evidence_packet_hash'],'verdict':'unknown','reason':'FAKE_CLI_RAW_NOT_ASTRA'}
p.write_text('{broken' if mode=='malformed' else json.dumps(out))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':20,'output_tokens':15,'output_tokens_details':{'reasoning_tokens':3},'fixture_other':7}}))
''');script.chmod(0o700);(prefix/'bin/codex').symlink_to('../package/codex.py')
    return InferConfig(str(prefix/'bin/codex'),fixture=True)


class InferTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=fake_cli(self.root)
        fixture=contracts.ContractTests();fixture.root=self.root
        fixture.cal={'pose_world_xyz_wxyz':[0,0,1,0,1,0,0],'intrinsic':[[200,0,160],[0,200,120],[0,0,1]],'resolution':[320,240]}
        self.obs=fixture.observation();self.obs['state']['gripper_master_rad']=0.
        self.events=[];self.slot=FullSlot(self.root/'slot',lambda k,d:self.events.append((k,d)),infer_config=self.config,max_attempts=20)
    def tearDown(self):self.slot.cancel();self.tmp.cleanup()
    def mode(self,value):(Path(self.config.executable).parent.parent/'fixture.json').write_text(json.dumps({'mode':value}))
    def wire(self,role='B'):
        return wire_base(self.obs,{'source_observation_id':'o1','request_id':'r1','history_cutoff':time.monotonic(),
             'preparation_started_monotonic':time.monotonic()}, {'status':'completed'},[.3,0,.12,0,1,0,0],Memory(),'B',0,role)
    def submit(self,role='B',timeout=5):
        self.slot.submit_wire(self.wire(role),self.obs,delay_s=0,timeout_s=timeout,episode_deadline=time.monotonic()+10)
    def drain(self):
        deadline=time.monotonic()+8
        while self.slot.job and time.monotonic()<deadline:self.slot.poll();time.sleep(.01)
        self.assertIsNone(self.slot.job)
    def worker(self,index=1):return json.loads((self.root/'slot'/('request-%03d'%index)/'worker.json').read_text())
    def test_preflight_same_sandbox_versions_only(self):
        r=isolated_preflight(self.config,self.root/'preflight')
        self.assertEqual(r['status'],'PASS',r)
        self.assertEqual(r['worker']['paths']['node'],str(Path(self.config.executable).with_name('node')))
        self.assertEqual(len(r['worker']['probes']),3);self.assertEqual(r['model_calls'],0)
        self.assertFalse(list((self.root/'preflight').rglob('infer_started.json')))
    def test_B_action_from_actual_raw_and_frozen_payload(self):
        self.mode('chunk');self.submit();self.drain()
        r=self.worker();self.assertEqual(self.slot.pending['candidate'],json.loads(r['raw']))
        self.assertEqual(self.slot.pending['candidate']['actions'][0]['pose'][:3],[.321,.012,.181])
        run=self.root/'slot/request-001'
        sent=existing_infer_payload(run/'input_only')
        self.assertEqual(json.loads((run/'input_payload.json').read_text()),sent)
        bridge_dir=next((run/'infer_output/bridge').iterdir())
        self.assertEqual(json.loads((bridge_dir/'prompt.json').read_text()),sent['context'])
        self.assertEqual(r['usage']['cached_input_tokens'],20);self.assertEqual(len(r['usage_events']),1)
        self.assertEqual(r['server_model'],'unknown');self.assertEqual(r['server_effort'],'unknown')
        self.assertEqual(self.slot.infer_calls,1)
        self.assertFalse((run/'worker_code/rgb.py').exists())
    def test_F_runtime_E_then_A_uses_actual_bbox_and_hash(self):
        b=FakeBackend();b.observe=lambda:copy.deepcopy(self.obs);b.finish=lambda _: {'status':'PASS','source':'FAKE_SCORE'}
        runtime=FullRuntime(b,self.root/'runtime',condition='F',budget_s=5,max_calls=20,infer_config=self.config)
        # Actual owner admission, no physical motion; finish fixture only.
        out=runtime.run()
        self.assertEqual(out['status'],'PASS',out['error']);self.assertEqual(out['all_role_attempts'],2)
        self.assertEqual(out['real_model_calls'],0);self.assertEqual(out['E_calls'],1)
        workers=self.root/'runtime/workers'
        e=json.loads((workers/'request-001/worker.json').read_text())
        a=json.loads((workers/'request-002/input_payload.json').read_text())['context']
        self.assertEqual(a['evidence_packet'],json.loads(e['raw']))
        self.assertEqual(a['evidence_packet']['selected_camera'],'wrist')
        roi=next(x for x in a['attachments'] if x['representation']=='roi')
        self.assertEqual(roi['transform']['bbox_pixels'],[73,74,150,141])
        raw_a=json.loads((workers/'request-002/worker.json').read_text())
        self.assertEqual(json.loads(raw_a['raw'])['parent_evidence_hash'],a['evidence_packet_hash'])
        self.assertEqual(out['max_in_flight'],1);self.assertEqual(b.commands,[])
    def test_raw_failure_api_failure_missing_no_fallback_or_retry(self):
        for mode in ('malformed','api','missing'):
            with self.subTest(mode=mode):
                self.mode(mode);self.submit()
                with self.assertRaisesRegex(Rejected,'NO_RETRY'):self.drain()
                self.assertIsNone(self.slot.pending)
                self.assertEqual(self.slot.attempts[self.slot.calls]['status'],'PARSE_FAILED')
                self.assertFalse((self.root/'slot'/('request-%03d'%self.slot.calls)/'parsed.json').exists())
        self.assertEqual(self.slot.calls,3);self.assertEqual(self.slot.infer_calls,3)
        self.assertIsNone(self.worker(2)['usage']);self.assertEqual(self.worker(2)['return_code'],17)
    def wait_started(self):
        deadline=time.monotonic()+3
        while not self.slot.infer_calls and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.slot.infer_calls,1)
        # Wait for fake CLI to write partial raw, not just Python entry.
        while not list((self.root/'slot/request-001/infer_output').rglob('last_message.json')) and time.monotonic()<deadline:time.sleep(.01)
    def test_cancel_preserves_partial_raw_and_reaps(self):
        self.mode('partial');self.submit();self.wait_started();proc=self.slot.job['process']
        self.slot.cancel();self.assertIsNotNone(proc.poll());self.assertIsNone(self.slot.pending)
        r=self.worker();self.assertEqual(r['raw'],'{"partial":');self.assertIn('CANCELLED',r['error'])
        self.assertEqual(self.slot.attempts[1]['status'],'CANCELLED');self.assertIsNone(r['usage'])
        with self.assertRaisesRegex(Rejected,'STOPPED'):self.submit()
    def test_cancel_kills_stubborn_CLI_and_descendant_namespace(self):
        self.mode('forkchild');self.submit();self.wait_started()
        deadline=time.monotonic()+2
        beats=[]
        while not beats and time.monotonic()<deadline:
            beats=list((self.root/'slot/request-001/infer_output').rglob('heartbeat'));time.sleep(.01)
        self.assertEqual(len(beats),1);self.slot.cancel()
        last=beats[0].read_text();time.sleep(.12);self.assertEqual(beats[0].read_text(),last)
        self.assertEqual(self.slot.attempts[1]['status'],'CANCELLED');self.assertIsNone(self.slot.pending)
    def test_timeout_and_late_result_do_not_adopt(self):
        self.mode('partial');self.submit(timeout=.5);self.drain()
        self.assertIsNone(self.slot.pending);self.assertEqual(self.slot.attempts[1]['status'],'CANCELLED')
        self.mode('finish');self.submit();self.slot.job['process'].wait(timeout=5)
        self.slot.clock=lambda:self.slot.job['deadline']+1 if self.slot.job else time.monotonic()+100
        self.slot.poll();self.assertIsNone(self.slot.pending)
        self.assertEqual(self.slot.attempts[2]['status'],'LATE_OR_CANCELLED')
    def test_failure_audit_preserves_raw_usage_and_actual_wire(self):
        from sim_skills.model import state_projection
        from scripts.audit_full_pnp_offline import audit
        self.mode('malformed');self.obs['state']=state_projection(self.obs['state'])
        b=FakeBackend();b.observe=lambda:copy.deepcopy(self.obs)
        root=self.root/'audit';root.mkdir()
        runtime=FullRuntime(b,root/'episode',condition='F',budget_s=5,max_calls=20,infer_config=self.config)
        out=runtime.run()
        (root/'result.json').write_text(json.dumps({'status':out['status'],'condition':'F','episode':out,'real_model_calls':0,'hardware_calls':0}))
        report=audit(root);row=report['requests'][0]
        self.assertTrue(report['audit_complete']);self.assertEqual(row['wire_status'],'PASS')
        self.assertEqual(row['bridge_wire_status'],'PASS');self.assertEqual(row['raw'],'{broken')
        self.assertIsNone(row['candidate']);self.assertEqual(row['usage_raw']['input_tokens'],100)
        self.assertEqual(row['parse_status'],'FAILED');self.assertIsNotNone(row['phase_duration_s']['parse'])
    def test_E_parse_failure_prevents_A_launch(self):
        self.mode('malformed');b=FakeBackend();b.observe=lambda:copy.deepcopy(self.obs)
        runtime=FullRuntime(b,self.root/'runtime',condition='F',budget_s=5,max_calls=20,infer_config=self.config)
        out=runtime.run();self.assertEqual(out['status'],'FAIL');self.assertEqual(out['all_role_attempts'],1)
        self.assertEqual(out['attempts'][0]['role'],'E');self.assertEqual(out['candidate_generated'],0)
        self.assertEqual(b.commands,[])
    def test_STOP_owner_closes_without_second_request(self):
        self.mode('stop');b=FakeBackend();b.observe=lambda:copy.deepcopy(self.obs)
        runtime=FullRuntime(b,self.root/'runtime',condition='B',budget_s=5,max_calls=20,infer_config=self.config)
        out=runtime.run();self.assertEqual(out['status'],'STOPPED');self.assertEqual(out['all_role_attempts'],1)
        self.assertEqual(b.commands,[])
    def test_attempt_cap_and_preparation_launch_failures(self):
        with patch('sim_skills.full_pnp.slot.subprocess.Popen',side_effect=OSError('FAKE_LAUNCH_FAIL')):
            with self.assertRaisesRegex(OSError,'FAKE_LAUNCH_FAIL'):self.submit()
        self.assertEqual(self.slot.calls,1);self.assertEqual(self.slot.infer_calls,0)
        self.assertEqual(self.slot.attempts[1]['status'],'FAILED')
        self.slot.calls=20
        with self.assertRaisesRegex(Rejected,'ALL_ROLE_REQUEST_CAP'):self.submit()
        self.assertEqual(self.slot.calls,20)
    def test_remaining_budget_in_actual_infer_marker(self):
        self.slot.submit_wire(self.wire(),self.obs,delay_s=0,timeout_s=30,episode_deadline=time.monotonic()+2)
        self.drain()
        started=json.loads((self.root/'slot/request-001/infer_output/infer_started.json').read_text())
        self.assertLessEqual(started['timeout_s'],2)
        self.assertLessEqual(started['started_monotonic']+started['timeout_s'],started['deadline_monotonic']+.01)
    def test_tampered_frozen_payload_fails_before_infer(self):
        self.submit();proc=self.slot.job['process'];proc.wait(timeout=5);self.slot.poll()
        # Replay ONLY fake CLI worker command after changing frozen bytes; no infer begins.
        run=self.root/'slot/request-001';p=run/'input_only/payload.json';p.chmod(0o600);p.write_text('{}')
        from scripts.codex_astra_mac_bridge import worker_environment
        cmd=json.loads((run/'command.json').read_text());env=worker_environment(self.config.executable,run)
        (run/'infer_output/infer_started.json').unlink()
        result=subprocess.run(cmd,capture_output=True,text=True,env=env,cwd=run/'input_only',timeout=5)
        self.assertIn('FROZEN_PAYLOAD_HASH',json.loads(result.stdout)['error'])
        self.assertFalse((run/'infer_output/infer_started.json').exists())


class PairEntryTests(unittest.TestCase):
    def test_no_enable_no_process_or_scene(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sys,'argv',['runner','--assets',tmp,'--output',tmp+'/out']),patch.object(pair,'pair') as launch,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:pair.main()
            self.assertEqual(exc.exception.code,2);launch.assert_not_called();self.assertFalse(Path(tmp,'out').exists())
    def test_pair_launches_exactly_B_F_with_fresh_caps(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(output=Path(tmp)/'pair',assets=Path(tmp),codex_executable='/fake/codex')
            commands=[]
            class Process:
                def __init__(self,cmd,**_):
                    commands.append(cmd);out=Path(cmd[cmd.index('--output')+1]);out.mkdir()
                    pair.save(out/'result.json',{'status':'FAIL','real_model_calls':0,'all_role_attempts':20,
                        'episode':{'status':'FAIL','error':None,'all_role_attempts':20,'attempts':[{'status':'READY'}]*20}})
                def wait(self,**_):return 1
                def poll(self):return 1
            with patch.object(pair.subprocess,'Popen',Process),patch.object(pair.signal,'signal'),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pair.pair(args),0)
            ledger=json.loads((args.output/'ledger.json').read_text())
            self.assertEqual([c[c.index('--episode')+1] for c in commands],['B','F'])
            self.assertEqual(ledger['total_attempts'],40);self.assertEqual(ledger['inherited_budget'],0)
            with self.assertRaises(FileExistsError):pair.pair(args)
    def test_pair_protocol_failure_does_not_launch_F(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(output=Path(tmp)/'pair',assets=Path(tmp),codex_executable='/fake/codex')
            class Process:
                def __init__(self,cmd,**_):
                    out=Path(cmd[cmd.index('--output')+1]);out.mkdir()
                    pair.save(out/'result.json',{'status':'FAIL','real_model_calls':0,'all_role_attempts':1,
                        'episode':{'status':'FAIL','error':'PARSE_FAILED','all_role_attempts':1,'attempts':[{'status':'PARSE_FAILED'}]}})
                def wait(self,**_):return 1
                def poll(self):return 1
            with patch.object(pair.subprocess,'Popen',side_effect=Process) as launch,patch.object(pair.signal,'signal'),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pair.pair(args),1);self.assertEqual(launch.call_count,1)
            ledger=json.loads((args.output/'ledger.json').read_text());self.assertEqual(ledger['episodes'][1]['status'],'NOT_RUN')
    def test_preflight_failure_before_backend_creation(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'asset_manifest.json').write_text('{}')
            args=SimpleNamespace(output=root/'episode',assets=root,codex_executable='/fake/codex',episode='B')
            with patch.object(pair,'isolated_preflight',return_value={'status':'FAIL','model_calls':0}),patch.object(pair.signal,'signal'),patch('sim_skills.full_pnp.backend.FullTaskBackend') as backend:
                self.assertEqual(pair.episode(args),1);backend.assert_not_called()
            result=json.loads((args.output/'result.json').read_text())
            self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['real_model_calls'],0)
            self.assertTrue((args.output/'wire_audit.json').exists())
    def test_fixed_new_budget_and_failure_classification(self):
        self.assertEqual(pair.LIMITS['total_attempt_cap'],40)
        self.assertEqual(pair.LIMITS['attempts_per_episode'],20);self.assertEqual(pair.LIMITS['episode_budget_s'],300)
        self.assertEqual(pair.LIMITS['request_timeout_s'],30)
        base={'episode':{'status':'FAIL','all_role_attempts':1,'attempts':[{'status':'READY'}],'error':None}}
        self.assertFalse(pair.classify(base,1))
        base['episode'].update(status='STOPPED',error='Rejected:STOP_NO_NEW_COMMAND');self.assertFalse(pair.classify(base,1))
        base['episode']['attempts'][0]['status']='PARSE_FAILED';self.assertTrue(pair.classify(base,1))


if __name__=='__main__':unittest.main()
