"""Run-scoped contracts on frozen REAL input with FAKE answers; zero dispatch."""
import copy,unittest
from unittest.mock import patch
from test_action_proposal import ProposalTests
from platform_v1.research import pnp_proposal as p
from platform_v1.research import chunk_plan
from platform_v1.research.supervisor import Supervisor
from scripts.structured_outputs import compile_schema,check_provider

class PnPTests(ProposalTests):
 def request(self):return p.request(self.w,self.o)
 def start(self):
  self.b.pnp_episode_authorization=self.store.episode_id
  return super().start()
 def answer(self,row,decision='planned'):
  row['proposal_host']=row['pnp_proposal_host'];a=super().answer(row,decision);del row['proposal_host']
  a['result'].update(version=p.VERSION,mode='coarse',phase='approach',fine_actions=[])
  return a
 def test_pnp_coarse_broker_preserves_four_actions(self):
  row=self.start();a=self.answer(row);before=copy.deepcopy(a);self.finish(row,a)
  self.assertEqual(row['status'],'READY',row['error']);d=row['pnp_candidate']
  self.assertEqual(d['actions'],[{'type':'move_pose','pose':x['pose']} for x in before['result']['proposal']['waypoints']])
  self.assertEqual(d['plan']['m'],1);self.assertIsNone(self.b.action_ready);self.assertFalse(row['grants_execution'])
 def test_pnp_fine_small_move_and_close_boundary(self):
  row=self.start();a=self.answer(row);origin=row['pnp_proposal_host']['plan_fields']['origin_pose_world']
  actions=[{'type':'move_pose','pose':[origin[0],origin[1],origin[2]-.001,*origin[3:]]},{'type':'gripper','opening':0.}]
  a['result'].update(mode='fine',phase='grasp',proposal=None,fine_actions=actions);self.finish(row,a)
  self.assertEqual(row['status'],'READY',row['error']);self.assertEqual(row['pnp_candidate']['actions'],actions)
 def test_pnp_postgripper_future_rejected(self):
  row=self.start();a=self.answer(row);origin=row['pnp_proposal_host']['plan_fields']['origin_pose_world']
  a['result'].update(mode='fine',phase='grasp',proposal=None,fine_actions=[{'type':'gripper','opening':0.},{'type':'move_pose','pose':origin}]);self.finish(row,a)
  self.assertEqual(row['status'],'FAILED');self.assertIn('GRIPPER_BARRIER',row['error'])
 def test_pnp_null_decisions(self):
  for decision in ('refused','need_more_evidence','finished'):
   row=self.start();a=self.answer(row,'refused');a['result']['decision']=decision;self.finish(row,a)
   self.assertEqual(row['status'],'READY',row['error']);self.assertEqual(row['pnp_candidate']['actions'],[])
 def test_pnp_host_override_rejected(self):
  row=self.start();a=self.answer(row);a['result']['origin_pose_world']=[0]*7;self.finish(row,a);self.assertEqual(row['status'],'FAILED')
 def test_pnp_schema(self):
  s,a=compile_schema(p.schema());check_provider(s)
 def test_pnp_stale_epoch_rejected(self):
  row=self.start();a=self.answer(row);self.epoch+=1;self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.assertIn('STALE',row['error'])
 def test_pnp_auth_required(self):
  with self.assertRaisesRegex(ValueError,'PNP_EXPLICIT_EPISODE_AUTH'):super().start()
