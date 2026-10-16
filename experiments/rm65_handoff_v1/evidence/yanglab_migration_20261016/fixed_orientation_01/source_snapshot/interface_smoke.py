"""Real shared PhysX execution of numeric commands; NO model, NOT a handoff proof."""
import argparse,json,traceback
from pathlib import Path
from dual_scene import DualScene
from action_interface import execute_action,context_from_observation
p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();w=DualScene(a.output);result={'model_calls':0,'handoff_claim':False}
try:
 w.start_video();obs=w.observe(w.output/'observation_0');c,images=context_from_observation(obs,[]);(w.output/'public_context.json').write_text(json.dumps(c,indent=2))
 group={'done':False,'execution':'parallel','actions':[{'arm':s,'kind':'gripper','pose_world_wxyz':None,'opening_fraction':1.} for s in ['left','right']]}
 result['parallel_gripper']=execute_action(w,group)
 if not result['parallel_gripper']['ok']:raise RuntimeError('PARALLEL_GRIPPER_REJECTED')
 move={'done':False,'execution':'parallel','actions':[]}
 for side in ['left','right']:
  state=w.arms[side].state();xyz=state['actual_grasp_center_world'].copy();xyz[2]+=.005
  move['actions'].append({'arm':side,'kind':'tcp','pose_world_wxyz':[*xyz,*state['flange_pose_world'][3:]],'opening_fraction':None})
 result['parallel_numeric_tcp']=execute_action(w,move)
 if not result['parallel_numeric_tcp']['ok']:raise RuntimeError('PARALLEL_TCP_REJECTED')
 before=w.steps;bad={'done':False,'execution':'parallel','actions':[{'arm':'left','kind':'tcp','pose_world_wxyz':[9,9,9,1,0,0,0],'opening_fraction':None},{'arm':'right','kind':'gripper','pose_world_wxyz':None,'opening_fraction':0.}]}
 result['invalid_group']=execute_action(w,bad);assert not result['invalid_group']['executed'] and w.steps==before
 w.observe(w.output/'observation_1');result['status']='PASS'
except Exception as e:result.update(status='FAIL',error=repr(e),traceback=traceback.format_exc())
finally:w.close();(a.output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
