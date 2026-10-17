import sys, unittest, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gripper_telemetry import telemetry
from gripper_position_semantics import evaluation
from parallel_history import compact, transition, ParallelHistory
from parallel_safety_pause import require_automation_ready
from unittest.mock import patch

class TelemetryTests(unittest.TestCase):
 def sample(self):
  return {'position':436,'captured_at':123,'sdk_return_code':0,
          'raw':{'dof_state':[3],'dof_err':[0],'sys_state':0,'current':[98],'speed':[0]}}
 def test_force_stop_not_fault_or_grasp_or_position_reached(self):
  e=evaluation(self.sample(),300,1)
  self.assertEqual(e['telemetry']['stop_reason'],'力控到位停止')
  self.assertTrue(e['healthy']);self.assertFalse(e['opening_reached'])
  self.assertEqual(e['grasp_confirmed'],'UNKNOWN')
 def test_missing_is_unknown_not_zero(self):
  t=telemetry({'raw':{'current':[],'dof_state':[]}})
  self.assertIsNone(t['current']);self.assertFalse(t['validity']['current'])
  self.assertEqual(t['stop_reason'],'UNKNOWN_OTHER_STATE')
 def test_history_retains_current_state_errors_and_validity(self):
  s={'gripper_state':self.sample(),'ee_pose':{'xyz_m':[0,0,.21]}}
  t=transition(13,{}, {},{'left':s},{'left':s},{'arms':{'left':{'executed_action':{'arm':{'pose':[]},'gripper':None},'between_channels':compact(s)}}})
  h=ParallelHistory();h.append(t)
  m=h.context()['transitions'][0]['measured']['left']
  self.assertEqual(m['before']['gripper_telemetry']['dof_state'],3)
  self.assertEqual(m['after']['gripper_telemetry']['current'],98)
  self.assertTrue(m['after']['gripper_telemetry']['validity']['dof_err'])
  self.assertIsNone(m['executed_commands']['gripper'])
  self.assertEqual(m['between_channels']['gripper_telemetry']['stop_reason'],'力控到位停止')
 def test_current_model_projection(self):
  from arm_stack import model_input
  from test_arm_mirror import canonical
  s=canonical('left');s['gripper_state']=self.sample()
  o={'canonical_states':{'left':s},'cameras':[],'task':'test','observation_id':'offline'}
  t=model_input(o)['robot_states']['left']['gripper']['telemetry']
  self.assertEqual(t['dof_state'],3);self.assertEqual(t['current'],98)
 def test_incident_gate_has_no_ik_bypass(self):
  with patch('parallel_safety_pause.AUTOMATION_PAUSED',True):
   with self.assertRaisesRegex(RuntimeError,'PARALLEL_AUTOMATION_PAUSED'):require_automation_ready()
 def test_operator_pause_lifted_does_not_dispatch(self):
  self.assertIsNone(require_automation_ready())
