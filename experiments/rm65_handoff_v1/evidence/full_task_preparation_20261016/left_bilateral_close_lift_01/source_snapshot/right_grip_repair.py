"""Finite PRIVATE full-route controller repair trials; zero model/network calls.

The numerical executor, IK, collision checks and proposals are not patched.
Only the right actuator's contact-latched velocity feedback is versioned.
"""
import argparse, json, os, traceback
from pathlib import Path
import numpy as np


CANDIDATES={
 'no_native_damping':'Only right contact-hold master damping 2 -> 0. K/target/preload/10 Nm unchanged; other finger damping unchanged.',
 'all_finger_native_damping_off':'Relative to candidate 1: also remove native velocity damping on the five right follower joints during hold; restore ordinary follower damping on opening. No stiffness/target/force/path changes.',
 'position_difference_feedback':'Original K/D/limit. Right hold velocity target = native qvel - position finite-difference velocity, bounded by URDF velocity limit. Experimental feedback-source compensation, not a measured torque.'}

class ReleaseRegressionComplete(Exception):pass


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',choices=CANDIDATES,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--release-regression',action='store_true',help='After strict 7s hold, test ordinary opening at the handoff location; not a placement success.')
    p.add_argument('--fine-transport-reference',action='store_true',help='Private explicit 5mm engineering TCP targets on the original transport/lowering line; NOT an executor feature.')
    a=p.parse_args();root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    assert os.environ['RM65_CONTROLLER']=='urdf_effort_hold_v2'
    assert os.environ.get('RM65_SOLVER','original')=='original'
    from dual_scene import DualScene,CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from full_handoff_reference import run_reference
    from right_grip_hold_score import score
    from evaluate_process import evaluate
    relocate_runtime_mesh_paths(CONFIG)
    report={'status':'RUNNING','candidate':a.candidate,'change':CANDIDATES[a.candidate],
        'model_requests':0,'route':'full_numeric_known_d3_urdf_effort_04','expert_not_astra':True,
        'private_transport_reference':'explicit_5mm_targets' if a.fine_transport_reference else 'original_single_targets'}
    w=None;telemetry=None;hold={};control={'latched_target':None};previous=None
    try:
        w=DualScene(a.output);arm=w.arms['right'];master=arm.joints[arm.master]
        original_latch=arm.latch_grasp_contact
        def latch():
            result=original_latch();K=master.get_stiffness();D=master.get_damping();cap=master.get_force_limit()
            control.update(latched_target=float(master.get_drive_target()[0]),right_latch_step=w.steps)
            record={'step':w.steps,'before':{'K':K,'D':D,'limit_Nm':cap,'target':control['latched_target']},'candidate':a.candidate}
            if a.candidate=='no_native_damping':
                from right_hold_velocity_v3 import apply
                record['versioned_controller']=apply(arm)
            elif a.candidate=='all_finger_native_damping_off':
                master.set_drive_property(K,0.,force_limit=cap)
                saved=[]
                for i,j in enumerate(arm.joints):
                    if i in arm.arm_indices or i==arm.master:continue
                    saved.append((i,j.get_stiffness(),j.get_damping(),j.get_force_limit()))
                    j.set_drive_property(j.get_stiffness(),0.,force_limit=j.get_force_limit())
                control['restore_followers']=saved;record['followers_before']=saved
            record['after']={'K':master.get_stiffness(),'D':master.get_damping(),'limit_Nm':master.get_force_limit(),'target':float(master.get_drive_target()[0])}
            arm.log('right_hold_feedback_v3',record);report['controller_change']=record
            return result
        arm.latch_grasp_contact=latch
        telemetry=(w.output/'right_native_readback.jsonl').open('x',buffering=1)
        original_step=w.scene.step
        def step():
            nonlocal previous
            q=float(arm.robot.get_qpos()[arm.master]);native=float(arm.robot.get_qvel()[arm.master]);fd=0. if previous is None else (q-previous)/w.dt
            active=control['latched_target'] is not None and abs(float(master.get_drive_target()[0])-control['latched_target'])<1e-7
            if control.get('restore_followers') and master.get_damping()>0:
                for i,K,D,cap in control.pop('restore_followers'):arm.joints[i].set_drive_property(K,D,force_limit=cap)
                arm.log('right_follower_opening_properties_restored',{'next_step':w.steps+1,'no_target_change':True})
            if a.candidate=='position_difference_feedback':
                velocity=float(np.clip(native-fd,-10,10)) if active else 0.
                master.set_drive_velocity_target(velocity)
            previous=q
            original_step()
            if control['latched_target'] is not None:
                contacts=[]
                for c in w.scene.get_contacts():
                    names=[b.entity.name for b in c.bodies]
                    if 'target_cube' not in names:continue
                    contacts.append({'names':names,'points':[{'position':pt.position.tolist(),'normal':pt.normal.tolist(),
                        'impulse':pt.impulse.tolist(),'separation':float(pt.separation)} for pt in c.points]})
                telemetry.write(json.dumps({'step':w.steps+1,'native_qvel_before':native,'fd_qvel_before':fd,
                    'master_qpos_after':float(arm.robot.get_qpos()[arm.master]),'D':master.get_damping(),
                    'position_target':float(master.get_drive_target()[0]),'velocity_target':float(master.get_drive_velocity_target()[0]),
                    'force_limit':master.get_force_limit(),'native_actuator_torque':None,'contacts':contacts})+'\n')
        w.scene.step=step
        original_tick=w.tick
        def tick(n):
            if w.phase_name=='right_independent_hold' and n==500:
                start=w.steps;reference=w.records[-1];original_tick(500)
                hold['first_2s']=score([r for r in w.records if start<r['step']<=w.steps],reference=reference)
                (w.output/'hold_checks.json').write_text(json.dumps(hold,indent=2)+'\n')
                if not hold['first_2s']['pass']:raise RuntimeError('ENGINEERING_HOLD_2S_FAIL')
                w.observe(w.output/'right_independent_2s')
                second=w.steps;original_tick(1250)
                hold['additional_5s']=score([r for r in w.records if second<r['step']<=w.steps],required_s=5.,reference=reference)
                hold['combined_7s']=score([r for r in w.records if start<r['step']<=w.steps],required_s=7.,reference=reference)
                (w.output/'hold_checks.json').write_text(json.dumps(hold,indent=2)+'\n')
                if not hold['combined_7s']['pass']:raise RuntimeError('ENGINEERING_HOLD_7S_FAIL')
                if a.release_regression:
                    from action_interface import execute_action
                    proposal={'done':False,'execution':'sequential','actions':[{'arm':'right','kind':'gripper','pose_world_wxyz':None,'opening_fraction':1.}]}
                    (w.output/'release_regression_proposal_PRIVATE.json').write_text(json.dumps(proposal,indent=2)+'\n')
                    w.phase_context='right_open_regression';receipt=execute_action(w,proposal);w.phase_context=None
                    assert receipt['ok'],receipt
                    w.phase_name='release_regression_passive_hold';start=w.steps;original_tick(500)
                    samples=[r for r in w.records if r['step']>start]
                    tests={'right_open_gap_over_70mm':all(r['arms']['right']['actual_pad_gap_m']>.07 for r in samples),
                        'no_right_bilateral':all(not r['bilateral_contact']['right'] for r in samples),
                        'cube_table_supported':all(any('table' in c['names'] and 'target_cube' in c['names'] for c in r['contacts']) for r in samples),
                        'right_original_opening_damping_restored':abs(master.get_damping()-2)<1e-6}
                    report['normal_opening_regression']={'pass':all(tests.values()),'checks':tests,'duration_s':2.,'receipt':receipt,
                        'not_blue_zone_placement':True}
                    raise ReleaseRegressionComplete()
            else:original_tick(n)
        w.tick=tick
        source=root/'evidence/full_handoff_restore_20261015/full_numeric_known_d3_urdf_effort_04'
        prefix=[json.loads((source/f'reference_{i:03d}/proposal_PRIVATE.json').read_text()) for i in range(10)]
        (w.output/'candidate_plan.json').write_text(json.dumps(CANDIDATES,indent=2)+'\n')
        w.start_video();w.observe(w.output/'table_initial')
        run_reference(w,report,fixed_pickup_orientation=True,frozen_numeric_prefix=prefix,fine_transport_reference=a.fine_transport_reference)
    except ReleaseRegressionComplete:report['status']='RELEASE_REGRESSION_COMPLETE_NOT_FULL_TASK'
    except Exception as exc:report.update(status='INCOMPLETE',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            report.update(last_step=w.steps,sim_time_s=w.steps*w.dt,engineering_hold=hold)
            w.observe(w.output/'final_observation');w.close()
            if telemetry:telemetry.close()
            report['historical_process_score_unchanged']=evaluate(w.output)
            (w.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if report['status']=='INCOMPLETE':raise SystemExit(1)


if __name__=='__main__':main()
