import sys,copy,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parallel_history import ParallelHistory,transition
from gripper_position_semantics import evaluation
class HistoryTests(unittest.TestCase):
 def test_bounded_isolated_and_copied(self):
  h=ParallelHistory()
  for i in range(12):h.append({'step':i})
  c=h.context();self.assertEqual([t['step'] for t in c['transitions']],list(range(4,12)))
  c['transitions'][0]['step']=99;self.assertEqual(h.context()['transitions'][0]['step'],4)
  self.assertEqual(ParallelHistory().context()['completed_count'],0)
 def test_measured_not_grasp(self):
  b={'left':{'ee_pose':{'xyz_m':[0,0,.22]},'gripper_state':{'position':399}}};a=copy.deepcopy(b);a['left']['ee_pose']['xyz_m'][2]=.245
  t=transition('26',{}, {'next_action_intent':'试提'},b,a,{'status':'COMPLETED'})
  self.assertAlmostEqual(t['measured']['left']['tcp_delta_m'][2],.025)
  self.assertEqual(t['measured']['left']['grasp_confirmed'],'UNKNOWN')
  self.assertEqual(t['model_judgment']['next_action_intent'],'试提')
 def test_quantization_not_force(self):
  g={'position':399,'raw':{'speed':[0],'sys_state':0,'dof_err':[0]}}
  self.assertTrue(evaluation(g,400,1)['opening_reached'])
  self.assertEqual(evaluation(g,400,1)['grasp_confirmed'],'UNKNOWN')
  self.assertFalse(evaluation(g,401,1)['opening_reached'])
  g['raw']['speed']=[1];self.assertFalse(evaluation(g,400,1)['opening_reached'])
  g['raw']['speed']=[0];g['raw']['dof_err']=[1];self.assertFalse(evaluation(g,400,1)['opening_reached'])
