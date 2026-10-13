#!/usr/bin/env python3
"""Validate a frozen payload in the bridge interpreter; no HTTP, auth or CLI.

This deliberately goes beyond version/help. It executes the unchanged production
schema compiler, image decoder/SHA checks and local validation of a smoke JSON.
No infer/main/command execution is reachable; subprocess.Popen is blocked.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch


def preflight(bridge_source, payload_path, output):
    output.mkdir(parents=True,exist_ok=False)
    source=bridge_source.resolve();payload_path=payload_path.resolve()
    report={'status':'FAIL','checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'python':sys.version.split()[0],'interpreter':sys.executable,
            'bridge_source':str(source),'bridge_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'payload_sha256':hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            'model_calls':0,'http_requests':0,'auth_files_read':False,'checks':[]}
    try:
        sys.path.insert(0,str(source.parent.parent))
        spec=importlib.util.spec_from_file_location('payload_preflight_bridge',source)
        bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
        payload=json.loads(payload_path.read_text())
        with patch('subprocess.Popen',side_effect=AssertionError('PREFLIGHT_FORBIDS_GENERATION')):
            schema,audit,images=bridge.validate_payload(payload)
            report['checks'].append('PROVIDER_SCHEMA_AUTHORITATIVE_BINDING')
            assert len(images)==3,'THREE_RGB_REQUIRED'
            report['checks'].append('THREE_PNG_BASE64_AND_SHA256')
            assert schema==payload['schema'],'PROVIDER_SCHEMA_MISMATCH'
            task=payload['context']['task'];assert task['kind'] in ('placement','path'),'PLANNING_SMOKE_ONLY'
            fixture={'object_id':task['constraints']['object_id'],'position_m':[0,0,0],
                     'quaternion_wxyz':task['constraints']['required_quaternion_wxyz'] or [1,0,0,0],
                     'waypoints_m':[[0,0,0]] if task['kind']=='path' else []}
            bridge.validate_local(fixture,payload['authoritative_schema'],schema)
            report['checks'].append('LOCAL_OUTPUT_SCHEMA_VALIDATION_SMOKE_NOT_ASTRA')
        report.update(status='PASS',image_sha256=[hashlib.sha256(image).hexdigest() for image in images],
                      provider_schema_sha256=audit['provider_sha256'],jsonschema_version=importlib.metadata.version('jsonschema'))
    except Exception as exc:
        report.update(error_type=type(exc).__name__,error=str(exc))
    (output/'preflight.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bridge-source',type=Path,required=True)
    parser.add_argument('--payload',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=preflight(args.bridge_source,args.payload,args.output)
    raise SystemExit(0 if result['status']=='PASS' else 1)
