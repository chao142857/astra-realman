"""PRIVATE finite actuator acceptance. No model, Bridge or full-task success claim.

Only engineering initialization replays the archived pre-transport prefix.
The public executor has no access to this file or any reference directory.
"""
import argparse,hashlib,json,os,time,traceback
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    assert os.environ['RM65_CONTROLLER']=='urdf_effort_hold_v2' and os.environ.get('RM65_SOLVER','original')=='original'
    from dual_scene import DualScene,CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from action_interface import execute_action
    from numeric_action_chunk import execute_chunk,actual_pose
    from right_hold_velocity_v3 import install
    from right_grip_hold_score import score
    relocate_runtime_mesh_paths(CONFIG)
    report={'source':'PRIVATE_ENGINEERING_NOT_ASTRA','real_requests':0,'bridge_connections':0,
        'not_a_full_task_trial':True,'cases':[],'status':'RUNNING'}
    w=None;started=time.monotonic()
    def save():(w.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    def gripper(side,opening,mode):return {'arm':side,'kind':'gripper','opening_fraction':opening,'contact_mode':mode}
    def single(actions,mode='sequential',hold=0):return {'done':False,'stages':[{'mode':mode,'actions':actions,'observe_s':hold}]}
    def run_case(name,proposal):
        report['current_case']=name;before=w.steps
        (w.output/(name+'_input.json')).write_text(json.dumps(proposal,indent=2)+'\n')
        receipt=execute_chunk(w,proposal)
        row={'case':name,'start_step':before,'end_step':w.steps,'receipt_ok':receipt['ok'],
            'reason':receipt.get('reason'),'chunk':w.chunk_count}
        report['cases'].append(row);save()
        if not receipt['ok']:raise RuntimeError('ACCEPTANCE_CASE_FAILED:'+name+':'+str(receipt.get('reason')))
        return row
    try:
        w=DualScene(a.output);install(w);w.start_video();w.observe(w.output/'table_initial')
        source=root/'evidence/right_grip_repair_20261016/candidate1_no_native_damping_01'
        report['initialization_proposals']=[]
        for i in range(13):
            file=source/f'reference_{i:03d}/proposal_PRIVATE.json';proposal=json.loads(file.read_text())
            report['initialization_proposals'].append({'index':i,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
            op=proposal['actions'][0]
            if op['kind']=='gripper':
                mode='bilateral_hold' if op['opening_fraction']<.8 else 'position'
                receipt=execute_chunk(w,single([gripper(op['arm'],op['opening_fraction'],mode)]))
            else:receipt=execute_action(w,proposal)
            if not receipt['ok']:raise RuntimeError('PRIVATE_INITIALIZATION_REJECTED:'+str(i)+':'+str(receipt))
            if i==4:w.phase_name='private_left_pick_hold';w.tick(500)
            if i==5:w.phase_name='private_left_handoff_hold';w.tick(500)
            if i==8:w.phase_name='private_both_grip_settle';w.tick(125)
            if i==9:
                reference=w.records[-1];start=w.steps;w.phase_name='explicit_contact_hold_acceptance';w.tick(1750)
                report['explicit_hold_7s']=score([r for r in w.records if start<r['step']],required_s=7.,reference=reference)
                save();assert report['explicit_hold_7s']['pass'],report['explicit_hold_7s']
        w.observe(w.output/'generic_tracking_initial')
        reference=w.records[-1];start=w.steps
        # Exactly one large numerical target, not 5mm targets from a route file.
        run_case('single_long_segment',single([{'arm':'right','kind':'tcp',
            'waypoints_world_wxyz':[[.52,.16,.15,-.5,.5,.5,-.5]]}],hold=2))
        samples=[r for r in w.records if r['step']>start]
        report['long_segment_independent_hold']=score(samples,required_s=(w.steps-start)*w.dt,reference=reference)
        assert report['long_segment_independent_hold']['pass'],report['long_segment_independent_hold']
        # Predeclared cross-check: local bend + 3 degree world yaw, not used to
        # tune subdivision or hold settings. Both waypoints are explicit input.
        p0=actual_pose(w.arms['right']);q0=Rotation.from_quat(np.roll(p0[3:],-1))
        q1=np.roll((Rotation.from_euler('z',3,degrees=True)*q0).as_quat(),1).tolist()
        p1=[p0[0]-.015,p0[1]-.010,p0[2]+.010,*q1]
        p2=[p0[0]-.025,p0[1]+.015,p0[2]+.020,*q1]
        reference=w.records[-1];start=w.steps
        run_case('held_user_bend_and_yaw',single([{'arm':'right','kind':'tcp','waypoints_world_wxyz':[p1,p2]}],hold=2))
        report['bend_independent_hold']=score([r for r in w.records if r['step']>start],
            required_s=(w.steps-start)*w.dt,reference=reference)
        assert report['bend_independent_hold']['pass'],report['bend_independent_hold']
        w.observe(w.output/'tracking_complete')
        # Public position-mode release, not a controlled-placement success.
        run_case('normal_position_open',single([gripper('right',1.,'position')],hold=2))
        state=w.arms['right'].state();j=w.arms['right'].joints[w.arms['right'].master]
        report['release']={'actual_gap_m':state['actual_pad_gap_m'],'bilateral':w.arms['right'].bilateral_pad_contact(),
            'restored_damping':j.get_damping(),'servo_target_rad':float(j.get_drive_target()[0]),'not_placement_success':True}
        assert state['actual_pad_gap_m']>.085 and not report['release']['bilateral'] and abs(j.get_damping()-2)<1e-6
        # The same interface must report absent bilateral holding as a physical
        # execution failure, without inventing a grasp target or retrying.
        before=w.steps
        empty=execute_chunk(w,single([gripper('right',.45,'bilateral_hold')]))
        report['empty_close_negative']={'ok':empty['ok'],'reason':empty.get('reason'),'executed_steps':w.steps-before}
        assert not empty['ok'] and empty['reason']=='GRIPPER_BILATERAL_HOLD_NOT_ESTABLISHED'
        # Opening after a negative is an explicit test command, never auto-repair.
        run_case('negative_cleanup_explicit_open',single([gripper('right',1.,'position')]))
        run_case('empty_position_close',single([gripper('right',.45,'position')]))
        run_case('final_explicit_open',single([gripper('right',1.,'position')]))
        report['status']='PASS_FINITE_ACTUATOR_CASES_NOT_MODEL_TASK_SUCCESS'
    except Exception as exc:report.update(status='FAIL',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            report.update(physics_steps=w.steps,physics_time_s=w.steps*w.dt,wall_s=time.monotonic()-started)
            w.observe(w.output/'final_observation');w.close();save()
    print(json.dumps(report,indent=2))
    if report['status']=='FAIL':raise SystemExit(1)


if __name__=='__main__':main()
