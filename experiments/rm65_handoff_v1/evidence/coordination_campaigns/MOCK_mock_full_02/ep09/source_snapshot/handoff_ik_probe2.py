"""Private engineering reachability, never imported by model loop."""
import json,numpy as np
from dual_scene import DualScene
from initial_v1 import prepare_left
from mplib.sapien_utils.conversion import convert_object_name
w=DualScene('evidence/handoff_reachability_02');rows=[]
try:
 prepare_left(w)
 for x,y,z in [(x,y,z) for z in [.16,.20,.25] for x,y in [(.36,0),(.36,.08),(.4,0),(.32,0)]]:
  poses={'left':[x,y,z+.002,0,2**-.5,2**-.5,0],'right':[x+.0136978,y,z,2**-.5,0,-2**-.5,0]};row={'object_center':[x,y,z],'poses':poses}
  try:
   plans={s:w.arms[s].plan_tcp(p) for s,p in poses.items()};qs={s:a.robot.get_qpos().copy() for s,a in w.arms.items()}
   for s in qs:qs[s][w.arms[s].arm_indices]=plans[s]['position'][-1]
   for s,a in w.arms.items():
    for other,oa in w.arms.items():a.motion.planning_world.get_articulation(convert_object_name(oa.robot)).set_qpos(qs[other],full=True)
    if a.motion.check_for_self_collision(qs[s]) or a.motion.check_for_env_collision(qs[s]):raise ValueError('COMBINED_COLLISION')
   row['status']='FEASIBLE_ENDPOINTS_ONLY'
  except Exception as e:row['status']=str(e)
  rows.append(row);print(row,flush=True)
 (w.output/'candidate_endpoints.json').write_text(json.dumps(rows,indent=2))
finally:w.close()
