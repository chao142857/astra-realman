import copy
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
import parallel180 as p
from isolated_mac_worker import load_bridge
from spatial_eval.adapter import mock_raw
from spatial_eval.mac_bridge import MacBridgeAdapter, MacBridgeConfig


class Parallel180Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def state(self):
        return dict(status='READY',max_cumulative_dispatches=24,prior_budget_consumed=4,
                    max_new_dispatches=20,jobs=p.plan(),reservations=[])

    def test_default_timeout_is_still_90_and_180_is_explicit(self):
        config=MacBridgeConfig('http://127.0.0.1:12345',self.root/'offline.token')
        with self.assertRaisesRegex(ValueError,'BOUNDED_AT_90'):
            MacBridgeAdapter(config,offline_test=True).infer({},[],self.root/'out',timeout_s=180)
        self.assertEqual(MacBridgeAdapter(config,offline_test=True,timeout_limit_s=180).timeout_limit_s,180)
        with self.assertRaises(ValueError):MacBridgeAdapter(config,timeout_limit_s=181)

    def test_four_isolated_original_handlers_concurrent_protocol_no_cli(self):
        barrier=threading.Barrier(4,timeout=5);mutex=threading.Lock();active=0;peak=0
        servers=[];threads=[];results=[];ports=[];seen=[]
        def stub(bridge,payload,stop,**options):
            nonlocal active,peak
            self.assertEqual(options['timeout_s'],180)
            bridge.validate_payload(payload)
            with mutex:active+=1;peak=max(peak,active)
            try:barrier.wait();time.sleep(.03)
            finally:
                with mutex:active-=1
            raw=mock_raw(payload['context']);run=Path('/private/tmp/codex-astra-bridge')/uuid.uuid4().hex
            events='\n'.join(json.dumps(e) for e in [dict(type='thread.started',thread_id='OFFLINE_'+uuid.uuid4().hex),
                dict(type='turn.started'),dict(type='item.completed',item=dict(type='agent_message',text=raw)),
                dict(type='turn.completed',usage=dict(input_tokens=1,output_tokens=1))])
            return dict(raw=raw,events=events,stderr='',return_code=0,error=None,
                command=bridge.command(run,[run/'input_only'/f'image-{i}.png' for i in range(3)]),local_log=str(run),latency_s=.03)
        try:
            for i in range(4):
                bridge=load_bridge(p.base.HARNESS/'scripts/codex_astra_mac_bridge.py','offline_parallel_'+str(i))
                bridge.infer=lambda payload,stop,_bridge=bridge,**opts:stub(_bridge,payload,stop,**opts)
                server=ThreadingHTTPServer(('127.0.0.1',0),bridge.Handler);server.daemon_threads=True
                server.token='offline-test-token-not-a-credential-'+str(i);server.inference_options={'timeout_s':180}
                token=self.root/f'fixture-{i}.token';token.write_text(server.token)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                servers.append(server);threads.append(thread);ports.append(server.server_port)
                job=p.plan()[i];s=p.base.load_snapshot(p.base.SUITE/job['scene_id']/'snapshot.json')
                t=next(t for t in s['task'] if t['task_id']==job['task_id'])
                context,_,images=p.base.build_input(s,t,job['condition'])
                adapter=MacBridgeAdapter(MacBridgeConfig(f'http://127.0.0.1:{server.server_port}',token),offline_test=True,timeout_limit_s=180)
                seen.append((adapter,context,images,self.root/f'out-{i}',s,t))
            with patch('subprocess.Popen',side_effect=AssertionError('NO_GENERATION_ALLOWED')),ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(a.infer,c,im,out,timeout_s=180) for a,c,im,out,_,_ in seen]
                results=[future.result() for future in futures]
            self.assertEqual(peak,4);self.assertEqual(len(set(ports)),4)
            for i,result in enumerate(results):
                self.assertIsNone(result['error']);self.assertEqual(result['model_calls'],0)
                self.assertEqual(result['source'],'FAKE_MAC_BRIDGE_NOT_ASTRA')
                self.assertEqual(p.base.read(self.root/f'out-{i}/transport.json')['timeout_s'],180)
                self.assertEqual(p.base.cli.assess_response(result,seen[i][4],seen[i][5])['parse_status'],'VALID')
        finally:
            for server in servers:server.shutdown();server.server_close()
            for thread in threads:thread.join(timeout=2)

    def test_wave_reserves_four_before_launch_and_score_zero_continues(self):
        state=self.state();barrier=threading.Barrier(4,timeout=5);called=[]
        def runner(job,seal,abort):
            self.assertEqual(len(p.base.read(self.root/'ledger.json')['reservations']),4)
            called.append(job['index']);barrier.wait()
            return dict(thread_id='mock_'+str(job['index']),score=0)
        with patch.object(p,'ROOT',self.root),patch.object(p,'report'):
            self.assertEqual(p.execute_wave(state,{},runner=runner),0)
        self.assertEqual(sorted(called),[5,6,7,8]);self.assertEqual(state['status'],'READY')
        self.assertTrue(all(r['status']=='VALID' for r in state['reservations']))

    def test_one_failure_cancels_peers_and_stops_later_waves(self):
        state=self.state();barrier=threading.Barrier(4,timeout=5);cancels=[];calls=[]
        def runner(job,seal,abort):
            calls.append(job['index']);barrier.wait()
            if job['index']==5:raise TimeoutError('OFFLINE_TIMEOUT')
            self.assertTrue(abort.wait(3));time.sleep(.03);raise RuntimeError('OFFLINE_PEER_CANCELLED')
        with patch.object(p,'ROOT',self.root),patch.object(p,'report'):
            self.assertEqual(p.execute_wave(state,{},runner=runner,canceller=lambda job:cancels.append(job['index'])),2)
            with self.assertRaisesRegex(ValueError,'BATCH_STOPPED'):
                p.execute_wave(state,{},runner=runner)
        self.assertEqual(len(calls),4);self.assertEqual(set(cancels),{6,7,8})
        self.assertEqual(state['status'],'STOPPED')

    def test_cumulative_cap_stops_at_24_and_no_repeat_added(self):
        state=self.state();state['reservations']=[dict(j,status='VALID',audit={'thread_id':'prior_'+str(j['index'])}) for j in state['jobs'][:16]]
        called=[]
        def runner(job,seal,abort):called.append(job['index']);return dict(thread_id='last_'+str(job['index']),score=1)
        with patch.object(p,'ROOT',self.root),patch.object(p,'report'):
            self.assertEqual(p.execute_wave(state,{},runner=runner),0)
            with self.assertRaises(ValueError):p.execute_wave(state,{},runner=runner)
        self.assertEqual(sorted(called),[21,22,23,24]);self.assertEqual(state['status'],'COMPLETE')
        self.assertEqual(4+len(state['reservations']),24)
        self.assertTrue(all(j['role']=='primary' for j in state['jobs']))

    def test_crash_inflight_never_relaunches(self):
        state=self.state();state['reservations']=[dict(state['jobs'][0],status='IN_FLIGHT')]
        with patch.object(p,'run_one') as run:
            with self.assertRaisesRegex(ValueError,'CRASH_OR_FAILURE'):
                p.execute_wave(state,{},runner=run)
            run.assert_not_called()

    def test_abort_before_decide_does_not_transmit(self):
        abort=threading.Event();abort.set()
        adapter=p.AbortableAdapter(MacBridgeConfig('http://127.0.0.1:12345',self.root/'token'),abort)
        with patch.object(MacBridgeAdapter,'_post') as post:
            with self.assertRaises(OSError):adapter._post('/decide',b'{}','offline-token',180)
            post.assert_not_called()


if __name__=='__main__':unittest.main()
