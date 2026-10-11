"""Narrow offline Broker tests; FAKE responses, no model or Owner calls."""
import copy
from test_full_pnp_connection import PnPTests
from platform_v1.research import pnp_proposal as pp
from platform_v1.research.contracts import digest

class HostBindingTests(PnPTests):
 def image_refs(self,row,a):a['evidence_refs']=[x['id'] for x in row['attachments']];return a
 def test_planned_host_source_without_model_echo(self):
  row=self.start();a=self.image_refs(row,self.answer(row));before=copy.deepcopy(a);self.finish(row,a)
  self.assertEqual(row['status'],'READY',row['error']);self.assertEqual(row['parsed'],before)
  d=row['pnp_candidate'];self.assertEqual(d['model_evidence_refs'],before['evidence_refs'])
  self.assertEqual(d['plan']['evidence_refs'],row['binding']['evidence_ids'])
  self.assertEqual(d['trusted_semantic_binding']['binding'],row['binding'])
  self.assertEqual(d['trusted_semantic_binding']['task_binding'],d['plan']['task_binding'])
  self.assertEqual(d['actions'],[{'type':'move_pose','pose':x['pose']} for x in before['result']['proposal']['waypoints']])
  self.assertEqual(d['proposal_sha256'],digest(before['result']));self.assertFalse(d['grants_execution']);self.assertEqual(d['K'],0);self.assertIsNone(self.b.action_ready)
 def test_fine_host_binding_without_echo(self):
  row=self.start();a=self.image_refs(row,self.answer(row));a['result'].update(mode='fine',phase='trial_lift',proposal=None,fine_actions=[{'type':'hold','seconds':1.2}]);self.finish(row,a)
  self.assertEqual(row['status'],'READY',row['error']);self.assertEqual(row['pnp_candidate']['actions'],a['result']['fine_actions'])
 def test_additional_identity_claim_requires_model_ref(self):
  row=self.start();a=self.image_refs(row,self.answer(row));c=self.claim(row,'target_identity_hypothesis');a['result']['additional_claims']=[c];self.finish(row,a)
  self.assertEqual(row['status'],'FAILED');self.assertIn('IDENTITY_EVIDENCE',row['error'])
 def test_additional_identity_claim_cannot_borrow_host_envelope(self):
  row=self.start();a=self.image_refs(row,self.answer(row));c=self.claim(row,'target_identity_hypothesis');c['evidence_refs']=row['binding']['evidence_ids'];a['result']['additional_claims']=[c];self.finish(row,a)
  self.assertEqual(row['status'],'FAILED');self.assertIn('UNBOUND_CLAIM',row['error'])
 def test_valid_explicit_identity_claim(self):
  row=self.start();a=self.answer(row);c=self.claim(row,'target_identity_hypothesis');c['evidence_refs']=row['binding']['evidence_ids'];a['result']['additional_claims']=[c];self.finish(row,a);self.assertEqual(row['status'],'READY',row['error'])
 def test_invalid_claims_rejected_without_semantic_echo(self):
  for change in ({'evidence_refs':[]},{'evidence_refs':['UNSENT']},{'scope':'future'},{'precondition':'owner_admission'}):
   row=self.start();a=self.image_refs(row,self.answer(row));c=self.claim(row);c.update(change);a['result']['additional_claims']=[c];self.finish(row,a);self.assertEqual(row['status'],'FAILED',change)
 def test_runtime_binding_tamper_rejected(self):
  for key,value in [('episode_id','FORGED'),('world_revision',999),('execution_epoch',999),('evidence_ids',[]),('observation_ids',['FORGED'])]:
   row=self.start();a=self.image_refs(row,self.answer(row));row['binding'][key]=value;self.finish(row,a);self.assertEqual(row['status'],'FAILED',key)
 def test_host_target_task_readversions_source_tamper_rejected(self):
  for kind in ('target','task','read_versions','source'):
   row=self.start();a=self.image_refs(row,self.answer(row));h=row['pnp_proposal_host']
   if kind=='target':h['plan_fields']['task_binding']['object_id']='FORGED'
   elif kind=='task':h['plan_fields']['task']['id']='FORGED'
   elif kind=='read_versions':h['plan_fields']['read_versions']['FORGED']=1
   else:h['world_sha256']='FORGED'
   self.finish(row,a);self.assertEqual(row['status'],'FAILED',kind)
 def test_world_target_and_semantic_source_tamper_rejected(self):
  for kind in ('target','source'):
   row=self.start();a=self.image_refs(row,self.answer(row));original=copy.deepcopy(self.store.worlds[self.w['world_id']])
   if kind=='target':self.store.worlds[self.w['world_id']]['state']['task_selection']['task_target_geometry_id']='FORGED'
   else:self.store.worlds[self.w['world_id']]['state']['semantic_source']['raw_sha256']='FORGED'
   self.finish(row,a);self.assertEqual(row['status'],'FAILED',kind);self.store.worlds[self.w['world_id']]=original
 def test_unsent_refs_and_host_override_rejected(self):
  row=self.start();a=self.answer(row);a['evidence_refs']=['UNSENT'];self.finish(row,a);self.assertEqual(row['status'],'FAILED')
  row=self.start();a=self.image_refs(row,self.answer(row));a['result']['trusted_semantic_binding']={};self.finish(row,a);self.assertEqual(row['status'],'FAILED')
 def test_source_receipt_required_before_prepare(self):
  self.b.pnp_episode_authorization=self.store.episode_id;self.store.grounding_sources.clear()
  with self.assertRaisesRegex(ValueError,'RECEIPT_REQUIRED'):self.b.prepare(self.request())
 def test_real_prepare_schema_unchanged_no_dispatch(self):
  from unittest.mock import patch
  from scripts.structured_outputs import check_provider
  self.b.pnp_episode_authorization=self.store.episode_id;self.b.config.fixture=False;self.b.allowance=lambda:0
  with patch('platform_v1.research.broker.ProcessJob',side_effect=AssertionError('NO_MODEL')),patch('platform_v1.research.broker.sandbox_command',side_effect=AssertionError('NO_AUTH')):
   result=self.b.prepare(self.request())
  row=self.b.rows[result['request_id']];check_provider(row['provider_schema'])
  self.assertEqual(self.b.calls,0);self.assertEqual(self.b.infer_calls,0);self.assertIsNone(self.b.job);self.assertEqual(len(row['attachments']),3)
 def test_fake_semantic_cannot_enter_real_input(self):
  self.b.pnp_episode_authorization=self.store.episode_id;self.b.config.fixture=False
  self.store.evidence[self.w['binding']['evidence_ids'][0]]['provenance']='FAKE_MODEL_RAW'
  with self.assertRaises(ValueError):self.b.prepare(self.request())
 def test_action_boundaries_with_fresh_broker_per_fault(self):
  # Each software fault is a separate request context; never weaken the real
  # per-episode eight-call budget to run a many-case unit test.
  edits=[lambda p:p['waypoints'][0]['pose'].__setitem__(0,300),
   lambda p:p['waypoints'][0]['pose'].__setitem__(3,2),
   lambda p:p['waypoints'][0]['pose'].__setitem__(slice(3,None),[0,0,0,1]),
   lambda p:p['waypoints'][0]['pose'].__setitem__(0,float('nan')),
   lambda p:p['waypoints'].pop(),lambda p:p['waypoints'].append(copy.deepcopy(p['waypoints'][-1])),
   lambda p:p['waypoints'][1].update(nominal_end_offset_s=3),
   lambda p:p['waypoints'][1].update(prediction_dependencies=[]),
   lambda p:p['waypoints'][0].update(type='gripper'),lambda p:p['waypoints'][0].update(index=0),
   lambda p:p['waypoints'][0]['pose'].__setitem__(0,self.o['state']['actual_grasp_center_world'][0]+.001)]
  for edit in edits:
   case=PnPTests();case.setUp()
   try:
    row=case.start();a=case.answer(row);edit(a['result']['proposal']);case.finish(row,a)
    self.assertEqual(row['status'],'FAILED');self.assertIsNone(case.b.action_ready)
   finally:case.tearDown()
