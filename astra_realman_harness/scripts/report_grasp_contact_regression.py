#!/usr/bin/env python3
"""Offline regression report from closed archives, never create scene/model/hardware."""
import argparse,json,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sim_skills.full_pnp.grasp_assessment import assess_grasp

def read(p):return json.loads(p.read_text())
def report(root):
    out=[]
    for path in sorted(Path(root).glob('*/result.json')):
        folder=path.parent;r=read(path);scene=folder/'scene'
        trace=[json.loads(s) for s in (scene/'private_scoring_trace.jsonl').read_text().splitlines()]
        events=[json.loads(s) for s in (scene/'grasp_execution_private.jsonl').read_text().splitlines()]
        closes=[e['data'] for e in events if e['event'] in ('CLOSING_END','CLOSING_ABORT')]
        assessment=assess_grasp(trace,read(scene/'initial_object_private.json')[2],closes[-1] if closes else None,stopped=r['stopped'])
        raw=[json.loads(s) for s in (folder/'contact_trace.jsonl').read_text().splitlines()]
        seps=[p['separation_m'] for x in raw for c in x['contacts'] if 'target_cube' in c['names'] and any('Support_Link' in n for n in c['names']) for p in c['points']]
        out.append({'case':folder.name,'label':r['label'],'status':r['status'],'z_mm':r['z_mm'],'opening':r['opening'],
            'assessment':assessment,'min_support_object_separation_mm':min(seps)*1000 if seps else None,
            'lift_requested':any(x['phase']=='lift' for x in r['actions']),'last_step':r['final_step'],
            'initialization_wall_s':r['initialization_wall_s'],'initialization_physics_s':r['initialization_physics_s'],
            'process_wall_s':r['process_wall_s'],'total_physics_s':r['final_step']*.004,
            'grasp_controller_sha256':r['source_sha256']['sim_skills/full_pnp/grasp_control.py'],
            'real_model_calls':r['real_model_calls'],'hardware_calls':r['hardware_calls']})
    return {'scope':'ENGINEERING_CONTROL_REGRESSION_NOT_ASTRA_OR_BF','cases':out,'case_count':len(out),
            'controller_hash_count':len(set(x['grasp_controller_sha256'] for x in out)),
            'real_model_calls':sum(x['real_model_calls'] for x in out),'hardware_calls':sum(x['hardware_calls'] for x in out)}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=report(a.runs)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
