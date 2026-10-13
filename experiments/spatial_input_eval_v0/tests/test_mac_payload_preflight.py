import builtins
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from spatial_eval.adapter import HARNESS, prepare
from spatial_eval.inputs import load_snapshot, build_input

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mac_payload_preflight',ROOT/'lab/mac_payload_preflight.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class MacPayloadPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        snapshot=load_snapshot(ROOT/'evidence/lab_20261013/sim_suite_initial/lab_s5_placement/snapshot.json')
        context,_,images=build_input(snapshot,snapshot['task'][1],'RGB_MULTI_VIEW')
        prepare(context,images,self.root/'prepared',real=True)
        self.payload=self.root/'prepared/request.json';self.source=HARNESS/'scripts/codex_astra_mac_bridge.py'
    def tearDown(self):self.temp.cleanup()
    def test_full_payload_and_smoke_schema_are_checked_without_cli(self):
        with patch('subprocess.Popen',side_effect=AssertionError('NO_CLI_IN_PREFLIGHT')):
            result=probe.preflight(self.source,self.payload,self.root/'success')
        self.assertEqual(result['status'],'PASS');self.assertEqual(len(result['image_sha256']),3)
        self.assertIn('LOCAL_OUTPUT_SCHEMA_VALIDATION_SMOKE_NOT_ASTRA',result['checks'])
        self.assertEqual(result['http_requests'],0);self.assertEqual(result['model_calls'],0)
    def test_missing_jsonschema_fails_before_any_worker(self):
        original_import=builtins.__import__
        def missing(name,*args,**kwargs):
            if name=='jsonschema':raise ModuleNotFoundError("No module named 'jsonschema'")
            return original_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=missing), patch('subprocess.Popen',side_effect=AssertionError('NO_CLI')):
            result=probe.preflight(self.source,self.payload,self.root/'missing')
        self.assertEqual(result['status'],'FAIL');self.assertEqual(result['error_type'],'ModuleNotFoundError')
        self.assertEqual(result['checks'],[]);self.assertEqual(result['model_calls'],0)

if __name__=='__main__':unittest.main()
