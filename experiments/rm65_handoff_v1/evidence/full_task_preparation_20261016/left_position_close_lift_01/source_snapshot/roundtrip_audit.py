"""Reconstruct the first rejected archived waypoint in planning models only.
No robot or object pose is written to PhysX; this is a non-execution FK/IK audit.
"""
import json,gzip,numpy as np
from pathlib import Path
from scipy.spatial.transform import Rotation
import mplib,sapien
from mplib.sapien_utils.conversion import convert_object_name
from mplib.collision_detection.fcl import FCLObject
from dual_scene import DualScene
D=Path(__file__).parent;history=D/'evidence/rrt_numeric_replay_01';w=DualScene(D/'evidence/consistency_20261014/roundtrip');out=w.output
try:
 rows=[json.loads(x) for x in gzip.open(history/'physics.jsonl.gz','rt')];last=rows[-1]
 cfg=w.scene.get_physx_system().config
 info={'sapien_version':sapien.__version__ if hasattr(sapien,'__version__') else '3.0.0b1','physx_version':sapien.physx.version(),'scene':{k:getattr(cfg,k).tolist() if hasattr(getattr(cfg,k),'tolist') else getattr(cfg,k) for k in ['gravity','enable_tgs','enable_pcm','enable_friction_every_iteration','enable_ccd']},'solver_iterations':w.solver_record,'cube_COM_local_pose':[*w.cube_body.cmass_local_pose.p.tolist(),*w.cube_body.cmass_local_pose.q.tolist()],'sampling':'Original tick logs actor pose and COM velocity consecutively after each synchronous scene.step(), dt=0.004s. No intermediate step. COM offset checked above.'}
 (out/'runtime_info.json').write_text(json.dumps(info,indent=2))
 for a in w.arms.values():a.init_planner();a.motion.update_from_simulation()
 qs={s:np.array(last['arms'][s]['qpos']) for s in w.arms}
 cube_name=convert_object_name(w.cube)
 for a in w.arms.values():
  world=a.motion.planning_world
  for s,oa in w.arms.items():world.get_articulation(convert_object_name(oa.robot)).set_qpos(qs[s],full=True)
  obj=world.get_object(cube_name);world.add_object(FCLObject(cube_name,mplib.Pose(last['object_pose'][:3],last['object_pose'][3:]),obj.shapes,obj.shape_poses))
 a=w.arms['right'];m=a.motion;qm=qs['right'];idx=m.link_name_2_idx[m.move_group]
 def matrix_pose(q):
  m.pinocchio_model.compute_forward_kinematics(q);return m.robot.get_base_pose()*m.pinocchio_model.get_link_pose(idx)
 def local_pad(q):
  m.pinocchio_model.compute_forward_kinematics(q);fl=m.pinocchio_model.get_link_pose(idx).to_transformation_matrix();pts=[]
  for name,vs in a.pad_vertices.items():
   t=m.pinocchio_model.get_link_pose(m.link_name_2_idx[a.prefix+name]).to_transformation_matrix();pts.append((vs@t[:3,:3].T+t[:3,3]).mean(0))
  return fl[:3,:3].T@(np.mean(pts,axis=0)-fl[:3,3])
 def cols(q):
  m.robot.set_qpos(q,True);return [{'object1':c.object_name1,'link1':c.link_name1,'object2':c.object_name2,'link2':c.link_name2} for c in m.planning_world.check_collision()]
 route=json.loads((history/'private_rrt_018/waypoints_NOT_MODEL_INPUT.json').read_text());path=np.array(route['raw_q_path']);start=np.load(history/'group_019/right_trajectory.npz')['start_full'];samples=[]
 for begin,end in zip(path[:-1],path[1:]):
  n=max(1,int(np.ceil(np.max(abs(end-begin))/.06)))
  for t in np.linspace(0,1,n+1)[1:]:
   sample=start.copy();sample[a.arm_indices]=(1-t)*begin+t*end;samples.append(sample)
 failed=51;known=samples[failed];known_fl=matrix_pose(known);kp=known_fl.to_transformation_matrix();knownlocal=local_pad(known);actualfr=np.array(last['arms']['right']['flange_pose_world']);actualtcp=np.array(last['arms']['right']['actual_grasp_center_world']);actual_R=Rotation.from_quat(np.roll(actualfr[3:],-1));measuredlocal=actual_R.inv().apply(actualtcp-actualfr[:3]);target=np.array(json.loads((history/'group_070/proposal.json').read_text())['right']['pose'])
 # Archived executor converted target using its current measured finger-dependent offset.
 request_fl=target.copy();request_fl[:3]-=Rotation.from_quat(np.roll(target[3:],-1)).apply(measuredlocal);goal=m._transform_goal_to_wrt_base(mplib.Pose(request_fl[:3],request_fl[3:]));mask=np.ones(len(qm),dtype=bool);mask[a.arm_indices]=False
 tests=[]
 for label,seed in [('actual_logged_seed',qm),('known_waypoint_seed',known)]:
  m.robot.set_qpos(qm,True);status,sol=m.IK(goal,seed,mask=mask,return_closest=True,verbose=True)
  tests.append({'seed':label,'status':status,'solution':None if sol is None else sol.tolist()})
 # Pure CLIK without collision gating: records exact branch/limit/collision separately.
 cli,ok,error=m.pinocchio_model.compute_IK_CLIK(idx,goal,known,mask);fk=m.pinocchio_model;fk.compute_forward_kinematics(cli);returned=fk.get_link_pose(idx);limit_ok=m.wrap_joint_limit(cli)
 actual_fk=matrix_pose(qm);known_fk_base=m.robot.get_base_pose().inv()*known_fl
 report={'archived_first_rejection_group':70,'private_waypoint_index_zero_based':failed,'physical_step_before_rejection':last['step'],'archived_target_tcp':target.tolist(),'known_qpos':known.tolist(),'known_FK_world_flange':[*known_fl.p,*known_fl.q],'known_FK_TCP_using_known_gripper_geometry':(kp[:3,3]+kp[:3,:3]@knownlocal).tolist(),'requested_flange_using_actual_gripper_offset':request_fl.tolist(),'known_flange_request_translation_error_m':float(np.linalg.norm(request_fl[:3]-known_fl.p)),'known_flange_request_rotation_error_rad':float((Rotation.from_quat(np.roll(known_fl.q,-1)).inv()*Rotation.from_quat(np.roll(target[3:],-1))).magnitude()),'robot_FK_vs_logged_flange_translation_error_m':float(np.linalg.norm(actual_fk.p-actualfr[:3])),'robot_FK_vs_logged_flange_rotation_error_rad':float((Rotation.from_quat(np.roll(actual_fk.q,-1)).inv()*actual_R).magnitude()),'known_gripper_TCP_offset':knownlocal.tolist(),'actual_measured_gripper_TCP_offset':measuredlocal.tolist(),'archived_generator_constant_TCP_offset':local_pad(start).tolist(),'waypoint_known_configuration_collision_pairs':cols(known),'pure_CLIK_success':bool(ok),'pure_CLIK_wrap_limits_pass':bool(limit_ok),'pure_CLIK_pose_distance':float(goal.distance(returned)),'pure_CLIK_solution':cli.tolist(),'pure_CLIK_collision_pairs':cols(cli),'collision_gated_IK_tests':tests,'joint_names_sim':a.names,'joint_names_pinocchio':m.user_joint_names}
 (out/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
finally:w.close()
