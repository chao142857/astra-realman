"""Robot CAD only: opening-dependent pad centre. No object pose or contact reads."""
import json,numpy as np
from dual_scene import DualScene
w=DualScene('evidence/gripper_kinematics_01')
try:
 a=w.arms['right'];a.init_planner();m=a.motion;rows=[]
 def measure(master):
  q=a.robot.get_qpos().copy();q[a.master]=master
  for name,(parent,mul,off) in a.mimics.items():q[a.names.index(name)]=q[a.names.index(parent)]*mul+off
  m.pinocchio_model.compute_forward_kinematics(q)
  poses={name:m.pinocchio_model.get_link_pose(m.link_name_2_idx[a.prefix+name]).to_transformation_matrix() for name in ['Link6',*a.pad_vertices]}
  pts=[]
  for name,v in a.pad_vertices.items():t=poses[name];pts.append((v@t[:3,:3].T+t[:3,3]).mean(0))
  flange=poses['Link6'];local=flange[:3,:3].T@(np.mean(pts,axis=0)-flange[:3,3]);return {'master_rad':master,'gap_m':float(np.linalg.norm(pts[0]-pts[1])),'pad_center_in_Link6_m':local.tolist()}
 for master in [0,-.2,-.3,-.4,-.44,-.442,-.45,-.5]:rows.append(measure(master))
 # Solve gap=50mm from CAD alone, as a separately labelled engineering gauge.
 lo,hi=-.8,0.
 for _ in range(40):
  mid=(lo+hi)/2
  if measure(mid)['gap_m']<.05:lo=mid
  else:hi=mid
 closed=measure((lo+hi)/2);opened=measure(0);out={'source':'URDF/mesh robot kinematics only','samples':rows,'gauge_gap_50mm':closed,'advance_open_to_50mm_m':(np.array(closed['pad_center_in_Link6_m'])-opened['pad_center_in_Link6_m']).tolist()}
 (w.output/'robot_only_kinematics.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
finally:w.close()
