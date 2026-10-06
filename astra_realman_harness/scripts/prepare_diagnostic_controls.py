#!/usr/bin/env python3
"""Prepare independent human-verified controls or 3+1 history; infer only with explicit --infer."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import read_json
from offline_diagnostic_controls import prepare_controls, annotation_template
from scripts.prepare_history_replay import decision_observation
from history_diagnostics import PROFILES

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--step',type=int,required=True)
    p.add_argument('--output',type=Path);p.add_argument('--base-profile',choices=PROFILES,default='H5D1')
    p.add_argument('--annotation',type=Path);p.add_argument('--annotation-template',action='store_true')
    p.add_argument('--visual-history-mode',choices=['none','previous_fixed_before'],default='none')
    p.add_argument('--fixed-camera',choices=['tabletop','overhead'],default='tabletop')
    p.add_argument('--infer',action='store_true',help='Explicit real model calls, never hardware or rollout')
    a=p.parse_args()
    if a.step<1:p.error('positive step required')
    if a.annotation_template:
        print(json.dumps(annotation_template(decision_observation(a.run/('step-%02d'%a.step))),ensure_ascii=False,indent=2));return
    if not a.output:p.error('--output required')
    print(json.dumps(prepare_controls(a.run,a.step,a.output,base_profile=a.base_profile,annotation=read_json(a.annotation) if a.annotation else None,
        visual_history_mode=a.visual_history_mode,fixed_camera=a.fixed_camera,infer=a.infer),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
