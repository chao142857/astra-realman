"""Private reference geometry only. No simulator calls or public target correction."""
import numpy as np

def tcp_arc(start_flange,goal_tcp,base_xy,rotation,tcp_local,segments=12):
 start=np.asarray(start_flange,float);goal=np.asarray(goal_tcp,float)-rotation@tcp_local;base=np.asarray(base_xy,float)
 v0=start[:2]-base;v1=goal[:2]-base;r0,r1=np.linalg.norm(v0),np.linalg.norm(v1);t0,t1=np.arctan2(v0[1],v0[0]),np.arctan2(v1[1],v1[0]);out=[]
 for f in np.linspace(0,1,segments+1):
  radius=(1-f)*r0+f*r1;theta=(1-f)*t0+f*t1;flange=np.r_[base+radius*np.array([np.cos(theta),np.sin(theta)]),(1-f)*start[2]+f*goal[2]]
  out.append((flange+rotation@tcp_local).tolist())
 assert np.allclose(out[-1],goal_tcp,atol=1e-12)
 assert np.allclose(np.array(out[0])-rotation@tcp_local,start,atol=1e-12)
 return out
