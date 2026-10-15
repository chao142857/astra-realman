"""PRIVATE engineering witness from table, using only execute_action numeric commands.

GT is used here to select/reference engineering targets, never by the public
executor or model context. No OMPL, qpos writes, cube pose writes, or constraints.
"""
import argparse
import json
import os
import traceback
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def run_reference(w, report):
    from action_interface import execute_action
    from gripper_centering import open_tcp_for_closed_center
    stages=[];report['stages']=stages
    ready={s:[*a.state()['actual_grasp_center_world'],*a.state()['flange_pose_world'][3:]] for s,a in w.arms.items()}
    def command(name,side,pose=None,opening=None):
        report['attempted_stage']=name;w.phase_context=name
        action={'done':False,'execution':'sequential','actions':[{'arm':side,'kind':'tcp' if pose is not None else 'gripper',
                'pose_world_wxyz':None if pose is None else np.asarray(pose,float).tolist(),'opening_fraction':opening}]}
        index=len(stages);p=w.output/f'reference_{index:03d}';p.mkdir()
        (p/'proposal_PRIVATE.json').write_text(json.dumps(action,indent=2)+'\n')
        before=w.steps;receipt=execute_action(w,action)
        (p/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        stages.append({'stage':name,'start_step':before,'end_step':w.steps,'ok':receipt['ok'],'artifact':p.name})
        if not receipt['ok']:raise RuntimeError('NUMERIC_REJECTED:'+name+':'+str(receipt.get('reason',receipt)))
        w.phase_context=None
    def move(name,side,pose):command(name,side,pose=pose)
    def grip(name,side,value):command(name,side,opening=value)
    down=[0.,1.,0.,0.]
    # Same fixed table cube and Ready reset as the existing 1.1 m scene.
    xy=w.cube.get_pose().p[:2].copy()
    for z in (.20,.08,.04):move('left_pick_approach_'+str(z),'left',[*xy,z,*down])
    grip('left_pick_close','left',.45)
    current=np.asarray(w.arms['left'].state()['actual_grasp_center_world'])
    move('left_pick_lift','left',[*(current+[0,0,.14]),*down])
    w.phase_name='left_pick_hold';w.tick(500)
    if not w.arms['left'].bilateral_pad_contact():raise RuntimeError('LEFT_PICK_NOT_HOLDING')
    w.observe(w.output/'after_pick')
    # One geometric candidate. Opposed tool approach axes and orthogonal pad
    # closing axes leave different cube faces to the two grippers.
    left_q=[0.,.8660254037844386,0.,.5]
    right_q=[-.3535533905932738,.6123724356957945,.6123724356957945,-.3535533905932738]
    move('left_to_handoff','left',[.36,0,.22,*left_q])
    w.phase_name='left_handoff_hold';w.tick(500)
    if not w.arms['left'].bilateral_pad_contact():raise RuntimeError('LEFT_CARRY_CONTACT_LOST')
    w.observe(w.output/'handoff_before_receive')
    center=w.cube.get_pose().p.copy()
    tcp,delta=open_tcp_for_closed_center(w.arms['right'],center,right_q,.05)
    direction=Rotation.from_quat(np.roll(right_q,-1)).apply([0,0,1])
    (w.output/'centering_PRIVATE.json').write_text(json.dumps({'object_center':center.tolist(),'open_tcp':tcp.tolist(),
        'cad_closure_delta_local':delta.tolist(),'tool_axis_world':direction.tolist()},indent=2)+'\n')
    move('right_receive_approach','right',[*(tcp-.09*direction),*right_q])
    move('right_receive_contact_pose','right',[*tcp,*right_q])
    grip('right_receive_close','right',.45)
    w.phase_name='both_grip_settle';w.tick(125)
    if not w.arms['right'].bilateral_pad_contact():raise RuntimeError('RIGHT_RECEIVE_NO_BILATERAL')
    grip('left_release','left',1.)
    w.phase_name='right_independent_hold';w.tick(500)
    if not w.arms['right'].bilateral_pad_contact():raise RuntimeError('RIGHT_INDEPENDENT_CONTACT_LOST')
    w.observe(w.output/'right_independent')
    left=w.arms['left'];p=np.asarray(left.state()['actual_grasp_center_world'])
    axis=Rotation.from_quat(np.roll(left_q,-1)).apply([0,0,1])
    move('left_withdraw_open','left',[*(p-.10*axis),*left_q])
    move('left_return_ready','left',ready['left'])
    right=w.arms['right'];current=np.asarray(right.state()['actual_grasp_center_world'])
    move('right_exit','right',[*(current-.08*direction),*right_q])
    move('right_to_place_above','right',[.52,.16,.15,*right_q])
    # Placement reference accounts for the actually held cube OBB and relative
    # offset. This calculation remains private to the engineering witness.
    obj=w.cube.get_pose();extent=abs(Rotation.from_quat(np.roll(obj.q,-1)).as_matrix())@np.repeat(.025,3)
    offset=obj.p-np.asarray(right.state()['actual_grasp_center_world'])
    desired=np.array([.52,.16,float(extent[2])+.003])-offset
    move('right_lower_for_place','right',[*desired,*right_q])
    grip('right_release','right',1.)
    w.phase_name='right_release';w.tick(500)
    w.observe(w.output/'after_place')
    report['attempted_stage']='complete';report['status']='EXECUTION_COMPLETE_PENDING_SCORE'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--pgs-diagnostic',action='store_true',help='One explicit integration control; not the production default.')
    a=p.parse_args()
    root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    import sapien
    original_create=sapien.Engine.create_scene
    if a.pgs_diagnostic:
        # The installed legacy Engine.create_scene(config=SceneConfig())
        # overwrites the global config. Supply the selected config to that
        # actual creation call; a preceding set_scene_config alone is ignored.
        def create_pgs(engine,config=None):
            physics_config=sapien.physx.get_scene_config();physics_config.enable_tgs=False
            return original_create(engine,physics_config)
        sapien.Engine.create_scene=create_pgs
    from dual_scene import DualScene,CONFIG,CONTROLLER
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from evaluate_process import evaluate
    relocate_runtime_mesh_paths(CONFIG)
    w=None;report={'task':'full_table_pick_handoff_place','source':'PRIVATE_ENGINEERING_REFERENCE_NOT_ASTRA',
        'controller':CONTROLLER,'model_requests':0,'integration_model':'PGS_DIAGNOSTIC' if a.pgs_diagnostic else 'ORIGINAL_TGS',
        'initialization':'table cube, both empty/open; NO expert pregrasp',
        'executor':'action_interface.execute_action, original numeric IK/interpolation/precheck',
        'status':'RUNNING'}
    try:
        try:w=DualScene(a.output)
        finally:sapien.Engine.create_scene=original_create
        report['actual_scene_creation_enable_tgs']=bool(sapien.physx.get_scene_config().enable_tgs)
        assert report['actual_scene_creation_enable_tgs'] is (not a.pgs_diagnostic)
        w.start_video();w.observe(w.output/'table_initial')
        assert all(arm.state()['actual_pad_gap_m']>.085 for arm in w.arms.values())
        assert not any(arm.bilateral_pad_contact() for arm in w.arms.values())
        run_reference(w,report)
    except Exception as exc:report.update(status='INCOMPLETE',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            report.update(last_step=w.steps,sim_time_s=w.steps*w.dt)
            w.observe(w.output/'final_observation');w.close()
            report['historical_process_score_unchanged']=evaluate(w.output)
            (w.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
