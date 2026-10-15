"""Private, planning-only engineering candidate selection in the unchanged scene."""
import json,numpy as np,mplib
from pathlib import Path
from scipy.spatial.transform import Rotation
from mplib.sapien_utils.conversion import convert_object_name
from dual_scene import DualScene
from initial_v1 import prepare_left
from carry_collision import prepare
from gripper_centering import gauge_offset
D=Path(__file__).parent;w=DualScene(D/'evidence/consistency_20261014/candidates');rows=[]
try:
 prepare_left(w);prepare(w);left=w.arms['left'];right=w.arms['right'];q0={s:a.robot.qpos.copy() for s,a in w.arms.items()};delta=gauge_offset(right,.05)
 def setqs(qs):
  for a in w.arms.values():
   for s,b in w.arms.items():a.motion.planning_world.get_articulation(convert_object_name(b.robot)).set_qpos(qs[s],True)
 def ik(a,tcp,quat,qs):
  setqs(qs);actual=a.links['Link6'].pose.to_transformation_matrix();local=actual[:3,:3].T@(a.pads().mean(0)-actual[:3,3]);p=np.asarray(tcp)-Rotation.from_quat(np.roll(quat,-1)).apply(local);m=a.motion;goal=m._transform_goal_to_wrt_base(mplib.Pose(p,quat));mask=np.ones(len(qs[a.side]),dtype=bool);mask[a.arm_indices]=False;status,q=m.IK(goal,qs[a.side],mask=mask,return_closest=True)
  if status!='Success':raise ValueError('IK_'+a.side)
  return q
 def pathcheck(start,end,moving):
  for t in np.linspace(0,1,181):
   qs={s:start[s].copy() for s in start};qs[moving]=(1-t)*start[moving]+t*end[moving];setqs(qs)
   for a in w.arms.values():
    cs=a.motion.planning_world.check_collision()
    if cs:return [(c.link_name1,c.link_name2) for c in cs]
  return None
 for y in [-.20,.20,-.16,.16,-.24,.24]:
  for x,z in [(.36,.10),(.32,.10),(.40,.10),(.36,.14)]:
   for quat in [[-.5,.5,.5,.5],[.5,-.5,.5,.5],[-.5,-.5,.5,-.5],[.5,.5,.5,-.5]]:
    row={'left_tcp':[x,y,z+.002,0,1,0,0],'right_quaternion':quat};rows.append(row)
    try:
     ql=ik(left,row['left_tcp'][:3],row['left_tcp'][3:],q0);qls={**q0,'left':ql};bad=pathcheck(q0,qls,'left')
     if bad:raise ValueError('LEFT_PATH:'+str(bad))
     setqs(qls);left.motion.carry_collision_update();obj=left.motion.planning_world.get_object(convert_object_name(w.cube)).pose;center=np.array(obj.p);rR=Rotation.from_quat(np.roll(quat,-1));tcp=center-rR.apply(delta);approach=tcp-rR.apply([0,0,.07]);row.update(right_open_tcp=[*tcp,*quat],right_approach=[*approach,*quat])
     qr=ik(right,approach,quat,qls);qrs={**qls,'right':qr};bad=pathcheck(qls,qrs,'right')
     if bad:raise ValueError('RIGHT_APPROACH_PATH:'+str(bad))
     qrf=ik(right,tcp,quat,qrs);qf={**qrs,'right':qrf};bad=pathcheck(qrs,qf,'right')
     if bad:raise ValueError('RIGHT_FINAL_PATH:'+str(bad))
     row['status']='CANDIDATE_ENDPOINT_AND_181_SAMPLES_PASS_NOT_PHYSICAL';print('CANDIDATE',row,flush=True)
    except Exception as e:row['status']=str(e)
 (w.output/'candidates_PRIVATE.json').write_text(json.dumps(rows,indent=2));print('VALID',sum(x['status'].startswith('CANDIDATE') for x in rows),flush=True)
finally:w.close()
