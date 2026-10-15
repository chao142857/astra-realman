"""PRIVATE initialization. No receiving or handoff targets passed to model."""
from dual_scene import RM65Scene,LAYOUT

def expert_move(w,side,xyz,q):
 w.phase_name='expert_move_'+side
 r=RM65Scene.move_tcp(w.arms[side],[*xyz,*q])
 if not r['ok']:raise RuntimeError('EXPERT_MOTION_FAILED:'+side+':'+str(r.get('planner_status')))
 return r

def prepare_left(w):
 expert_move(w,'right',[.55,.18,.18],[0,0,1,0])
 xy=LAYOUT['cube_initial_xyz'][:2]
 for z in [.18,.08,.04]:expert_move(w,'left',[*xy,z],[0,1,0,0])
 w.phase_name='left_close';w.arms['left'].gripper(.45);w.tick(100)
 p=w.arms['left'].state()['actual_grasp_center_world'];expert_move(w,'left',[p[0],p[1],p[2]+.14],[0,1,0,0]);w.phase_name='left_hold';w.tick(300)
 if not w.arms['left'].bilateral_pad_contact():raise RuntimeError('LEFT_INITIAL_HOLD_FAILED')
 return w.observe(w.output/'handoff_initial')
