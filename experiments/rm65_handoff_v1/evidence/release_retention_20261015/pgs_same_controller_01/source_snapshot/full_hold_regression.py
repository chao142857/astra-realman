"""Finite engineering actuator regression. No bridge, hardware or ledger use."""
import argparse
import json
import os
import traceback
from pathlib import Path
import numpy as np
from diagnose_decision4 import EPISODE, relocate_runtime_mesh_paths
from gripper_fix_regression import replay
from decision4_trace import relative, angle, pad_penetration


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--case',choices=['d4','hold','release','heldout'],required=True)
    a=p.parse_args();root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    from dual_scene import DualScene,CONFIG,CONTROLLER
    from initial_transfer import prepare_left
    from action_interface import execute_action
    relocate_runtime_mesh_paths(CONFIG)
    w=None;report={'case':a.case,'controller':CONTROLLER,'model_requests':0,
                  'nominal_preload_gains_mass_friction_safety_unchanged':True,
                  'actual_drive_and_tendon_torque':'UNKNOWN'}
    try:
        w=DualScene(a.output);w.start_video();w.observe(w.output/'table_initial')
        prepare_left(w)
        actions=[json.loads((EPISODE/f'decision_{i:03d}/proposal.json').read_text()) for i in range(4)]
        for i in range(3):
            r=replay(w,actions[i],EPISODE/'group_003/left_trajectory.npz') if i==2 else execute_action(w,actions[i])
            assert r['ok']==(i==2)
        start=w.steps;report['case_start_step']=start
        if a.case=='d4':
            report['receipt']=replay(w,actions[3],EPISODE/'group_004/left_trajectory.npz')
            if report['receipt']['ok']:w.phase_name='d4_post_hold';w.tick(500)
        elif a.case=='hold':
            w.phase_name='stationary_hold';w.tick(1474);report['receipt']={'ok':True}
        elif a.case=='release':
            value={'done':False,'execution':'sequential','actions':[{'arm':'left','kind':'gripper','pose_world_wxyz':None,'opening_fraction':1.}]}
            report['receipt']=execute_action(w,value);w.phase_name='released_observation';w.tick(500)
            report['release_checks']={'open_over_70mm':w.arms['left'].state()['actual_pad_gap_m']>.07,
                'no_left_bilateral':not w.arms['left'].bilateral_pad_contact(),
                'table_support':any('target_cube' in c['names'] and 'table' in c['names'] for c in w.contacts())}
        else:
            data=root/'evidence/gripper_drive_audit_20261015'
            target=json.loads((data/'predeclared_checks.json').read_text())['heldout']['target_world_wxyz']
            value={'done':False,'execution':'sequential','actions':[{'arm':'left','kind':'tcp','pose_world_wxyz':target,'opening_fraction':None}]}
            report['receipt']=replay(w,value,data/'original_readback_01/heldout_trajectory_FROZEN.npz')
            if report['receipt']['ok']:w.phase_name='heldout_post_hold';w.tick(500)
        report['status']='COMPLETED' if report['receipt']['ok'] else 'REJECTED'
    except Exception as exc:report.update(status='STOPPED',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            if 'case_start_step' in report:
                rows=[r for r in w.records if r['step']>=report['case_start_step']]
                p0,q0=relative(rows[0]);rp=[relative(r) for r in rows]
                report['metrics']={'observed_s':(len(rows)-1)*w.dt,
                    'max_relative_translation_mm':max(float(np.linalg.norm(p-p0))*1000 for p,_ in rp),
                    'max_relative_rotation_deg':max(angle(q0,q) for _,q in rp),
                    'max_pad_penetration_mm':max(max(pad_penetration(r).values(),default=0.) for r in rows),
                    'left_bilateral_every_step':all(r['bilateral_contact']['left'] for r in rows)}
            report['last_step']=w.steps;w.observe(w.output/'final_observation');w.close()
            (w.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
