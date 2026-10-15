"""One predeclared engineering witness per condition; never an Astra input."""
import argparse
import json
import os
import traceback
from pathlib import Path
from .contract import ROOT, CONDITIONS, SPEC, prepare_initial, assess
from action_interface import execute_action


def main():
    p=argparse.ArgumentParser();p.add_argument('--condition',choices=CONDITIONS,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();os.environ['RM65_LAYOUT']=str(ROOT/SPEC['layout'])
    from dual_scene import DualScene, CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    relocate_runtime_mesh_paths(CONFIG)
    report={'source':'PRIVATE_ENGINEERING_NOT_ASTRA','real_model_requests':0,'condition_id':a.condition,'status':'INITIALIZING','actions':[]}
    w=None
    try:
        w=DualScene(a.output);w.start_video();w.observe(w.output/'ready_observation')
        prepare_initial(w,a.condition);p=w.campaign_policy;report['task_start_step']=w.task_start_step
        first,second=p['visit_order']
        def move(side,pose):
            proposal={'done':False,'execution':'sequential','actions':[{'arm':side,'kind':'tcp','pose_world_wxyz':pose,'opening_fraction':None}]}
            receipt=execute_action(w,proposal);report['actions'].append({'proposal':proposal,'receipt':receipt});return receipt
        before=w.steps
        rejected=move(first,p[first+'_goal_world_wxyz'])
        report['negative_control_PRIVATE']={'receipt':rejected,'physics_steps':w.steps-before}
        if rejected['ok'] or rejected['executed'] or w.steps!=before or 'COLLISION' not in json.dumps(rejected):
            raise RuntimeError('SHARED_WORKSPACE_COUPLING_NOT_VERIFIED')
        for side,pose in [(second,p['initial_ready_world_wxyz'][second]),(first,p[first+'_goal_world_wxyz']),
                          (first,p['initial_ready_world_wxyz'][first]),(second,p[second+'_goal_world_wxyz'])]:
            if not move(side,pose)['ok']:raise RuntimeError('PREDECLARED_WITNESS_REJECTED')
        w.phase_name='engineering_final_hold_2s';w.tick(500)
        report['score']=assess([r for r in w.records if r['step']>=w.task_start_step],w.dt,p)
        report['status']='PHYSICAL_WITNESS_PASS' if report['score']['pass'] else 'PHYSICAL_WITNESS_FAIL'
    except Exception as exc:report.update(status='FAILED',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            w.observe(w.output/'final_observation');w.close()
            (w.output/'witness_PRIVATE.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'condition':a.condition,'status':report['status'],'error':report.get('error'),'real_requests':0}))
    if report['status']!='PHYSICAL_WITNESS_PASS':raise SystemExit(1)


if __name__=='__main__':main()
