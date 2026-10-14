import json,numpy as np,mplib
from dual_scene import DualScene
from scipy.spatial.transform import Rotation
w=DualScene('evidence/ik_raw_diagnosis_01');rows=[]
try:
 a=w.arms['right'];a.init_planner();m=a.motion;q=a.robot.get_qpos();mask=np.ones(len(q),bool);mask[a.arm_indices]=False;idx=m.link_name_2_idx[m.move_group]
 print('JOINTS',a.names,'MOVE',m.move_group_joint_indices,'BASE',m.robot.get_base_pose(),flush=True)
 for p,quat in [([.40,-.06,.164],[.707106781,0,-.707106781,0]),([.4,-.06,.164],[0,1,0,0]),([.4,-.06,.164],[.5,.5,-.5,.5])]:
  f=a.links['Link6'].get_pose().to_transformation_matrix();local=f[:3,:3].T@(a.pads().mean(0)-f[:3,3]);fp=np.array(p)-Rotation.from_quat(np.roll(quat,-1)).as_matrix()@local;goal=m._transform_goal_to_wrt_base(mplib.Pose(fp,quat));results=[]
  for i in range(30):
   start=q.copy() if i==0 else m.pinocchio_model.get_random_configuration();start[mask]=q[mask]
   sol,ok,err=m.pinocchio_model.compute_IK_CLIK(idx,goal,start,mask)
   raw=sol.copy();limits=m.wrap_joint_limit(sol);m.pinocchio_model.compute_forward_kinematics(sol);dist=goal.distance(m.pinocchio_model.get_link_pose(idx));results.append({'ok':bool(ok),'limits':bool(limits),'error':np.asarray(err).tolist(),'distance':float(dist),'raw':raw.tolist(),'wrapped':sol.tolist()})
  row={'tcp':p,'quat':quat,'goal_base':str(goal),'results':results};rows.append(row);print(json.dumps(row),flush=True)
 (w.output/'diagnosis.json').write_text(json.dumps(rows,indent=2))
finally:w.close()
