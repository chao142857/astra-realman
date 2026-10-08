"""Timing/cancellation only: virtual clocks, fake processes, no physics or Astra."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_full_pnp_pair as pair
from sim_skills.full_pnp.runtime import FullRuntime
from sim_skills.full_pnp.slot import FullSlot
from sim_skills.full_pnp.protocol import Memory,wire_base,Rejected
import test_full_pnp as contracts
import test_full_pnp_infer as fixtures
from test_full_pnp_runtime import FakeBackend


class Process:
    """No OS launch; records cancellation and can return a synthetic raw E."""
    pid=12345
    returncode=None
    def __init__(self,cmd,**kwargs):self.command=cmd;self.stdout=kwargs['stdout']
    def poll(self):return self.returncode
    def wait(self,**kwargs):self.returncode=-15;return self.returncode
    def complete(self,candidate):
        self.stdout.write(json.dumps({'raw':json.dumps(candidate),'error':None,'return_code':0,'usage':None}))
        self.stdout.flush();self.returncode=0


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=fixtures.fake_cli(self.root)
        fixture=contracts.ContractTests();fixture.root=self.root
        fixture.cal={'pose_world_xyz_wxyz':[0,0,1,0,1,0,0],'intrinsic':[[200,0,160],[0,200,120],[0,0,1]],'resolution':[320,240]}
        self.obs=fixture.observation();self.obs['state']['gripper_master_rad']=0.
        self.now=100.;self.slots=[];self.runtimes=[]
    def tearDown(self):
        for slot in self.slots:slot.cancel()
        for runtime in self.runtimes:runtime.stream.close()
        self.tmp.cleanup()
    def clock(self):return self.now
    def slot(self,mode='qualification',virtual=True):
        kwargs={'clock':self.clock} if virtual else {}
        s=FullSlot(self.root/('slot-%d'%len(self.slots)),lambda *_:None,infer_config=self.config,max_attempts=20,mode=mode,**kwargs)
        self.slots.append(s);return s
    def wire(self,role='B'):
        return wire_base(self.obs,{'source_observation_id':'o1','request_id':'r1','history_cutoff':1.,
            'preparation_started_monotonic':self.now},{'status':'completed'},[.3,0,.12,0,1,0,0],Memory(),'B',0,role)
    def runtime(self,condition='F'):
        b=FakeBackend();b.observe=lambda:copy.deepcopy(self.obs)
        with patch('sim_skills.full_pnp.runtime.time.monotonic',self.clock):
            r=FullRuntime(b,self.root/('runtime-%d'%len(self.runtimes)),condition=condition,mode='qualification',
                          budget_s=900,timeout_s=90,max_calls=20,infer_config=self.config)
        r.slot.clock=self.clock;self.runtimes.append(r);self.slots.append(r.slot);return r
    def test_over_30_survives_until_90_and_standard_still_cancels_at_30(self):
        for mode,cap in (('qualification',90),('standard',30)):
            with self.subTest(mode=mode),patch('sim_skills.full_pnp.slot.subprocess.Popen',Process):
                self.now=100.;s=self.slot(mode)
                s.submit_wire(self.wire(),self.obs,delay_s=0,timeout_s=90,episode_deadline=1000)
                self.assertEqual(s.job['deadline'],100+cap)
                self.now=100+cap-.001;s.poll();self.assertIsNotNone(s.job)
                if mode=='qualification':
                    self.now=142.108;s.poll();self.assertIsNotNone(s.job)
                self.now=100+cap;s.poll()
                self.assertIsNone(s.job);self.assertIsNone(s.pending)
                self.assertEqual(s.attempts[1]['status'],'CANCELLED');self.assertEqual(s.calls,1)
                self.assertIsNone(s.attempts[1]['usage_raw'])
    def test_remaining_episode_time_wins_over_request_cap(self):
        s=self.slot()
        with patch('sim_skills.full_pnp.slot.subprocess.Popen',Process):
            s.submit_wire(self.wire(),self.obs,delay_s=0,timeout_s=90,episode_deadline=135)
        self.assertEqual(s.job['deadline'],135)
        self.now=134.999;s.poll();self.assertIsNotNone(s.job)
        self.now=135;s.poll();self.assertIsNone(s.job)
        self.assertEqual(s.attempts[1]['error'],'REQUEST_TIMEOUT')
    def test_external_STOP_cancels_before_new_deadline(self):
        r=self.runtime('B')
        with patch('sim_skills.full_pnp.runtime.time.monotonic',self.clock),patch('sim_skills.full_pnp.slot.subprocess.Popen',Process):
            r.begin_cycle(self.obs);self.now=142.108;r.stop('EXTERNAL_STOP')
            with self.assertRaisesRegex(Rejected,'STOP_NO_NEW_COMMAND'):r.submit('B')
        self.assertIsNone(r.slot.job);self.assertEqual(r.slot.calls,1);self.assertEqual(r.b.commands,[])
        self.assertTrue((r.slot.root/'request-001/infer_output/CANCEL').exists())
    def test_E_then_A_share_original_deadline_and_remaining_budget(self):
        r=self.runtime();self.assertEqual(r.deadline,1000)
        with patch('sim_skills.full_pnp.runtime.time.monotonic',self.clock),patch('sim_skills.full_pnp.slot.subprocess.Popen',Process):
            self.now=950;r.begin_cycle(self.obs)
            self.assertEqual(r.slot.job['deadline'],1000)
            w=r.slot.job['snapshot'];e={'kind':'evidence','binding':w['binding'],'selected_camera':'fixed','bbox':None,
                'claims':{'object_visible':'unknown','identity':'unknown','holding':'unknown'},
                'evidence_refs':[w['attachments'][0]['id']],'source':'FAKE_RAW_TIME_TEST'}
            r.slot.job['process'].complete(e)
            self.now=992.108;r.poll()
            self.assertEqual([a['role'] for a in r.slot.attempts.values()],['E','A'])
            self.assertEqual(r.deadline,1000);self.assertEqual(r.slot.job['deadline'],1000)
            self.assertAlmostEqual(r.slot.job['deadline']-r.slot.job['started'],7.892)
            self.now=1000
            with self.assertRaisesRegex(Rejected,'EPISODE_DEADLINE'):r.admit()
            r.stop('EPISODE_DEADLINE')
        self.assertEqual(r.slot.calls,2);self.assertEqual(r.slot.attempts[2]['status'],'CANCELLED')
    def test_every_role_and_failed_launch_consume_same_20_attempts(self):
        r=self.runtime()
        r.cycle={'template':self.wire(),'obs':self.obs,'packet':None,'reuse':None,'dependencies':[]}
        with patch('sim_skills.full_pnp.runtime.time.monotonic',self.clock),patch('sim_skills.full_pnp.slot.subprocess.Popen',side_effect=OSError('FAKE_LAUNCH_FAILURE')) as launch:
            # Manual fault injections exercise accounting, not automatic retries.
            for i in range(20):
                with self.assertRaisesRegex(OSError,'FAKE_LAUNCH_FAILURE'):r.submit(('B','E','A')[i%3])
            with self.assertRaisesRegex(Rejected,'ALL_ROLE_REQUEST_CAP'):r.submit('A')
        self.assertEqual(launch.call_count,20);self.assertEqual(r.slot.calls,20);self.assertEqual(r.slot.infer_calls,0)
        self.assertEqual({a['role'] for a in r.slot.attempts.values()},{'B','E','A'})
        self.assertTrue(all(a['status']=='FAILED' and a['usage_raw'] is None for a in r.slot.attempts.values()))
    def test_worker_actual_budget_and_wire_identical_across_modes(self):
        # The verified bridge runs only an auth-free, network-disabled fake CLI.
        for role in ('B','E','A'):
            payloads=[]
            for mode,cap in (('standard',30),('qualification',90)):
                with self.subTest(role=role,mode=mode):
                    s=self.slot(mode,virtual=False)
                    s.submit_wire(self.wire(role),self.obs,delay_s=0,timeout_s=cap,episode_deadline=time.monotonic()+900)
                    s.job['process'].wait(timeout=8);s.poll();self.assertIsNotNone(s.pending)
                    run=s.root/'request-001';marker=json.loads((run/'infer_output/infer_started.json').read_text())
                    self.assertEqual(marker['mode'],mode);self.assertGreater(marker['timeout_s'],cap-5)
                    self.assertLessEqual(marker['timeout_s'],cap)
                    self.assertLessEqual(marker['started_monotonic']+marker['timeout_s'],marker['deadline_monotonic']+.00001)
                    payloads.append((run/'input_payload.json').read_bytes())
            self.assertEqual(*payloads)
    def test_completion_checkpoint_is_success_only_and_not_a_cutoff(self):
        for status,elapsed,expected in (('PASS',300,True),('PASS',300.01,False),('FAIL',10,False)):
            with self.subTest(status=status,elapsed=elapsed):
                self.now=100;r=self.runtime('B')
                def finish(_):self.now=100+elapsed;return {'status':status,'source':'FAKE_SCORE_TIME_TEST'}
                r.b.finish=finish
                with patch('sim_skills.full_pnp.runtime.time.monotonic',self.clock),patch.object(r,'begin_cycle'),patch.object(r,'wait'),patch.object(r,'adopt',return_value=({'operation':'finish','verdict':'done'},None)):
                    out=r.run()
                self.assertEqual(out['completed_within_300s'],expected)
                self.assertEqual(out['task_completed_wall_s'],elapsed if status=='PASS' else None)
                self.assertEqual(out['all_role_attempts'],0);self.assertEqual(r.b.commands,[])
    def test_runtime_standard_rejects_90_and_qualification_rejects_over_caps(self):
        for kwargs in ({'budget_s':900,'timeout_s':90}, {'mode':'qualification','budget_s':901},
                       {'mode':'qualification','timeout_s':91}):
            with self.assertRaisesRegex(ValueError,'CONFIG'):FullRuntime(FakeBackend(),self.root/'invalid',condition='B',**kwargs)


class PairTimingTests(unittest.TestCase):
    def test_qualification_requires_explicit_enable_before_any_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sys,'argv',['runner','--mode','qualification','--assets',tmp,'--output',tmp+'/out']),patch.object(pair,'pair') as launch,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):pair.main()
            launch.assert_not_called();self.assertFalse(Path(tmp,'out').exists())
    def test_pair_mode_caps_and_watchdog_propagation(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(output=Path(tmp)/'pair',assets=Path(tmp),codex_executable='/fake/codex',mode='qualification')
            commands=[];timeouts=[]
            class Owner:
                def __init__(self,cmd,**_):
                    commands.append(cmd);out=Path(cmd[cmd.index('--output')+1]);out.mkdir()
                    pair.save(out/'result.json',{'status':'PASS','real_model_calls':0,'all_role_attempts':20,
                        'completed_within_300s':False,'task_completed_wall_s':450,
                        'episode':{'status':'PASS','error':None,'all_role_attempts':20,'attempts':[{'status':'READY'}]*20}})
                def wait(self,timeout):timeouts.append(timeout);return 0
                def poll(self):return 0
            with patch.object(pair.subprocess,'Popen',Owner),patch.object(pair.signal,'signal'),patch.object(pair.time,'monotonic',return_value=100),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pair.pair(args),0)
            ledger=json.loads((args.output/'ledger.json').read_text())
            self.assertEqual([c[c.index('--episode')+1] for c in commands],['B','F'])
            self.assertTrue(all(c[c.index('--mode')+1]=='qualification' for c in commands))
            self.assertEqual(timeouts,[1260,1260]);self.assertEqual(ledger['total_attempts'],40)
            self.assertEqual(ledger['inherited_budget'],0);self.assertEqual(ledger['limits']['episode_budget_s'],900)
            self.assertEqual(ledger['limits']['request_timeout_s'],90)
            self.assertTrue(all(r['completed_within_300s'] is False for r in ledger['episodes']))
    def test_episode_passes_budget_to_runtime_from_fresh_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'asset_manifest.json').write_text('{}')
            args=SimpleNamespace(output=root/'episode',assets=root,codex_executable='/fake/codex',episode='F',mode='qualification',owner_started_monotonic=100)
            with patch.object(pair.signal,'signal'),patch.object(pair.time,'monotonic',return_value=110),patch.object(pair,'isolated_preflight',return_value={'status':'PASS'}),patch('sim_skills.full_pnp.backend.FullTaskBackend') as backend,patch('sim_skills.full_pnp.runtime.FullRuntime') as runtime:
                backend.return_value.steps=0;backend.return_value.dt=.004;backend.return_value.provenance={'empty':True}
                runtime.return_value.started=110;runtime.return_value.slot.calls=0;runtime.return_value.slot.infer_calls=0
                runtime.return_value.run.return_value={'status':'PASS','completed_within_300s':True,'task_completed_wall_s':99}
                self.assertEqual(pair.episode(args),0)
                backend.assert_called_once_with(args.assets,args.output/'scene',2,False)
                kw=runtime.call_args.kwargs
                self.assertEqual((kw['budget_s'],kw['timeout_s'],kw['max_calls'],kw['mode']),(900,90,20,'qualification'))
    def test_startup_allowance_preserves_full_episode_and_cleanup(self):
        limits=pair.limits_for('qualification')
        self.assertEqual(limits['owner_watchdog_s'],sum(limits[k] for k in ('startup_margin_s','episode_budget_s','cleanup_margin_s')))
        pair.check_startup(limits,100,400)
        with self.assertRaisesRegex(RuntimeError,'NO_EPISODE'):pair.check_startup(limits,100,400.001)
        # Legacy watchdog and absence of a new legacy startup gate are preserved.
        self.assertEqual(pair.limits_for('standard')['owner_watchdog_s'],600)
        pair.check_startup(pair.limits_for('standard'),100,401)


if __name__=='__main__':unittest.main()
