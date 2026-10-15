"""Current frozen four-view layout, original controller, exact public numeric executor.
Private engineering choices/witness stay in this script, never in model context.
"""
import argparse,json,traceback,numpy as np
from pathlib import Path
from dual_scene import DualScene
from initial_v1 import prepare_left
from gripper_centering import open_tcp_for_closed_center
from private_safe_route import move as routed_move
p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();w=None;r={'status':'RUNNING','model_calls':0,'controller':'original','public_executor':'closest IK + cubic interpolation; unchanged supplied goals','private_engineering_route':False,'private_engineering_candidate':'negative Y rear-facing receiving; validated in candidates_PRIVATE.json'}
try:
 w=DualScene(args.output);w.start_video();prepare_left(w)
 def move(side,xyz,quat,segmented=False):
  start=np.array(w.arms[side].state()['actual_grasp_center_world']);n=max(1,int(np.ceil(np.linalg.norm(np.array(xyz)-start)/.03))) if segmented else 1
  for f in np.linspace(0,1,n+1)[1:]:
   pose=[*((1-f)*start+f*np.array(xyz)),*quat];receipt=w.execute_group({side:{'pose':pose}})
   if not receipt['ok']:raise RuntimeError('PUBLIC_NUMERIC_REJECTION:'+side+':'+str(receipt))
 def grip(side,value,phase):
  w.phase_context=phase;receipt=w.execute_group({side:{'opening':value}});w.phase_context=None
  if not receipt['ok']:raise RuntimeError('PUBLIC_GRIPPER_REJECTION:'+str(receipt))
 w.phase_context='left_to_handoff';move('left',[.36,-.20,.102],[0,1,0,0]);w.phase_context=None
 center=w.cube.pose.p.copy();quat=[-.5,-.5,.5,-.5];right=w.arms['right'];tcp,delta=open_tcp_for_closed_center(right,center,quat,.05)
 (w.output/'private_centering_NOT_MODEL_INPUT.json').write_text(json.dumps({'source':'robot URDF FK + measured current opening; desired center chosen privately from GT by engineer','local_open_to_closed_offset_m':delta.tolist(),'orientation_wxyz':quat,'open_tcp_unchanged_by_executor':tcp.tolist()},indent=2))
 w.phase_context='right_approach';from scipy.spatial.transform import Rotation
 direction=Rotation.from_quat(np.roll(quat,-1)).apply([0,0,1])
 move('right',tcp-.07*direction,quat);move('right',tcp,quat,True);w.phase_context=None
 grip('right',.45,'right_close');w.phase_name='both_grip_settle';w.tick(150)
 if not right.bilateral_pad_contact():raise RuntimeError('RIGHT_NO_BILATERAL_CONTACT')
 grip('left',1.,'left_release');w.phase_name='right_independent_hold';w.tick(1250);w.observe(w.output/'right_held')
 if not right.bilateral_pad_contact():raise RuntimeError('RIGHT_CONTACT_LOST_DURING_HOLD')
 now=np.array(right.state()['actual_grasp_center_world']);w.phase_context='right_exit';move('right',now-.08*direction,quat,True);w.phase_context=None
 w.phase_context='left_retreat';move('left',[.22,-.18,.18],[0,1,0,0]);w.phase_context=None
 w.phase_context='right_reorient';from scipy.spatial.transform import Slerp
 fixed_tcp=np.array(right.state()['actual_grasp_center_world']);down=[0,2**-.5,-2**-.5,0];rotations=Rotation.from_quat([np.roll(quat,-1),np.roll(down,-1)]);rotation_path=Slerp([0,1],rotations)
 for f in np.linspace(0,1,7)[1:]:move('right',fixed_tcp,np.roll(rotation_path(f).as_quat(),1).tolist())
 quat=down;w.phase_context=None
 w.phase_context='right_to_place';move('right',[.52,.16,.18],quat,True);move('right',[.52,.16,.04],quat,True);w.phase_context=None
 grip('right',1.,'right_release');w.phase_name='right_release';w.tick(400);w.observe(w.output/'final')
 r['status']='EXECUTION_COMPLETE_PENDING_INDEPENDENT_SCORE'
except Exception as e:r.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());traceback.print_exc()
finally:
 if w:r.update(physics_steps=w.steps,sim_time_s=w.steps*w.dt,earliest_failed_phase=(getattr(w,'phase_context',None) or w.phase_name) if r['status']=='FAIL' else None);w.close()
 Path(args.output,'result.json').write_text(json.dumps(r,indent=2));print(json.dumps(r),flush=True)
