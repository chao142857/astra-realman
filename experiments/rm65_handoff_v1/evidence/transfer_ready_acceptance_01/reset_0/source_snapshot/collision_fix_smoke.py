"""Matched stale-vs-following FCL check and actual public numeric execution."""
import json,traceback,numpy as np,argparse
from pathlib import Path
import mplib
from mplib import PlanningWorld
from mplib.collision_detection.fcl import FCLObject
from mplib.sapien_utils.conversion import convert_object_name
from dual_scene import DualScene
from initial_v1 import prepare_left
from carry_collision import prepare
D=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();w=DualScene(args.output);r={'status':'RUNNING','model_calls':0}
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
 receipt=w.execute_group({'left':{'pose':goal}});r['numeric_receipt']=receipt;r['physical_object_pose_after']=w.cube.pose.p.tolist();w.observe(w.output/'after');before=w.steps;bad=w.execute_group({'left':{'pose':[.36,.20,.025,0,1,0,0]}});r['held_object_table_collision_negative_control']=bad;r['negative_control_zero_physics_steps']=w.steps==before
 assert not bad['ok'] and not bad['executed'] and w.steps==before
 from action_interface import context_from_observation
 c,images=context_from_observation(w.observe(w.output/'public_observation'),[]);(w.output/'public_context.json').write_text(json.dumps(c,indent=2));r['no_private_carry_data_in_model_context']=True
 r['status']='PASS' if stale and receipt['ok'] else 'FAIL'
except Exception as e:r.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());traceback.print_exc()
finally:w.close();(w.output/'result.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
