"""Independent frozen diagnostic: synthetic source files and network-free fake CLI."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import frozen_pnp_diagnostic as diag
from scripts import codex_astra_mac_bridge as bridge
from sim_skills.full_pnp.wire import existing_infer_payload,schema_for_role
from scripts.structured_outputs import encoded
from sim_skills.full_pnp.protocol import wire_base,Memory
from test_full_pnp_infer import fake_cli
import test_full_pnp as contracts


class FrozenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=fake_cli(self.root)
        fixture=contracts.ContractTests();fixture.root=self.root
        fixture.cal={'pose_world_xyz_wxyz':[0,0,1,0,1,0,0],'intrinsic':[[200,0,160],[0,200,120],[0,0,1]],'resolution':[320,240]}
        obs=fixture.observation();self.source=self.root/'old/B/episode/workers/request-001'
        inp=self.source/'input_only';inp.mkdir(parents=True);(self.source/'worker_code').mkdir()
        shutil.copyfile(bridge.__file__,self.source/'worker_code/bridge.py')
        wire=wire_base(obs,{'source_observation_id':'o1','request_id':'request-001','history_cutoff':1.},
                       {'status':'completed'},[.3,0,.12,0,1,0,0],Memory(),'B',0,'B')
        data=Path(obs['images']['fixed']).read_bytes();(inp/'image-0.png').write_bytes(data)
        wire['attachments']=[{'id':'i1','file':'image-0.png','sha256':hashlib.sha256(data).hexdigest()}]
        (inp/'wire.json').write_text(json.dumps(wire,sort_keys=True))
        diag.save(self.source/'schema.json',schema_for_role(wire))
        payload=existing_infer_payload(inp);raw=json.dumps(payload,sort_keys=True).encode()
        (self.source/'input_payload.json').write_bytes(raw);(inp/'payload.json').write_bytes(raw)
        payload=json.loads(raw) # Matches actual FullSlot serialization ordering.
        old=self.source/'infer_output/bridge/old';(old/'input_only').mkdir(parents=True)
        diag.save(old/'attachments.json',[{'index':1,'path':'/output/bridge/old/input_only/image-0.png','sha256':hashlib.sha256(data).hexdigest()}])
        (old/'input_only/image-0.png').write_bytes(data)
        for name in ('prompt.json','input_only/context.json'):(old/name).write_text(json.dumps(payload['context'],ensure_ascii=False,allow_nan=False))
        (old/'schema.json').write_bytes(encoded(payload['schema']))
        cmd=bridge.command(Path('/output/bridge/old'),[Path('/output/bridge/old/input_only/image-0.png')],diag.CLI)
        events='{"type":"turn.started"}\n';(old/'events.jsonl').write_text(events);(old/'stderr.log').write_text('fixture\n')
        diag.save(old/'environment.json',{'source':'FAKE'})
        diag.save(old/'command.json',cmd)
        diag.save(old/'result.json',{'command':cmd,'local_log':'/output/bridge/old','events':events,'stderr':'fixture\n','raw':'','error':'FIXTURE_TIMEOUT','return_code':0,'latency_s':30})
        diag.save(self.source/'attempt.json',{'request':1,'status':'CANCELLED','usage_raw':None})
        self.before=diag.inventory(self.root/'old');self.prepared=self.root/'prepared'
    def tearDown(self):
        self.assertEqual(diag.inventory(self.root/'old'),self.before)
        self.tmp.cleanup()
    def mode(self,mode):(Path(self.config.executable).parent.parent/'fixture.json').write_text(json.dumps({'mode':mode}))
    def prepare(self):return diag.prepare(self.source,self.prepared)
    def run_fake(self,**kwargs):return diag.run_once(self.prepared,authorized=True,config=self.config,**kwargs)
    def test_prepare_exact_payload_prompt_schema_and_no_launch(self):
        with patch.object(diag.subprocess,'Popen') as proc:r=self.prepare();proc.assert_not_called()
        self.assertEqual(r['status'],'SOURCE_VERIFIED_NO_REQUEST');self.assertTrue(r['owner_schema_order_only_difference'])
        self.assertEqual((self.prepared/'frozen/input_payload.json').read_bytes(),(self.source/'input_payload.json').read_bytes())
        for name in ('prompt.json','schema.json'):
            self.assertEqual((self.prepared/'frozen'/name).read_bytes(),(self.source/'infer_output/bridge/old'/name).read_bytes())
        self.assertFalse((self.prepared/'request-001').exists())
        with self.assertRaises(FileExistsError):self.prepare()
        with self.assertRaisesRegex(ValueError,'OVERLAP'):diag.prepare(self.source,self.root/'old/new')
    def test_no_authorization_no_attempt(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION'):diag.run_once(self.prepared,config=self.config)
        with patch.object(sys,'argv',['diagnostic','run','--prepared',str(self.prepared)]),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):diag.main()
        self.assertFalse((self.prepared/'request-001').exists())
    def test_raw_chunk_parsed_only_90_not_old_30(self):
        self.prepare();self.mode('chunk');r=self.run_fake()
        self.assertEqual(r['status'],'PARSED_OFFLINE_NOT_EXECUTED',r)
        self.assertEqual(r['candidate']['actions'][0]['pose'][:3],[.321,.012,.181])
        self.assertEqual(r['executed_actions'],0);self.assertEqual(r['physics_scene_calls'],0)
        self.assertTrue(r['turn_completed']);self.assertTrue(r['actual_wire_unchanged'])
        self.assertTrue(r['cli_config_unchanged_except_run_paths']);self.assertEqual(r['real_model_calls'],0)
        self.assertEqual(r['usage_raw']['input_tokens'],100);self.assertEqual(r['usage_raw']['cached_input_tokens'],20)
        self.assertEqual(r['server_model'],'unknown')
        run=self.prepared/'request-001'
        marker=json.loads((run/'infer_output/infer_started.json').read_text())
        self.assertGreater(marker['timeout_s'],30);self.assertLessEqual(marker['timeout_s'],90)
        self.assertEqual(json.loads((run/'raw.txt').read_text()),r['candidate'])
        with self.assertRaises(FileExistsError):self.run_fake()
    def test_malformed_raw_preserves_usage_no_repair_or_retry(self):
        self.prepare();self.mode('malformed');r=self.run_fake()
        self.assertEqual(r['status'],'FAILED_NO_RETRY');self.assertIsNone(r['candidate']);self.assertTrue(r['turn_completed'])
        self.assertEqual((self.prepared/'request-001/raw.txt').read_text(),'{broken')
        self.assertIsNotNone(r['usage_raw']);self.assertEqual(r['infer_entry_markers'],1)
        self.assertFalse((self.prepared/'request-001/parsed.json').exists())
    def test_API_failure_missing_usage_null(self):
        self.prepare();self.mode('api');r=self.run_fake()
        self.assertEqual(r['status'],'FAILED_NO_RETRY');self.assertIsNone(r['usage_raw']);self.assertFalse(r['turn_completed'])
        self.assertIn('fixture API failure',(self.prepared/'request-001/stderr.log').read_text())
    def test_timeout_partial_raw_cancelled_no_parse(self):
        self.prepare();self.mode('partial');r=self.run_fake(timeout_s=.3)
        self.assertEqual(r['status'],'FAILED_NO_RETRY');self.assertEqual(r['stop_reason'],'DIAGNOSTIC_TIMEOUT')
        self.assertEqual((self.prepared/'request-001/raw.txt').read_text(),'{"partial":')
        self.assertIsNone(r['usage_raw']);self.assertFalse(r['turn_completed']);self.assertIsNone(r['candidate'])
    def test_launch_failure_consumes_bundle_and_report_is_complete(self):
        self.prepare()
        with patch.object(diag.subprocess,'Popen',side_effect=OSError('FAKE_LAUNCH_FAILURE')):r=self.run_fake()
        self.assertEqual(r['status'],'FAILED_NO_RETRY');self.assertEqual(r['infer_entry_markers'],0)
        self.assertTrue((self.prepared/'request-001/result.json').exists());self.assertIsNone(r['usage_raw'])
        with self.assertRaises(FileExistsError):self.run_fake()
    def test_tamper_rejected_before_model_and_fixed_cap(self):
        self.prepare();path=self.prepared/'frozen/input_only/payload.json';path.chmod(0o600);path.write_text('{}')
        with patch.object(diag.subprocess,'Popen') as proc:r=self.run_fake();proc.assert_not_called()
        self.assertIn('PREPARED_INPUT_CHANGED',r['error']);self.assertEqual(r['infer_entry_markers'],0)
        with self.assertRaisesRegex(ValueError,'FIXED_90S'):diag.run_once(self.prepared,authorized=True,timeout_s=91)
    def test_event_warning_is_preserved_with_completion(self):
        raw='\n'.join(json.dumps(e) for e in [{'type':'item.completed','item':{'type':'error','message':'Code Mode unavailable'}},
                                             {'type':'turn.started'},{'type':'turn.completed','usage':{'input_tokens':7,'cached_input_tokens':3}}])
        r=diag.event_summary(raw);self.assertTrue(r['turn_completed']);self.assertEqual(len(r['error_items']),1)
        self.assertEqual(r['usage_raw'],{'input_tokens':7,'cached_input_tokens':3})
        self.assertFalse(diag.event_summary('{broken')['turn_completed'])


if __name__=='__main__':unittest.main()
