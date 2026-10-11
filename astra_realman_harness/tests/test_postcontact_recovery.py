"""Archived development data + labeled software faults; no model/physics."""
import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scripts.diagnose_postcontact_offline import load,ROOT
from platform_v1.research.pnp_support import local_target_support
from platform_v1.research import rgbd_world as rw,pnp_proposal as pp
from scripts.run_persistent_chunk_pair_episode import no_action_recovery_route
from test_full_pnp_connection import PnPTests

class LocalSupportTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.inputs={name:load(name) for name in ('current_rgbd_h4','persistent_wh_h4')}
 def sample(self,name='current_rgbd_h4'):
  w,p,c,im,d,fb=self.inputs[name];return copy.deepcopy(w),copy.deepcopy(p),copy.deepcopy(c),im,copy.deepcopy(d),copy.deepcopy(fb)
 def call(self,w,c,im,d):return local_target_support(w['state'],c,im(c['observation_id']),d,im)
 def test_both_archives_current_support_close_not_held(self):
  for name in self.inputs:
   w,p,c,im,d,fb=self.sample(name);before=copy.deepcopy(w)
   s=rw.update_geometry_first(w['state'],p,c,im(c['observation_id']),d,im,fb['completed_monotonic'],fb,w['state']['geometry_update_config'])
   x=s['pnp_interaction'];self.assertTrue(x['current_support']);self.assertEqual(x['status'],'held_candidate');self.assertFalse(x['carrying_seen']);self.assertEqual(s['geometry_quality']['task_usable'],'unknown')
   self.assertTrue(x['carry_anchor_initialized_this_update']);self.assertEqual(x['carry_residual_scope'],'anchor_definition_not_hold_verification')
   target=s['entities'][s['task_target_geometry_id']];self.assertEqual(target['observation_id'],c['observation_id']);self.assertEqual(target['semantic_evidence_id'],w['state']['semantic_evidence_id']);self.assertEqual(w,before)
   self.assertTrue(any(e.get('candidate_type')=='robot_linked_surface' and e['status']=='unknown' for e in s['entities'].values()))
 def test_depth_absent_not_historical_measurement(self):
  w,p,c,im,d,fb=self.sample()
  for cam,(z,v,m) in d.items():v[:]=False
  x=self.call(w,c,im,d);self.assertEqual(x['support_status'],'unknown');self.assertIsNone(x['point_world_m']);self.assertEqual(x['partial_current_surface_cloud'],[])
 def test_one_view_partial_separate_from_unknown(self):
  w,p,c,im,d,fb=self.sample()
  for cam,(z,v,m) in d.items():
   if cam!='fixed':v[:]=False
  x=self.call(w,c,im,d);self.assertEqual(x['support_status'],'partial_current_surface');self.assertIsNone(x['point_world_m']);self.assertGreater(len(x['partial_current_surface_cloud']),0)
 def test_ambiguous_track_no_identity_promotion(self):
  w,p,c,im,d,fb=self.sample();original=rw.track_view
  def track(*a):
   return {'mask':None,'association':'unknown','reason':'AMBIGUOUS_TEMPORAL_ASSOCIATION'} if a[3]=='wrist' else original(*a)
  with patch.object(rw,'track_view',side_effect=track):x=self.call(w,c,im,d)
  self.assertEqual(x['status'],'unknown');self.assertEqual(x['reason'],'LOCAL_INSTANCE_COMPETITION')
 def test_bad_feedback_not_recovered(self):
  w,p,c,im,d,fb=self.sample();fb['ok']=False
  x=rw.update_geometry_first(w['state'],p,c,im(c['observation_id']),d,im,fb['completed_monotonic'],fb,w['state']['geometry_update_config'])
  self.assertFalse(x['pnp_interaction']['current_support'])
 def test_bad_FK_rejected(self):
  w,p,c,im,d,fb=self.sample();c['state']['flange_pose_world'][0]+=.1
  with self.assertRaisesRegex(ValueError,'FK_INCONSISTENT'):rw.update_geometry_first(w['state'],p,c,im(c['observation_id']),d,im,fb['completed_monotonic'],fb,w['state']['geometry_update_config'])
 def test_recovery_route_never_action(self):
  answer={'decision':'need_more_evidence','proposal':None,'fine_actions':[]};derived={'recovery_only':True,'plan':None,'actions':[],'grants_execution':False}
  self.assertEqual(no_action_recovery_route(answer,derived,False,True),'NEW_PLAN_FROM_NEW_CURRENT_SUPPORT')
  self.assertEqual(no_action_recovery_route(answer,derived,True,True),'STOP_NO_EXECUTION_WITH_ORIGINAL_REASON')
  answer['decision']='refused';self.assertEqual(no_action_recovery_route(answer,derived,False,True),'STOP_NO_EXECUTION_WITH_ORIGINAL_REASON')
  derived['actions']=[{'type':'hold','seconds':1}]
  with self.assertRaisesRegex(ValueError,'CANNOT_CONTAIN'):no_action_recovery_route(answer,derived,False,True)

