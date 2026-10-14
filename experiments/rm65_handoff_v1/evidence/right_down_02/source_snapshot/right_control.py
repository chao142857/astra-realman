"""Private minimal physical control: right-only grasp, hold, optional wrist reorientation."""
import argparse,json,traceback,numpy as np
from scipy.spatial.transform import Rotation,Slerp
from dual_scene import DualScene,RM65Scene,LAYOUT
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--rotate',action='store_true');a=p.parse_args();w=DualScene(a.output);result={'real_model_calls':0,'controller':'original','status':'RUNNING'}
def move(side,xyz,q):
 w.phase_name='move_'+side
 r=RM65Scene.move_tcp(w.arms[side],[*xyz,*q])
 if not r['ok']:raise RuntimeError('MOTION_FAILED:'+side+':'+str(r.get('planner_status')))
try:
 w.start_video();w.observe(w.output/'initial')
 move('left',[.25,-.18,.18],[0,1,0,0]);r=w.arms['right'];xy=LAYOUT['cube_initial_xyz'][:2];down=[0,0,1,0]
 for z in [.18,.08,.04]:move('right',[*xy,z],down)
 w.phase_name='right_close';r.gripper(.45);w.tick(100)
 tcp=r.state()['actual_grasp_center_world'];move('right',[tcp[0],tcp[1],tcp[2]+.14],down)
 w.phase_name='right_down_hold_5s';start=w.steps;w.tick(1250);w.observe(w.output/'down_held');result['down_hold_final_contact']=r.bilateral_pad_contact();result['down_hold_object_z']=float(w.cube.get_pose().p[2])
 if not result['down_hold_final_contact'] or result['down_hold_object_z']<.08:raise RuntimeError('RIGHT_DOWN_NOT_HELD')
 if a.rotate:
  q0=Rotation.from_quat(np.roll(down,-1));q1=Rotation.from_quat(np.roll([-.5,.5,.5,.5],-1));slerp=Slerp([0,1],Rotation.from_quat([q0.as_quat(),q1.as_quat()]))
  center=r.state()['actual_grasp_center_world']
  for t in np.linspace(0,1,7)[1:]:move('right',center,np.roll(slerp(t).as_quat(),1).tolist())
  w.phase_name='right_sideways_hold_5s';w.tick(1250);w.observe(w.output/'sideways_held');result['side_hold_final_contact']=r.bilateral_pad_contact()
  if not result['side_hold_final_contact']:raise RuntimeError('RIGHT_SIDE_NOT_HELD')
 result['status']='PASS'
except Exception as e:result.update(status='FAIL',error=repr(e),phase=w.phase_name,traceback=traceback.format_exc());traceback.print_exc()
finally:
 result.update(step=w.steps,simulation_time_s=w.steps*w.dt);w.close();(w.output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
