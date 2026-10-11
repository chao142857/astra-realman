"""Narrow software tests only, no model and no physics."""
import copy,inspect,unittest
from unittest.mock import patch
from platform_v1.research import model_context as mc,pnp_proposal as p
from platform_v1.owner import Owner
from scripts.run_persistent_chunk_pair_episode import skill_actions,PROTOCOL
from scripts.structured_outputs import compile_schema,check_provider

class PairTests(unittest.TestCase):
 def fixture(self):
  o={'observation_id':'current','state':{'actual_grasp_center_world':[.33,-.02,.14],'flange_pose_world':[0,0,0,0,1,0,0],'actual_pad_gap_m':.08}}
  w={'state':{'public_plane':{'normal':[0,0,1],'offset':0},'pnp_interaction':{'current_support':True,'gripper_event':'none','status':'tabletop_target','target_geometry_id':'obj'},'entities':{'obj':{'status':'coarse','observation_id':'current','point_world_m':[.35,-.03,.02]}}}}
  return w,o,{'phase':'grasp','mode':'fine','fine_actions':[{'type':'gripper','opening':.45}]}
 def test_skill_explicit_measurement_and_bounded_primitives(self):
  w,o,r=self.fixture();before=copy.deepcopy((w,o,r));actions=skill_actions(w,o,r)
  self.assertEqual((w,o,r),before);self.assertEqual(actions[-1],r['fine_actions'][0])
  origin=o['state']['actual_grasp_center_world']
  for a in actions[:-1]:
   self.assertLessEqual(__import__('math').dist(origin,a['pose'][:3]),.04+1e-9);origin=a['pose'][:3]
  self.assertLess(__import__('math').dist(origin,[.35,-.03,.04]),1e-12);self.assertEqual(len(actions),5)
 def test_skill_no_raw_waypoint_repair(self):
  w,o,r=self.fixture();r['fine_actions'].insert(0,{'type':'move_pose','pose':[.35,-.03,.032,0,1,0,0]})
  with self.assertRaisesRegex(ValueError,'REQUEST_REQUIRED'):skill_actions(w,o,r)
 def test_skill_unknown_stale_and_domain_refuse(self):
  for field,value,error in [('current_support',False,'TABLETOP'),('gripper_event','close','TABLETOP')]:
   w,o,r=self.fixture();w['state']['pnp_interaction'][field]=value
   with self.assertRaisesRegex(ValueError,error):skill_actions(w,o,r)
  w,o,r=self.fixture();w['state']['entities']['obj']['observation_id']='old'
  with self.assertRaisesRegex(ValueError,'STALE'):skill_actions(w,o,r)
  w,o,r=self.fixture();o['state']['actual_grasp_center_world'][2]=.032
  with self.assertRaisesRegex(ValueError,'DOMAIN'):skill_actions(w,o,r)
 def test_current_projection_not_mutation_and_current_geometry_shared(self):
  state={'observation_id':'now','entities':{'obj':{'point_world_m':[1,2,3],'status':'coarse','historical_geometry':{'point_world_m':[4,5,6]},'geometry_residual':.02,'current_evidence':[]}},'pnp_interaction':{'current_xyz_m':[1,2,3],'initial_object_xyz_m':[4,5,6],'gripper_event':'none'},'history_semantics':'old'}
  world={'state':state,'query':{'omissions':[]}}
  class Store:
   pair_current_only=False
   def query_world(self,_):return copy.deepcopy(world)
   def get(self,_):return {}
   def get_world(self,_):return world
  store=Store();before=copy.deepcopy(world)
  with patch('platform_v1.research.review_contracts.planning_review_eligibility',return_value={}):
   persistent=mc.role_world_view(store,'w',p.ROLE);store.pair_current_only=True;current=mc.role_world_view(store,'w',p.ROLE)
  self.assertEqual(world,before)
  self.assertIn('historical_geometry',persistent['state']['entities']['obj']);self.assertNotIn('historical_geometry',current['state']['entities']['obj'])
  self.assertEqual(current['state']['entities']['obj']['point_world_m'],persistent['state']['entities']['obj']['point_world_m'])
  self.assertEqual(current['state']['pnp_interaction']['current_xyz_m'],[1,2,3])
 def test_owner_default_and_frozen_pair_caps(self):
  self.assertEqual(inspect.signature(Owner).parameters['execution_chunk_budget'].default,12)
  self.assertEqual(PROTOCOL['semantic_max'],1);self.assertEqual(PROTOCOL['action_max'],8)
  self.assertEqual(PROTOCOL['owner_single_action_max'],40);self.assertEqual(PROTOCOL['owner_budget']['observations'],64)
 def test_existing_schema_same_strict_compiler(self):
  schema,_=compile_schema(p.schema());check_provider(schema)
  self.assertIn('TOOL REQUEST',p.PAIR_SKILL_INSTRUCTION)
if __name__=='__main__':unittest.main()
