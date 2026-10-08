#!/usr/bin/env python3
"""OFFLINE ONLY: existing bridge input/command and actual-raw parser; no infer call."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp.wire import existing_infer_payload,parse_bridge_record,strict_json
from scripts.codex_astra_mac_bridge import command,worker_environment,worker_paths,preflight


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-only',type=Path,required=True);p.add_argument('--bridge-record',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--preflight',action='store_true')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    report={'status':'INCOMPLETE','model_calls':0,'hardware_calls':0,'candidate':None,'usage_raw':None,'fallback':False}
    cli='/home/alex/.nvm/versions/node/v22.23.2/bin/codex'
    try:
        payload=existing_infer_payload(a.input_only)
        (a.output/'input_only').mkdir();(a.output/'runtime').mkdir()
        context=json.dumps(payload['context'],ensure_ascii=False,allow_nan=False)
        (a.output/'input_only/context.json').write_text(context);(a.output/'prompt.json').write_text(context)
        (a.output/'schema.json').write_text(json.dumps(payload['schema']))
        images=[]
        for i,blob in enumerate(payload['images']):
            path=a.output/'input_only'/('image-%d.png'%i);path.write_bytes(base64.b64decode(blob,validate=True));images.append(path.resolve())
        (a.output/'input_payload.json').write_text(json.dumps(payload,sort_keys=True))
        report['input_payload_sha256']=hashlib.sha256((a.output/'input_payload.json').read_bytes()).hexdigest()
        report['environment']=worker_paths(cli,a.output,worker_environment(cli,a.output))
        report['command_preview_not_executed']=command(a.output,images,cli)
        if a.preflight:
            report['preflight']=preflight(cli,a.output/'cli-preflight')
            if report['preflight']['status']!='PASS':raise ValueError('PREFLIGHT_FAILED')
        if a.bridge_record:
            data=a.bridge_record.read_bytes();(a.output/'actual_bridge_record.raw').write_bytes(data)
            report['bridge_record_sha256']=hashlib.sha256(data).hexdigest();record=strict_json(data)
            report['usage_raw']=record.get('usage')
            report['candidate']=parse_bridge_record(record,payload['context']);report['status']='RAW_VALIDATED_NOT_EXECUTED'
        else:report['status']='WIRE_READY_NO_RAW_NO_PROPOSAL'
    except Exception as exc:report.update(status='FAIL_NO_FALLBACK',error=type(exc).__name__+':'+str(exc))
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    return 1 if report['status']=='FAIL_NO_FALLBACK' else 0


if __name__=='__main__':raise SystemExit(main())