class RecoveryBrokerTests(PnPTests):
 def test_noaction_missing_semantic_echo_allowed_nonexecuting(self):
  for decision in ('need_more_evidence','refused'):
   row=self.start();a=self.answer(row,'refused');a['result']['decision']=decision;a['evidence_refs']=[row['attachments'][0]['id']];before=copy.deepcopy(a);self.finish(row,a)
   self.assertEqual(row['status'],'READY',row['error']);self.assertEqual(row['parsed'],before)
   self.assertEqual(row['execution_class'],'RECOVERY_ONLY');self.assertIsNone(self.b.action_ready)
   self.assertEqual(row['pnp_candidate']['actions'],[]);self.assertIsNone(row['pnp_candidate']['plan']);self.assertFalse(row['grants_execution']);self.assertFalse(row['pnp_candidate']['grants_execution'])
   self.assertEqual(self.store.get_evidence(row['evidence_id'])['execution_class'],'RECOVERY_ONLY')
 def test_planned_uses_trusted_host_semantic_without_echo(self):
  row=self.start();a=self.answer(row);a['evidence_refs']=[row['attachments'][0]['id']];self.finish(row,a)
  self.assertEqual(row['status'],'READY',row['error'])
  self.assertEqual(row['pnp_candidate']['trusted_request_evidence_ids'],row['binding']['evidence_ids'])
  self.assertEqual(row['parsed']['evidence_refs'],a['evidence_refs']);self.assertIsNone(self.b.action_ready)
 def test_noaction_new_claim_without_evidence_still_rejected(self):
  row=self.start();a=self.answer(row,'refused');a['evidence_refs']=[row['attachments'][0]['id']]
  a['result']['additional_claims']=[{'waypoint_index':1,'precondition':'target_identity_hypothesis','scope':'current','status':'supported_by_input','basis':'FAKE','evidence_refs':[]}]
  self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.assertIn('SUPPORT_WITHOUT_EVIDENCE',row['error'])
 def test_refusal_with_actions_rejected(self):
  row=self.start();a=self.answer(row,'refused');a['result']['fine_actions']=[{'type':'hold','seconds':1}];self.finish(row,a);self.assertEqual(row['status'],'FAILED')
 def test_noaction_stale_epoch_and_unknown_image_rejected(self):
  row=self.start();a=self.answer(row,'refused');self.epoch+=1;self.finish(row,a);self.assertEqual(row['status'],'FAILED');self.assertIn('STALE_EXECUTION',row['error'])
  self.epoch-=1
  row=self.start();a=self.answer(row,'refused');a['evidence_refs']=['UNSENT'];self.finish(row,a);self.assertEqual(row['status'],'FAILED')
 def test_host_evidence_tamper_rejected_even_noaction(self):
  row=self.start();a=self.answer(row,'refused');row['binding']['evidence_ids']=[];self.finish(row,a);self.assertEqual(row['status'],'FAILED')

 def test_recovery_cannot_enter_supervisor_or_owner(self):
  from platform_v1.research.supervisor import Supervisor
  from sim_skills.full_pnp.protocol import validate_actions
  from unittest.mock import Mock
  import jsonschema
  row=self.start();a=self.answer(row,'refused');a['result']['decision']='need_more_evidence';a['evidence_refs']=[row['attachments'][0]['id']];self.finish(row,a)
  owner=Mock();sup=Supervisor(owner,self.store,Mock(),self.b,self.root/'supervisor')
  with self.assertRaises((ValueError,jsonschema.ValidationError)):sup.from_broker(row['request_id'])
  owner.admit.assert_not_called();owner.execute.assert_not_called()
  with self.assertRaises(__import__('sim_skills.async_v1',fromlist=['Rejected']).Rejected):validate_actions(row['pnp_candidate']['actions'])

 def test_noaction_episode_world_and_readversions_tamper_rejected(self):
  for mode in ('episode','world_revision','read_versions'):
   row=self.start();a=self.answer(row,'refused')
   if mode=='episode':row['binding']['episode_id']='FORGED_EPISODE'
   elif mode=='world_revision':self.store.revision+=1
   else:row['pnp_proposal_host']['plan_fields']['read_versions']['FORGED']=1
   self.finish(row,a);self.assertEqual(row['status'],'FAILED',mode);self.assertIsNone(self.b.action_ready)
   if mode=='world_revision':self.store.revision-=1
