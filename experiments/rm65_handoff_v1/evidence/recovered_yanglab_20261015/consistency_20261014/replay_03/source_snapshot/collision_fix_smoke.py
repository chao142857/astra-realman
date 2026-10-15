"""Matched stale-vs-following FCL check and actual public numeric execution."""
import json,traceback,numpy as np
from pathlib import Path
import mplib
from mplib import PlanningWorld
from mplib.collision_detection.fcl import FCLObject
from mplib.sapien_utils.conversion import convert_object_name
from dual_scene import DualScene
from initial_v1 import prepare_left
from carry_collision import prepare
D=Path(__file__).parent;w=DualScene(D/'evidence/consistency_20261014/carry_smoke');r={'status':'RUNNING','model_calls':0}
try:
 w.start_video();prepare_left(w);a=w.arms['left'];goal=[.36,.20,.102,0,1,0,0];prepare(w,{'left':{'pose':goal}});plan=a.plan_tcp(goal);world=a.motion.planning_world;name=convert_object_name(w.cube);obj=world.get_object(name);original=mplib.Pose(w.cube.pose.p,w.cube.pose.q);stale=[];fixed=[]
 for i,point in enumerate(plan['position']):
  q=a.robot.get_qpos().copy();q[a.arm_indices]=point;world.get_articulation(convert_object_name(a.robot)).set_qpos(q,True)
  world.add_object(FCLObject(name,original,obj.shapes,obj.shape_poses));cs=PlanningWorld.check_collision(world)
  if cs and not stale:stale=[{'index':i,'pairs':[(c.link_name1,c.link_name2) for c in cs]}]
  cs=world.check_collision()
  if cs:fixed.append({'index':i,'pairs':[(c.link_name1,c.link_name2) for c in cs]});break
 r.update(same_target_tcp=goal,stale_first_collision=stale,following_first_collision=fixed,physical_object_pose_before=w.cube.pose.p.tolist())
 if fixed:raise RuntimeError('FOLLOWING_PREFLIGHT_COLLISION')
 receipt=w.execute_group({'left':{'pose':goal}});r['numeric_receipt']=receipt;r['physical_object_pose_after']=w.cube.pose.p.tolist();w.observe(w.output/'after');r['status']='PASS' if stale and receipt['ok'] else 'FAIL'
except Exception as e:r.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());traceback.print_exc()
finally:w.close();(w.output/'result.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
