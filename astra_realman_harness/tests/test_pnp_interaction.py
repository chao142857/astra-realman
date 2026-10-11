"""Explicit synthetic evidence contracts, never a physics success claim."""
import copy,unittest
from unittest.mock import patch
from platform_v1.research.pnp_support import augment
class InteractionTests(unittest.TestCase):
 def setup_state(self):
  e={'status':'coarse','temporal_association':{'status':'unique_current_match'},'point_world_m':[.3,0,.025]}
  state={'entities':{'x':e}};reference={'entities':copy.deepcopy(state['entities']),'task_target_geometry_id':'x'}
  obs={'captured_monotonic':1.,'observation_id':'SYNTHETIC:1','state':{'flange_pose_world':[.3,0,.2,1,0,0,0],'actual_pad_gap_m':.08}}
  return state,reference,obs
 def call(self,s,r,old,cur,fb):
  with patch('platform_v1.research.pnp_support.destination',return_value={'status':'unknown','source':'SYNTHETIC_TEST'}):augment(s,r,old,cur,{}, {},None,fb)
  return s['pnp_interaction']
 def test_close_not_held(self):
  s,r,o=self.setup_state();v=self.call(s,r,o,o,{'actions':[{'completed':True,'action':{'type':'gripper','opening':0.}}]})
  self.assertEqual(v['status'],'held_candidate');self.assertFalse(v['carrying_seen']);self.assertTrue(v['close_is_not_held'])
 def test_measured_carry_not_rejected_as_static_drift(self):
  s,r,o=self.setup_state();v=self.call(s,r,o,o,{'actions':[{'completed':True,'action':{'type':'gripper','opening':0.}}]})
  r['pnp_interaction']=v;s['entities']['x']['point_world_m']=[.4,0,.1]
  new=copy.deepcopy(o);new['captured_monotonic']=3;new['state']['flange_pose_world'][:3]=[.4,0,.275]
  v=self.call(s,r,o,new,{'actions':[]});self.assertEqual(v['status'],'carrying_visual_hypothesis');self.assertGreater(v['current_position_shift_m'],.03)
  self.assertLess(v['current_visual_vs_carry_prediction_residual_m'],1e-8)
 def test_fk_prediction_does_not_invent_current_measurement(self):
  s,r,o=self.setup_state();r['pnp_interaction']={'gripper_event':'close','carry_anchor_flange_local_m':[0,0,-.175]}
  r['object_config']={'tracker':{},'geometry':{}};r['entities']['x']['historical_geometry']={};s['entities']['x']['status']='unknown'
  with patch('platform_v1.research.pnp_support.rw.calibrated_cameras',return_value=([],[])),patch('platform_v1.research.pnp_support.rw.measure_entity',return_value={'status':'unknown','point_world_m':None,'bounds_world_m':None,'current_evidence':[],'reason':'NO_CURRENT_SUPPORT'}):
   v=self.call(s,r,o,o,{'actions':[]})
  self.assertEqual(v['status'],'unknown');self.assertIsNone(v['current_xyz_m']);self.assertIsNotNone(v['FK_carry_prediction_world_m'])
