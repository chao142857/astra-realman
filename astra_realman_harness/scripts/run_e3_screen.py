#!/usr/bin/env python3
"""E3 only. prepare/verify/report/archive are offline; infer requires explicit opt-in."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from e3_history_screen import prepare, validate_batch, infer, report, archive

def main():
    p=argparse.ArgumentParser(description=__doc__)
    s=p.add_subparsers(dest='mode',required=True)
    a=s.add_parser('prepare');a.add_argument('--source',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    for name in ('verify','infer','report','archive'):
        a=s.add_parser(name);a.add_argument('--batch',type=Path,required=True)
        if name=='infer':a.add_argument('--authorize-32-real-requests',action='store_true')
    a=p.parse_args()
    if a.mode=='prepare':r=prepare(a.source,a.output);print(json.dumps({'prepared':len(r['requests']),'model_calls':0,'hardware_commands_sent':0}))
    elif a.mode=='verify':r=validate_batch(a.batch);print(json.dumps({'verified':len(r['requests']),'model_calls':0,'hardware_commands_sent':0}))
    elif a.mode=='infer':infer(a.batch,authorize_32=a.authorize_32_real_requests)
    elif a.mode=='report':print(json.dumps(report(a.batch),ensure_ascii=False))
    else:print(json.dumps(archive(a.batch),ensure_ascii=False))

if __name__=='__main__':main()
