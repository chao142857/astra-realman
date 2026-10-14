"""Private GT engineering baseline using the EXACT public numeric executor after initialization."""
import argparse,json,traceback
from pathlib import Path
import numpy as np
from dual_scene import DualScene,RM65Scene
from initial_v1 import prepare_left
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--hold-only',action='store_true');p.add_argument('--expert',action='store_true');a=p.parse_args();w=None;r={'status':'RUNNING','model_calls':0,'post_initialization_executor':'public closest IK/cubic interpolation; explicit private waypoints; no OMPL'}
try:
 r['post_initialization_executor']='original OMPL expert with explicit segments' if a.expert else r['post_initialization_executor']
 w=DualScene(a.output);w.start_video();w.observe(w.output/'initial_observation');prepare_left(w)
 def move(side,xyz,q,segments=False):
  start=np.array(w.arms[side].state()['actual_grasp_center_world']);n=max(1,int(np.ceil(np.linalg.norm(np.array(xyz)-start)/.012))) if segments else 1
  for t in np.linspace(0,1,n+1)[1:]:
   pose=[*((1-t)*start+t*np.array(xyz)),*q]
   out=RM65Scene.move_tcp(w.arms[side],pose) if a.expert else w.execute_group({side:{'pose':pose}})
   if not out['ok']:raise RuntimeError('NUMERIC_REJECTED:'+side+':'+str(out))
 def grip(side,value):
  out=w.execute_group({side:{'opening':value}})
  if not out['ok']:raise RuntimeError('GRIPPER_REJECTED:'+str(out))
 move('left',[.36,.20,.102],[0,1,0,0],True)
 obj=w.cube.get_pose().p.copy();obj[1]-=.01369781;q=[-.5,.5,.5,.5]
 from private_rrt_waypoints import move as private_move
 private_move(w,'right',[*(obj+np.array([0,-.07,0])),*q]);move('right',obj,q,True)
 grip('right',.45);w.tick(150)
 grip('left',1.);w.phase_name='right_independent_hold';w.tick(1250)
 if not w.arms['right'].bilateral_pad_contact():raise RuntimeError('RIGHT_NOT_HOLDING')
 w.observe(w.output/'held')
 if not a.hold_only:
  current=np.array(w.arms['right'].state()['actual_grasp_center_world'])
  move('right',current+[0,-.08,0],q,True)
  move('left',[.27,-.12,.22],[0,1,0,0],True)
  move('right',[.52,.16,.10],q,True);move('right',[.52,.16,.055],q,True)
  w.phase_context='right_release';grip('right',1.);w.phase_context=None;w.phase_name='right_release';w.tick(400)
  w.observe(w.output/'final_observation')
 r['status']='PASS_HOLD_ONLY' if a.hold_only else 'EXECUTION_COMPLETE_PENDING_INDEPENDENT_SCORE'
except BaseException as e:r.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());traceback.print_exc()
finally:
 if w:r.update(steps=w.steps);w.close()
 Path(a.output,'result.json').write_text(json.dumps(r,indent=2));print(r,flush=True)
