import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from spatial_eval.adapter import HARNESS, PARAMETERS
from spatial_eval.cli import run, assess_response
from spatial_eval.inputs import load_snapshot, build_input
from spatial_eval.mac_bridge import MacBridgeAdapter, MacBridgeConfig
from spatial_eval.schema import read

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
from offline_bridge import fake_bridge

SUITE=Path(__file__).resolve().parents[1]/'evidence/lab_20261013/sim_suite_initial'
PATHS=sorted(SUITE.glob('*/snapshot.json'))


class MacBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.snapshot=load_snapshot(PATHS[0]);self.task=self.snapshot['task'][0]
        self.context,_,self.images=build_input(self.snapshot,self.task,'RGB_MULTI_VIEW')
    def tearDown(self):self.temp.cleanup()
    def invoke(self,state,name='response',timeout=2,context=None,images=None):
        # Fail hard if either the CLI or any hardware subprocess is accidentally invoked.
        with patch('subprocess.Popen',side_effect=AssertionError('NO_GENERATION_OR_HARDWARE_ALLOWED')):
            return state['adapter'].infer(context or self.context,images or self.images,self.root/name,timeout_s=timeout)
    def test_generic_protocol_freeze_schema_archive_and_secret_isolation(self):
        with fake_bridge(self.root) as state:
            result=self.invoke(state)
            self.assertIsNone(result['error']);self.assertEqual(result['source'],'FAKE_MAC_BRIDGE_NOT_ASTRA')
            self.assertEqual(result['model_calls'],0);self.assertIsNone(result['usage'])
            self.assertEqual(assess_response(result,self.snapshot,self.task)['parse_status'],'VALID')
            payload=read(self.root/'response/bridge_request.json')
            self.assertEqual(set(payload),{'request_id','context','images','schema','authoritative_schema'})
            self.assertEqual(payload['context'],self.context);self.assertEqual(len(payload['images']),3)
            self.assertEqual(payload['authoritative_schema'],self.context['output_schema'])
            from scripts.structured_outputs import compile_schema
            self.assertEqual(payload['schema'],compile_schema(self.context['output_schema'])[0])
            for i,p in enumerate(self.images):
                self.assertEqual(hashlib.sha256((self.root/f'response/input_only/image-{i}.png').read_bytes()).hexdigest(),
                                 hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(read(self.root/'response/model_parameters.json'),PARAMETERS)
            self.assertEqual(read(self.root/'response/bridge_result.json')['raw'],result['raw'])
            secret=state['token_file'].read_bytes()
            for p in (self.root/'response').rglob('*'):
                if p.is_file():self.assertNotIn(secret,p.read_bytes())
            self.assertEqual(state['decide_calls'],1);self.assertEqual(state['stub_calls'],1)
    def test_auth_failure_no_retry_or_inference(self):
        with fake_bridge(self.root) as state:
            state['token_file'].write_text('incorrect-token-at-least-16-bytes')
            result=self.invoke(state)
            self.assertEqual(result['error'],'MAC_BRIDGE_HTTP_403');self.assertEqual(state['stub_calls'],0)
            self.assertEqual(state['decide_calls'],1);self.assertEqual(state['cancel_calls'],0)
            self.assertEqual(assess_response(result,self.snapshot,self.task)['score_status'],'NOT_SCORED')
            self.assertEqual(read(self.root/'response/transport.json')['retries'],0)
    def test_image_hash_rejected_before_dispatch(self):
        with fake_bridge(self.root) as state:
            context=copy.deepcopy(self.context);context['attachments'][0]['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'FROZEN_IMAGE_HASH'):self.invoke(state,context=context)
            self.assertEqual(state['decide_calls'],0)
    def test_schema_and_hidden_geometry_fields_rejected_before_dispatch(self):
        with fake_bridge(self.root) as state:
            context=copy.deepcopy(self.context);context['output_schema']={'type':'object'}
            with self.assertRaisesRegex(ValueError,'BRIDGE_OUTPUT_SCHEMA'):self.invoke(state,context=context)
            context,_,images=build_input(self.snapshot,self.task,'RGB_ORACLE_3D')
            context['geometry']['planning_witness']={'answer':'PRIVATE'}
            with self.assertRaises(ValueError):self.invoke(state,context=context,images=images)
            self.assertEqual(state['decide_calls'],0)
    def test_busy_no_retry(self):
        with fake_bridge(self.root) as state:
            state['busy_lock'].acquire()
            try:result=self.invoke(state)
            finally:state['busy_lock'].release()
            self.assertEqual(result['error'],'MAC_BRIDGE_HTTP_409');self.assertEqual(state['stub_calls'],0)
            self.assertEqual(state['decide_calls'],1)
    def test_total_timeout_cancel_and_no_retry(self):
        with fake_bridge(self.root) as state:
            state['mode']='timeout';start=time.monotonic();result=self.invoke(state,timeout=.15)
            self.assertLess(time.monotonic()-start,1.5)
            self.assertEqual(result['error'],'MAC_BRIDGE_TIMEOUT_COMPLETION_UNKNOWN')
            self.assertEqual(state['decide_calls'],1);self.assertEqual(state['cancel_calls'],1)
            transport=read(self.root/'response/transport.json')
            self.assertEqual(transport['cancel_http_status'],200);self.assertEqual(transport['retries'],0)
            self.assertEqual(assess_response(result,self.snapshot,self.task)['score_status'],'NOT_SCORED')
    def test_trickle_cannot_extend_total_deadline(self):
        with fake_bridge(self.root) as state:
            state['mode']='trickle';start=time.monotonic();result=self.invoke(state,timeout=.2)
            self.assertLess(time.monotonic()-start,1.5)
            self.assertEqual(result['error'],'MAC_BRIDGE_TIMEOUT_COMPLETION_UNKNOWN')
            self.assertEqual(state['decide_calls'],1)
    def test_invalid_raw_is_existing_parser_failure_not_transport_failure(self):
        with fake_bridge(self.root) as state:
            state['mode']='invalid-output';result=self.invoke(state)
            assessed=assess_response(result,self.snapshot,self.task)
            self.assertEqual(assessed['parse_status'],'INVALID');self.assertEqual(assessed['score'],0.)
            self.assertEqual((self.root/'response/raw.txt').read_text(),'not JSON')
    def test_parameter_drift_blocks_scoring(self):
        with fake_bridge(self.root) as state:
            state['mode']='parameter-drift';result=self.invoke(state)
            self.assertEqual(result['error'],'MAC_BRIDGE_MODEL_PARAMETER_MISMATCH')
            self.assertEqual(assess_response(result,self.snapshot,self.task)['score_status'],'NOT_SCORED')
    def test_malformed_transport_response_retained(self):
        with fake_bridge(self.root) as state:
            state['mode']='malformed-response';result=self.invoke(state)
            self.assertTrue(result['error'].startswith('MAC_BRIDGE_PROTOCOL_OR_CONNECTION'))
            self.assertTrue((self.root/'response/http_response_body.bin').exists())
    def test_offline_fixture_and_live_transport_guards(self):
        for endpoint in ('https://127.0.0.1:9999','http://localhost:9999','http://example.com:9999',
                         'http://127.0.0.1:9999/decide','http://token@127.0.0.1:9999'):
            with self.assertRaises(ValueError):MacBridgeConfig(endpoint,self.root/'token')
        for port in (18766,18767):
            with self.assertRaises(ValueError):MacBridgeAdapter(MacBridgeConfig(f'http://127.0.0.1:{port}',self.root/'token'),offline_test=True)
        with fake_bridge(self.root) as state:
            with self.assertRaisesRegex(ValueError,'CANNOT_CLAIM_REAL'):state['adapter'].infer(self.context,self.images,self.root/'bad',real=True)
            live=MacBridgeAdapter(state['config'])
            with self.assertRaisesRegex(ValueError,'EXPLICIT_REAL'):live.infer(self.context,self.images,self.root/'bad')
            self.assertEqual(state['decide_calls'],0)
    def test_all_24_ac_inputs_existing_parser_scorer_and_pairing(self):
        with fake_bridge(self.root) as state:
            with patch('subprocess.Popen',side_effect=AssertionError('NO_GENERATION_ALLOWED')):
                rows=run(PATHS,self.root/'run',['RGB_MULTI_VIEW','RGB_ORACLE_3D'],transport_adapter=state['adapter'])
            self.assertEqual(len(rows),24);self.assertTrue(all(r['parse_status']=='VALID' for r in rows))
            self.assertTrue(all(r['source']=='FAKE_MAC_BRIDGE_NOT_ASTRA' and r['model_calls']==0 for r in rows))
            self.assertEqual(state['decide_calls'],24)
            pairs=read(self.root/'run/paired_comparison.json')
            self.assertEqual(len(pairs),12);self.assertTrue(all(p['eligible'] for p in pairs))
            for a,c in zip(state['payloads'][::2],state['payloads'][1::2]):
                cc=copy.deepcopy(c['context']);cc['geometry']=None
                self.assertEqual(a['context'],cc);self.assertEqual(a['images'],c['images'])
    def test_single_task_selection_and_real_budget_before_dispatch(self):
        with fake_bridge(self.root) as state:
            rows=run([PATHS[0]],self.root/'one',['RGB_MULTI_VIEW'],task_ids=['plan'],transport_adapter=state['adapter'])
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['task_id'],'plan')
            config=self.root/'bridge.json';config.write_text(json.dumps({'endpoint':state['config'].endpoint,'token_file':str(state['token_file'])}))
            with self.assertRaisesRegex(ValueError,'BUDGET'):
                run([PATHS[0]],self.root/'real',['RGB_MULTI_VIEW'],backend='mac-bridge',bridge_config=config,real=True,max_real_calls=1)
            self.assertEqual(state['decide_calls'],1)
            with self.assertRaisesRegex(ValueError,'UNKNOWN_TASK'):
                run([PATHS[0]],self.root/'bad',['RGB_MULTI_VIEW'],task_ids=['missing'])
    def test_connection_refused_is_archived_without_retry(self):
        import socket
        with socket.socket() as held:
            held.bind(('127.0.0.1',0));port=held.getsockname()[1]
            token=self.root/'refused.token';token.write_text('offline-dummy-token-long-enough')
            adapter=MacBridgeAdapter(MacBridgeConfig(f'http://127.0.0.1:{port}',token),offline_test=True)
            result=adapter.infer(self.context,self.images,self.root/'refused',timeout_s=.2)
        self.assertTrue(result['error'].startswith('MAC_BRIDGE_PROTOCOL_OR_CONNECTION'))
        transport=read(self.root/'refused/transport.json')
        self.assertEqual(transport['dispatch_attempts'],1);self.assertEqual(transport['retries'],0)
        self.assertEqual(transport['cancel_attempts'],0)
        self.assertEqual(assess_response(result,self.snapshot,self.task)['score_status'],'NOT_SCORED')
    def test_real_runner_stops_after_failure_without_dispatch_or_fallback(self):
        # Replace the transport method entirely: tests the scheduler, sends no HTTP.
        config=self.root/'production-paths.json'
        config.write_text(json.dumps({'endpoint':'http://127.0.0.1:18766','token_file':str(self.root/'never-read.token')}))
        failed={'raw':'','events':'','error':'OFFLINE_SCHEDULER_FIXTURE','return_code':None,
                'source':'FAKE_SCHEDULER_NOT_ASTRA','model_calls':0,'wall_latency_s':0,'usage':None}
        with patch.object(MacBridgeAdapter,'infer',return_value=failed) as transport, patch('spatial_eval.cli.infer',side_effect=AssertionError('NO_FALLBACK')):
            rows=run([PATHS[0]],self.root/'stop',['RGB_MULTI_VIEW','RGB_ORACLE_3D'],
                     real=True,max_real_calls=4,backend='mac-bridge',bridge_config=config)
        self.assertEqual(transport.call_count,1);self.assertEqual(len(rows),1)
        self.assertFalse(read(self.root/'stop/run_manifest.json')['completed'])
        self.assertEqual(rows[0]['score_status'],'NOT_SCORED')
    def test_gt_canary_not_transported(self):
        with fake_bridge(self.root) as state:
            self.snapshot['ground_truth']['PRIVATE_SCORE_CANARY']='NEVER_TRANSPORT_PRIVATE_SCORE'
            context,_,images=build_input(self.snapshot,self.task,'RGB_ORACLE_3D')
            self.invoke(state,context=context,images=images)
            wire=json.dumps(state['payloads'][0])
            for forbidden in ('NEVER_TRANSPORT_PRIVATE_SCORE','planning_witness','ground_truth','token_file'):
                self.assertNotIn(forbidden,wire)

if __name__=='__main__':unittest.main()
