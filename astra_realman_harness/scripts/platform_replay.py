#!/usr/bin/env python3
"""Replay historical evidence; never create a scene, model request or action executor."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from platform_v1.client import Replay

def main():
 p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='mode',required=True)
 q=s.add_parser('prepare');q.add_argument('--run',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
 q=s.add_parser('read');q.add_argument('--bundle',type=Path,required=True)
 a=p.parse_args()
 if a.mode=='prepare':
  from platform_v1.replay import build
  r=build(a.run,a.output);print(json.dumps({k:v for k,v in r.items() if k!='image_quality'}))
 else:
  r=Replay(a.bundle);counts={}
  for e in r.events():
   counts[e['kind']]=counts.get(e['kind'],0)+1
   if e['kind']=='observation':
    for camera in ('assembly','fixed','wrist'):r.rgb(e['data'],camera)
  print(json.dumps({'version':r.index['version'],'events':counts,'physics_runs':0,'model_calls':0,'hardware_calls':0}))
if __name__=='__main__':main()
