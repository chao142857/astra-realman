"""PRIVATE expert planning only. Output TCP waypoints go through unchanged public executor.
Never imported by model loop; never included in model context. No physical pose writes.
"""
import json,numpy as np
from scipy.spatial.transform import Rotation

def move(w,side,target):
 a=w.arms[side];plan=a.plan_tcp(target);q=a.robot.get_qpos().copy();goal=q.copy();goal[a.arm_indices]=plan['position'][-1]
 a.motion.update_from_simulation();a.motion.robot.set_qpos(q,True)
 status,path=a.motion.planner.plan(q[a.arm_indices],[goal[a.arm_indices]],time=10.,range=.05,fixed_joints=set(),simplify=False)
 if status!='Exact solution':raise RuntimeError('PRIVATE_RRT:'+status)
 path=np.asarray(path);flange=a.links['Link6'].get_pose().to_transformation_matrix();local=flange[:3,:3].T@(a.pads().mean(0)-flange[:3,3]);goals=[]
 # Explicit dense geometric path. No TOPP spline across RRT corners.
 for begin,end in zip(path[:-1],path[1:]):
  n=max(1,int(np.ceil(np.max(abs(end-begin))/.06)))
  for t in np.linspace(0,1,n+1)[1:]:
   sample=q.copy();sample[a.arm_indices]=(1-t)*begin+t*end
   a.motion.pinocchio_model.compute_forward_kinematics(sample)
   pose=a.motion.robot.get_base_pose()*a.motion.pinocchio_model.get_link_pose(a.motion.link_name_2_idx[a.motion.move_group])
   xyz=np.asarray(pose.p)+Rotation.from_quat(np.roll(pose.q,-1)).as_matrix()@local
   goals.append([*xyz,*pose.q])
 folder=w.output/f'private_rrt_{w.group_count:03d}';folder.mkdir();(folder/'waypoints_NOT_MODEL_INPUT.json').write_text(json.dumps({'status':status,'raw_q_path':path.tolist(),'tcp_waypoints':goals},indent=2))
 for pose in goals:
  result=w.execute_group({side:{'pose':pose}})
  if not result['ok']:raise RuntimeError('RRT_NUMERIC_REPLAY:'+str(result))
 return {'ok':True,'private_rrt_waypoints':len(goals)}
