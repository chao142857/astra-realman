"""Private offline IK diagnosis only; no right-arm execution, no model calls."""
import numpy as np,json
from pathlib import Path
from dual_scene import DualScene,RM65Scene
w=DualScene('evidence/right_ik_probe_02')
try:
 a=w.arms['left']
 for z in [.18,.08,.04]:assert RM65Scene.move_tcp(a,[.36,-.06,z,0,1,0,0])['ok']
 a.gripper(.45);w.tick(100);p=a.state()['actual_grasp_center_world'];assert RM65Scene.move_tcp(a,[p[0],p[1],p[2]+.14,0,1,0,0])['ok'];w.tick(300)
 r=w.arms['right'];r.init_planner();original=r.motion.IK
 def verbose(*args,**kwargs):return original(*args,**dict(kwargs,verbose=True))
 r.motion.IK=verbose;print('CURRENT',r.motion.check_for_self_collision(),r.motion.check_for_env_collision(),flush=True)
 print('LIMITS',r.robot.get_qlimits().tolist(),'Q',r.robot.get_qpos().tolist(),flush=True)
 from scipy.spatial.transform import Rotation
 rows=[];obj=w.cube.get_pose().p.tolist()
 for approach in ['right','front','back']:
  # local z directed toward object, local x vertical for orthogonal jaw contact.
  direction={'right':[-1,0,0],'front':[0,1,0],'back':[0,-1,0]}[approach];z=np.array(direction,float);x=np.array([0,0,1.]);y=np.cross(z,x);mat=np.column_stack([x,y,z]);q=np.roll(Rotation.from_matrix(mat).as_quat(),1).tolist()
  for distance in [.0,.03,.06]:
   pos=np.array(obj)-z*distance;print('PROBE',approach,distance,pos.tolist(),q,flush=True)
   try:plan=r.plan_tcp([*pos,*q]);status='IK_OK';n=len(plan['position'])
   except Exception as e:status=str(e);n=None
   rows.append({'approach':approach,'distance':distance,'position':pos.tolist(),'quaternion':q,'status':status,'trajectory_steps':n});print('RESULT',status,flush=True)
 (w.output/'ik_candidates.json').write_text(json.dumps(rows,indent=2))
finally:w.close()
