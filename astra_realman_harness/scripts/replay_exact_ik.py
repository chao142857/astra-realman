#!/usr/bin/env python3
"""Replay recorded IK inputs only. No actuator calls, no fresh-pose substitution."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from exact_target_feasibility import solve_exact_inputs
from io_utils import ROOT, write_json
from realman_api2_readonly import SDKReadOnly

def rejected_records(root):
    for name in ('check.json','feasibility.json','group_preflight.json'):
        for path in root.rglob(name):
            try:
                data=json.loads(path.read_text())
                records=[data] if 'status' in data else list(data.values())
                for record in records:
                    if isinstance(record,dict) and record.get('status')=='REJECTED_IK':
                        yield path,record
            except (ValueError,OSError):
                continue

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--logs-root',type=Path,default=ROOT/'logs')
    p.add_argument('--record',type=Path)
    p.add_argument('--arm',choices=('left','right'))
    args=p.parse_args()
    if args.record:
        data=json.loads(args.record.read_text())
        if 'status' not in data:
            if not args.arm: p.error('--arm required for a group record')
            data=data[args.arm]
        records=[(args.record,data)]
    else:
        records=list(rejected_records(args.logs_root))
    records=[(path,r) for path,r in records if not args.arm or r.get('frame','').startswith('realman:'+args.arm+':')]
    if not records: p.error('No matching recorded REJECTED_IK; no SDK connection made')
    path,record=max(records,key=lambda item:item[0].stat().st_mtime_ns)
    arm=record['frame'].split(':')[1]
    if arm not in ('left','right'): p.error('Invalid recorded arm')
    target=record['original_target']; seed=record['seed_joint_deg']; flag=record['checker_flag']
    run=ROOT/'logs'/('ik-replay-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    run.mkdir(parents=True)
    write_json(run/'source.json',{'path':str(path.resolve()),'record':record})
    (run/'sdk').mkdir()
    with SDKReadOnly(run/'sdk') as session:
        session.connect(arm,{'left':'192.168.1.19','right':'192.168.1.18'}[arm],8080)
        snapshot=session.snapshot(arm)
        state=snapshot.get('canonical')
        if not state: raise RuntimeError('CURRENT_FRAME_READ_FAILED')
        if state['work_frame']['id']!=record['frame'] or state['tool_frame']['id']!=record['tool_frame']:
            raise RuntimeError('RECORDED_FRAME_NAME_MISMATCH')
        result=solve_exact_inputs(session,arm,seed,target,flag,all_stages=True)
        result.update(source_record=str(path), recorded_frame=record['frame'], recorded_tool_frame=record['tool_frame'],
                      current_work_frame=state['work_frame'],current_tool_frame=state['tool_frame'],
                      archived_frame_definition_comparison='UNKNOWN: historical record may contain names only',
                      delta_xyz_m=record.get('delta_xyz_m'),delta_rpy_rad=record.get('delta_rpy_rad'),
                      execution_permitted=False,hardware_commands_sent=0)
        write_json(run/'result.json',result)
    print(json.dumps({'run':str(run),'result':result},ensure_ascii=False,allow_nan=False))
    return int(result['status']=='CHECK_ERROR')

if __name__=='__main__':raise SystemExit(main())
