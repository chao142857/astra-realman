"""Robot CAD kinematics, not a task skill. Engineering script chooses the desired center.
The public executor never calls this to alter a model goal.
"""
import numpy as np
from scipy.spatial.transform import Rotation

def gauge_offset(arm,gap_m):
 m=arm.motion;idx=m.link_name_2_idx[arm.prefix+'Link6'];start=arm.robot.get_qpos().copy()
 def measure(master):
  q=start.copy();q[arm.master]=master
  for name,(parent,mult,off) in arm.mimics.items():q[arm.names.index(name)]=q[arm.names.index(parent)]*mult+off
  m.pinocchio_model.compute_forward_kinematics(q);fl=m.pinocchio_model.get_link_pose(idx).to_transformation_matrix();pts=[]
  for name,vs in arm.pad_vertices.items():
   t=m.pinocchio_model.get_link_pose(m.link_name_2_idx[arm.prefix+name]).to_transformation_matrix();pts.append((vs@t[:3,:3].T+t[:3,3]).mean(0))
  return float(np.linalg.norm(pts[0]-pts[1])),fl[:3,:3].T@(np.mean(pts,axis=0)-fl[:3,3])
 lo,hi=-.91,0
 if not measure(lo)[0]<=gap_m<=measure(hi)[0]:raise ValueError('GAUGE_OUTSIDE_GRIPPER_RANGE')
 for _ in range(40):
  mid=(lo+hi)/2
  if measure(mid)[0]<gap_m:lo=mid
  else:hi=mid
 _,closed=measure((lo+hi)/2)
 actual=arm.links['Link6'].pose.to_transformation_matrix();opened=actual[:3,:3].T@(arm.pads().mean(0)-actual[:3,3])
 return closed-opened

def open_tcp_for_closed_center(arm,center,quaternion_wxyz,gap_m):
 delta=gauge_offset(arm,gap_m);return np.asarray(center)-Rotation.from_quat(np.roll(quaternion_wxyz,-1)).apply(delta),delta
