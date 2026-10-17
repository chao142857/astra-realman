import test_arm_mirror as fixtures
from test_arm_mirror import Stop
from left_executor import RealArmExecutor
from exact_target_feasibility import check_exact_target
class Execution(fixtures.Tests):
 def test_one_count_skip_preserves_arm_motion(self):
  a=self.proposal('left');a['gripper_opening']=.4
  self.states['left']['gripper_state']['position']=399
  self.states['left']['gripper_state']['raw']['pos']=[399]
  step=self.root/'tolerance';step.mkdir();obs=self.capture(self.root/'tolerance-before')
  ex=RealArmExecutor(self.session,self.capture,Stop(),step,gripper_factory=self.Grip,arm_id='left',gripper_tolerance_raw=1)
  result=ex.execute(a,obs,feasibility=check_exact_target(self.session,a,obs,allow_shared_session=True))
  self.assertEqual(len(self.robots['left'].moves),1);self.assertEqual(self.grip_calls,[])
  self.assertEqual(result['gripper_skip_reason'],'OPENING_WITHIN_TOLERANCE_STATIONARY')
  self.assertEqual(result['hardware_commands_sent'],1)
