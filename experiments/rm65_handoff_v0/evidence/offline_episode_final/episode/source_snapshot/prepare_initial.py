"""PRIVATE expert initialization only. Ends before any right-arm approach."""
from dual_scene import RM65Scene

def prepare_left(world):
 left=world.arms['left']
 def move(xyz):
  result=RM65Scene.move_tcp(left,[*xyz,0,1,0,0])
  if not result['ok']:raise RuntimeError('INITIALIZATION_MOTION_FAILED')
 for z in [.18,.08,.04]:move([.36,-.06,z])
 world.phase_name='left_close';left.gripper(.45);world.tick(100)
 p=left.state()['actual_grasp_center_world'];move([p[0],p[1],p[2]+.14]);world.phase_name='left_hold';world.tick(300)
 if not left.bilateral_pad_contact():raise RuntimeError('LEFT_INITIAL_HOLD_FAILED')
 return world.observe(world.output/'handoff_initial')
