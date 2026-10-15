"""Finite return-value fix regressions; no model, new IK, or controller tuning."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback
import numpy as np
from diagnose_decision4 import ROOT, EPISODE, HISTORY, relocate_runtime_mesh_paths
from decision4_trace import read_rows, compare_start, relative, angle, pad_penetration
from gripper_drive_audit import drives, save


def replay(world, action, path):
    """Use exact saved six-arm-joint arrays; fingers stay in their actual state."""
    from action_interface import execute_action
    arm = world.arms['left']; original = arm.plan_tcp
    with np.load(path) as z:
        plan = {k: z[k].copy() for k in z.files}
    assert np.array_equal(plan['target_tcp'], action['actions'][0]['pose_world_wxyz'])
    err = float(np.max(abs(arm.robot.get_qpos()[arm.arm_indices]-plan['start_full'][arm.arm_indices])))
    assert err < 1e-4, 'SAVED_ARM_START_DIFFERS_NO_CORRECTION'
    def frozen(pose):
        assert np.array_equal(pose, plan['target_tcp'])
        return {k: np.array(v, copy=True) for k, v in plan.items()}
    arm.plan_tcp = frozen
    try:
        return execute_action(world, action)
    finally:
        arm.plan_tcp = original


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', choices=['d4', 'hold', 'release', 'heldout'], required=True)
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    output = a.output.resolve()
    assert output.is_relative_to(ROOT/'evidence/gripper_drive_audit_20261015') and not output.exists()
    ledger_sha = hashlib.sha256((HISTORY/'ledger.json').read_bytes()).hexdigest()
    assert ledger_sha == '2304f4eb011e40a870c91c4420d22ce75d94346cdda6ec3ae799a825f50db8c1'
    os.environ['RM65_LAYOUT'] = str(ROOT/'scene_v4_ready_transfer_1100.json')
    assert os.environ.get('RM65_CONTROLLER', 'original') == 'original'
    assert os.environ.get('RM65_SOLVER', 'original') == 'original'
    from dual_scene import DualScene, CONFIG
    from initial_transfer import prepare_left
    from action_interface import execute_action
    from evaluate_transfer import assess
    report = {'case': a.case, 'status': 'INITIALIZING', 'new_model_requests': 0,
              'change': 'Arm.latch_grasp_contact returns parent result; no parameter change.',
              'code_commit': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
              'mesh_path_relocation': relocate_runtime_mesh_paths(CONFIG),
              'actual_drive_and_tendon_torques': 'UNKNOWN',
              'start_note': 'Physical pickup under corrected return behavior. Any resulting contact-state difference is reported, never reset/snap-corrected.'}
    w = None; stream = None; latches = []
    try:
        w = DualScene(output); w.start_video()
        stream = (output/'pre_step_drive_qf.jsonl').open('x', buffering=1)
        original_step = w.scene.step
        def measured_step():
            stream.write(json.dumps({'next_step': w.steps+1, 'phase': w.phase_name,
                'arms': {s: {'drives': drives(arm), 'qpos': arm.robot.get_qpos().tolist(),
                              'engine_qvel': arm.robot.get_qvel().tolist(),
                              'external_qf_command': arm.robot.get_qf().tolist(),
                              'actual_drive_torque_Nm': None} for s,arm in w.arms.items()}})+'\n')
            original_step()
        w.scene.step = measured_step
        arm = w.arms['left']; original_latch = arm.latch_grasp_contact
        def latch():
            result = original_latch()
            latches.append({'step':w.steps,'returned':result,'drives':drives(arm)})
            return result
        arm.latch_grasp_contact = latch
        prepare_left(w)
        report['initial_pickup_latch_calls'] = len(latches)
        report['initial_pickup_latch_returned_result'] = len(latches)==1 and isinstance(latches[0]['returned'],dict)
        save(output/'latch_calls.json',latches)
        report['initial_left_bilateral'] = arm.bilateral_pad_contact()
        actions=[json.loads((EPISODE/f'decision_{i:03d}/proposal.json').read_text()) for i in range(4)]
        for i in range(3):
            result = replay(w,actions[i],EPISODE/'group_003/left_trajectory.npz') if i==2 else execute_action(w,actions[i])
            assert result['ok']==(i==2), 'PREFIX_ACTION_CHANGED'
        report['archived_successful_D3_replayed'] = True
        save(output/'before_case_state_PRIVATE.json',w.records[-1])
        report['old_pre_D4_state_comparison_not_a_gate']=compare_start(w.records[-1],read_rows(EPISODE)[3466])
        report['case_start_step']=w.steps; report['status']='RUNNING'
        if a.case=='d4':
            report['receipt']=replay(w,actions[3],EPISODE/'group_004/left_trajectory.npz')
            if report['receipt']['ok']:
                w.phase_name='fixed_d4_post_motion_hold';w.tick(500)
        elif a.case=='hold':
            w.phase_name='fixed_original_hold';w.tick(1474)
            report['receipt']={'ok':True,'hold_steps':1474}
        elif a.case=='release':
            w.phase_name='fixed_normal_open'
            proposal={'done':False,'execution':'sequential','actions':[{'arm':'left','kind':'gripper','pose_world_wxyz':None,'opening_fraction':1.0}]}
            save(output/'release_proposal.json',proposal);report['receipt']=execute_action(w,proposal)
            w.phase_name='fixed_post_release_observation';w.tick(500)
            cs=w.contacts()
            report['release_checks']={'gap_over_70mm':arm.state()['actual_pad_gap_m']>.07,
                                      'left_bilateral_absent':not arm.bilateral_pad_contact(),
                                      'object_table_contact':any('target_cube' in c['names'] and 'table' in c['names'] for c in cs)}
        else:
            root=ROOT/'evidence/gripper_drive_audit_20261015'
            target=json.loads((root/'predeclared_checks.json').read_text())['heldout']['target_world_wxyz']
            proposal={'done':False,'execution':'sequential','actions':[{'arm':'left','kind':'tcp','pose_world_wxyz':target,'opening_fraction':None}]}
            report['receipt']=replay(w,proposal,root/'original_readback_01/heldout_trajectory_FROZEN.npz')
            if report['receipt']['ok']:
                w.phase_name='fixed_heldout_post_motion_hold';w.tick(500)
        report['status']='COMPLETED' if report['receipt']['ok'] else 'EXECUTOR_REJECTED_OR_RESIDUAL_FAILURE'
    except Exception as exc:
        report.update(status='STOPPED',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            report['last_step']=w.steps
            report['unchanged_task_assessment']=assess(w.records,w.dt)
            if 'case_start_step' in report:
                rows=[r for r in w.records if r['step']>=report['case_start_step']]
                p0,r0=relative(rows[0]);ps=[relative(r) for r in rows]
                report['case_metrics']={'observed_s':(len(rows)-1)*w.dt,
                    'max_relative_translation_mm':max(float(np.linalg.norm(p-p0))*1000 for p,_ in ps),
                    'max_relative_rotation_deg':max(angle(r0,r) for _,r in ps),
                    'max_pad_penetration_mm':max(max(pad_penetration(r).values(),default=0.) for r in rows),
                    'left_bilateral_every_step':all(r['bilateral_contact']['left'] for r in rows)}
            save(output/'final_state_PRIVATE.json',w.records[-1]);w.frame();w.observe(output/'final_observation');w.close()
        if stream:stream.close()
        assert hashlib.sha256((HISTORY/'ledger.json').read_bytes()).hexdigest()==ledger_sha
        if output.exists():save(output/'regression_result.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
