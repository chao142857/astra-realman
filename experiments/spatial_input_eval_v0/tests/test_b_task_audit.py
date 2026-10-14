"""Offline tests against frozen observations and original geometry functions."""
import copy,json,sys,unittest
from pathlib import Path
MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'lab'),str(MODULE/'lab/b_task_audit')]
import audit
from spatial_eval.geometry import swept_collision,contains
from pilot02_contract import score
class TaskAuditTests(unittest.TestCase):
 def load(self,scene):
  root=MODULE/'evidence/pilot02_preview_20261013/suite_v2'/scene
  c=audit.read(root/'model_inputs/RGB_MULTI_VIEW/context.json');b=audit.read(MODULE/'evidence/b_prototype_20261013/inputs_B'/scene/'geometry.json');t=audit.read(root/'snapshot.json')['ground_truth'];w=audit.read(root/'private/design_and_controls.json')['witness']
  return c,b,t,w
 def test_original_functions_are_used(self):
  self.assertIs(audit.swept_collision,swept_collision);self.assertIs(audit.contains,contains);self.assertIs(audit.score,score)
 def test_B_environment_is_public_only_and_nonmutating(self):
  c,b,t,w=self.load('p02_b_open_minus');before=copy.deepcopy((c,b));e=audit.b_environment(c,b)['ground_truth']
  self.assertEqual((c,b),before);self.assertEqual(e['objects'],b['objects']);self.assertEqual(e['obstacles'],b['obstacles']);self.assertEqual(e['regions'],audit.public_regions(c));self.assertNotEqual(e['obstacles'],t['obstacles'])
 def test_no_fallback_if_public_volume_missing(self):
  c,b,t,w=self.load('p02_b_open_minus');c['task']['instruction']='No public volumes here'
  with self.assertRaises(AssertionError):audit.b_environment(c,b)
 def test_yaw_clearance_and_ablation(self):
  for scene,mm in [('p02_c_slot_030',1.1802219392),('p02_c_slot_120',.79546420986)]:
   c,b,t,w=self.load(scene);envs=audit.environments(c,b,t)
   self.assertTrue(audit.result(envs['GT'],c,w)['success']);self.assertTrue(audit.result(envs['B_target_only'],c,w)['success']);self.assertFalse(audit.result(envs['B_full'],c,w)['success']);self.assertTrue(audit.result(envs['B_full'],c,w,0)['success'])
   bracket=audit.margins(envs['B_full'],c,w)['placement'];self.assertAlmostEqual(bracket['noncollision_lower_m']*1000,mm,places=7)
   self.assertTrue(audit.result(envs['B_full'],c,w,bracket['noncollision_lower_m']-1e-8)['success']);self.assertFalse(audit.result(envs['B_full'],c,w,bracket['collision_upper_m']+1e-8)['success'])
 def test_archived_real_outputs_GT_stays_equal_to_original(self):
  root=MODULE/'evidence/pilot02_runs/pilot02_continuation_01';ledger=audit.read(root/'ledger.json')
  for run in ledger['runs']:
   c,b,t,_=self.load(run['job']['scene_id_private_catalog_only']);pred=audit.parse_prediction((root/run['artifact']/'raw.txt').read_text(),c['task']);a=audit.result({'ground_truth':t},c,pred)
   self.assertEqual(a,audit.read(root/run['artifact']/'assessment.json')['evaluation'])
 def test_B_030_existence_certificate(self):
  c,b,t,w=self.load('p02_c_slot_030');cert=audit.read(MODULE/'evidence/b_task_audit_20261014/exploratory_followup/p02_c_slot_030/summary.json')['first_B_feasible_certificate']['prediction']
  for env in [audit.b_environment(c,b),{'ground_truth':t}]:self.assertTrue(audit.result(env,c,cert)['success'])
 def test_detour_rejection_is_target_height_not_path_collision(self):
  c,b,t,w=self.load('p02_b_open_minus');w['waypoints_m']=[[.18,-.2,.06],[.76,-.2,.06],[.76,0,.12]];envs=audit.environments(c,b,t)
  self.assertTrue(audit.result(envs['GT'],c,w)['success']);self.assertTrue(audit.result(envs['B_obstacles_only'],c,w)['success'])
  for key in ['B_target_only','B_full']:self.assertEqual(audit.result(envs[key],c,w)['error_types'],['path_in_workspace'])
 def test_metrics_have_explicit_conditional_denominators(self):
  r=audit.confusion([(True,True),(True,False),(False,True),(False,False)])
  self.assertEqual(r['retention_given_GT_feasible'],.5);self.assertEqual(r['false_rejection_given_GT_feasible'],.5);self.assertEqual(r['false_acceptance_given_GT_infeasible'],.5)
if __name__=='__main__':unittest.main()
