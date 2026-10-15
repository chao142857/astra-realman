"""Private engineering RRT reference, dense screened BEFORE physical replay.
No expert routing exists in the public executor; the model must supply its own goals.
"""
import json,numpy as np,mplib
from mplib.sapien_utils.conversion import convert_object_name
from carry_collision import prepare

def move(w,side,target):
 a=w.arms[side];m=a.motion;prepare(w,{side:{'pose':target}});q=a.robot.get_qpos().copy();plan=a.plan_tcp(target);goal=q.copy();goal[a.arm_indices]=plan['position'][-1]
 actual=a.links['Link6'].pose.to_transformation_matrix();local=actual[:3,:3].T@(a.pads().mean(0)-actual[:3,3]);idx=m.link_name_2_idx[m.move_group];attempts=[];chosen=None;goals=None
 def pose_at(sample):
  m.pinocchio_model.compute_forward_kinematics(sample);p=m.robot.get_base_pose()*m.pinocchio_model.get_link_pose(idx);t=p.to_transformation_matrix();return np.r_[t[:3,3]+t[:3,:3]@local,p.q]
 for attempt in range(12):
  prepare(w,{side:{'pose':target}});m.robot.set_qpos(q,True);status,path=m.planner.plan(q[a.arm_indices],[goal[a.arm_indices]],time=10.,range=.02,simplify=True,fixed_joints=set());record={'attempt':attempt,'status':status};attempts.append(record)
  if status!='Exact solution':continue
  path=np.asarray(path);bad=None;poses=[]
  for begin,end in zip(path[:-1],path[1:]):
   for t in np.linspace(0,1,max(2,int(np.ceil(np.max(abs(end-begin))/.005))+1)):
    sample=q.copy();sample[a.arm_indices]=(1-t)*begin+t*end;m.robot.set_qpos(sample,True);cs=m.planning_world.check_collision();pose=pose_at(sample)
    if cs:bad={'reason':'DENSE_GEOMETRIC_COLLISION','pairs':[(c.link_name1,c.link_name2) for c in cs]};break
    if not (-.15<=pose[0]<=.9 and -.4<=pose[1]<=.4 and .025<=pose[2]<=.5):bad={'reason':'PUBLIC_TCP_WORKSPACE','tcp':pose.tolist()};break
   if bad:break
   for t in np.linspace(0,1,max(1,int(np.ceil(np.max(abs(end-begin))/.10)))+1)[1:]:
    sample=q.copy();sample[a.arm_indices]=(1-t)*begin+t*end;poses.append(pose_at(sample).tolist())
  record['rejected']=bad
  if bad is None:chosen=path.tolist();goals=poses;break
 folder=w.output/f'private_verified_route_{w.group_count:03d}';folder.mkdir();(folder/'route_NOT_MODEL_INPUT.json').write_text(json.dumps({'target_unchanged':target,'dense_joint_step_rad':.005,'replay_joint_step_rad':.10,'attempts':attempts,'chosen_q_path':chosen,'tcp_waypoints':goals},indent=2))
 if chosen is None:raise RuntimeError('NO_DENSE_VERIFIED_PRIVATE_ROUTE:'+str(attempts))
 for i,pose in enumerate(goals):
  receipt=w.execute_group({side:{'pose':pose}})
  if not receipt['ok']:raise RuntimeError('PRIVATE_ROUTE_NUMERIC_REPLAY:'+str(i)+':'+str(receipt))
 return {'ok':True,'explicit_waypoints':len(goals)}
