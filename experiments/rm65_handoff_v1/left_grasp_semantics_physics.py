"""PRIVATE finite table-close/lift interface check. No model or online route."""
import argparse,json,os,time,traceback
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--physics-only',action='store_true',help='Real PhysX only; no RGB or video')
    p.add_argument('--release-regression',action='store_true',help='Separate explicit opening test after stable-lift evidence')
    p.add_argument('--mode',choices=['position','bilateral_hold'],required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent;os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    if a.physics_only:
        from replay_without_rendering import install as omit_rendering
        omit_rendering()
    from dual_scene import DualScene,CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from action_interface import execute_action
    from numeric_action_chunk import execute_chunk,public_receipt
    from right_hold_velocity_v3 import install
    from evaluate_process import evaluate
    if a.physics_only:
        from replay_without_rendering import omit_observations
        omit_observations(DualScene)
    relocate_runtime_mesh_paths(CONFIG);w=None;report={'real_requests':0,'bridge_connections':0,
        'source':'PRIVATE_ENGINEERING_INTERFACE_NOT_ASTRA','mode':a.mode,'status':'RUNNING',
        'rendering':'OMITTED_NO_RGB_OR_VIDEO' if a.physics_only else 'ORIGINAL_FOUR_CAMERAS'}
    def single(action,hold=0):return {'done':False,'stages':[{'mode':'sequential','actions':[action],'observe_s':hold}]}
    try:
        w=DualScene(a.output);install(w);w.start_video();w.observe(w.output/'table_initial')
        source=root/'evidence/right_grip_repair_20261016/candidate1_no_native_damping_01'
        # Three unchanged archived engineering approach targets, never online.
        for i in range(3):
            proposal=json.loads((source/f'reference_{i:03d}/proposal_PRIVATE.json').read_text())
            receipt=execute_action(w,proposal);assert receipt['ok'],receipt
        before=w.steps
        close=single({'arm':'left','kind':'gripper','opening_fraction':.45,'contact_mode':a.mode})
        r=execute_chunk(w,close);report['close_receipt']=r;report['close_start_step']=before;report['close_end_step']=w.steps
        report['close_public_receipt']=public_receipt(r)
        assert r['groups'][0]['receipt']['gripper_execution']['left']['stable_grasp']=='NOT_ASSESSED_BY_SERVO'
        if a.mode=='bilateral_hold':
            assert not r['ok'] and r['recoverable_action_feedback'],r
        else:assert r['ok'],r
        w.observe(w.output/'close_end')
        # No implicit lift: all actual arm drive targets during closure stay at
        # the measured starting joints. This next lift is a separate test input.
        samples=[x for x in w.records if before<x['step']<=w.steps]
        report['close_actual_tcp_z_range_m']=[min(x['arms']['left']['actual_grasp_center_world'][2] for x in samples),max(x['arms']['left']['actual_grasp_center_world'][2] for x in samples)]
        lift=json.loads((source/'reference_004/proposal_PRIVATE.json').read_text())['actions'][0]['pose_world_wxyz']
        (w.output/'separate_lift_input_PRIVATE.json').write_text(json.dumps(lift)+'\n')
        report['lift_start_step']=w.steps
        r2=execute_chunk(w,single({'arm':'left','kind':'tcp','waypoints_world_wxyz':[lift]},hold=2.))
        report['lift_receipt']=r2;assert r2['ok'],r2
        samples=w.records[-500:];rel=[];qs=[];contacts=[];maxpen=0
        for x in samples:
            st=x['arms']['left'];tcp=np.asarray(st['actual_grasp_center_world']);q=st['flange_pose_world'][3:]
            rot=Rotation.from_quat(np.roll(q,-1));rel.append(rot.inv().apply(np.asarray(x['object_pose'][:3])-tcp))
            qs.append(rot.inv()*Rotation.from_quat(np.roll(x['object_pose'][3:],-1)))
            cubecontacts=[c for c in x['contacts'] if 'target_cube' in c['names']]
            contacts.append(x['bilateral_contact']['left'] and x['object_pose'][2]>.07 and not any('table' in c['names'] or any(n.startswith('R__') for n in c['names']) for c in cubecontacts))
            for c in cubecontacts:
                if any('Support_Link' in n for n in c['names']):maxpen=max(maxpen,-min(p['separation'] for p in c['points']))
        drift=float(max(np.linalg.norm(x-rel[0]) for x in rel));angle=float(max((qs[0].inv()*q).magnitude() for q in qs))
        report['post_lift_private_evidence']={'duration_s':len(samples)*w.dt,'continuous_bilateral_without_other_support':all(contacts),
            'relative_translation_drift_m':drift,'relative_rotation_drift_rad':angle,'maximum_pad_penetration_m':maxpen,
            'stable_grasp_2s':len(samples)==500 and all(contacts) and drift<=.002 and angle<=np.deg2rad(5) and maxpen<=.002}
        assert report['post_lift_private_evidence']['stable_grasp_2s'],report['post_lift_private_evidence']
        w.observe(w.output/'lift_hold_end')
        if a.release_regression:
            before_release=w.steps
            release=single({'arm':'left','kind':'gripper','opening_fraction':1.,'contact_mode':'position'},hold=2.)
            (w.output/'explicit_release_test_input.json').write_text(json.dumps(release,indent=2)+'\n')
            release_result=execute_chunk(w,release);report['release_receipt']=release_result
            tail=w.records[-500:]
            evidence={'start_step':before_release,'end_step':w.steps,
                'command_ok':release_result['ok'],'final_master_rad':float(w.arms['left'].robot.get_qpos()[w.arms['left'].master]),
                'no_bilateral_in_last_2s':all(not x['bilateral_contact']['left'] for x in tail),
                'table_support_in_last_2s':all(any('target_cube' in c['names'] and 'table' in c['names'] for c in x['contacts']) for x in tail),
                'object_position_range_last_2s_m':np.ptp(np.asarray([x['object_pose'][:3] for x in tail]),axis=0).tolist()}
            evidence['pass']=evidence['command_ok'] and abs(evidence['final_master_rad'])<.02 and evidence['no_bilateral_in_last_2s'] and evidence['table_support_in_last_2s'] and max(evidence['object_position_range_last_2s_m'])<.002
            report['release_regression']=evidence;assert evidence['pass'],evidence
            w.observe(w.output/'release_end')
        report['status']='PASS_INTERFACE_ONLY_NOT_FULL_TASK'
    except Exception as e:report.update(status='FAIL',error=repr(e),traceback=traceback.format_exc())
    finally:
        if w:
            report['physics_steps']=w.steps;w.close();report['historical_process_score_unchanged']=evaluate(w.output)
            (w.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('close_receipt','close_public_receipt','lift_receipt')},indent=2))
    if report['status']=='FAIL':raise SystemExit(1)


if __name__=='__main__':main()
