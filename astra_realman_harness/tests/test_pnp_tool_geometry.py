"""Frozen observations, robot CAD, fake answers only. Zero scene/model requests."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
from sim_skills.full_pnp import tool_geometry as t
from platform_v1.research import pnp_proposal as p
from scripts.build_tool_contact_calibration import build
from scripts.structured_outputs import compile_schema,check_provider
WS=Path('/home/alex/astra-realman_ws');RUN=WS/'run-full-pnp-approach-20261010';ASSETS=WS/'astra-sim-delivery-20261008/ASTRA_SIM_INCREMENT_20261008_v1/evidence/assets'
class ToolGeometryTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  obs=[json.loads(l)['data'] for l in (RUN/'episode/public/events.jsonl').read_text().splitlines() if json.loads(l)['kind']=='observation']
  req=json.loads((RUN/'request_A2.json').read_text());cls.o=next(o for o in obs if o['observation_id']==req['images'][0]['observation_id'])
  cls.w=next(json.loads(f.read_text()) for f in (RUN/'worlds').glob('*.json') if json.loads(f.read_text())['world_id']==req['world_id']);cls.oldrequest=req
 def test_reproducible_robot_only_calibration(self):
  self.assertEqual(build(ASSETS),t.load_calibration())
  self.assertEqual(hashlib.sha256(t.CALIBRATION.read_bytes()).hexdigest(),t.CALIBRATION_SHA256)
 def test_measured_FK_reconstructs_public_robot_geometry(self):
  self.assertLess(t.context(self.o)['URDF_measured_joints_vs_measured_pad_center_residual_m'],1e-6)
  s=json.loads((RUN/'episode/private/scene/safety_abort.json').read_text())['state']
  close={**self.o,'state':s};self.assertLess(t.context(close)['URDF_measured_joints_vs_measured_pad_center_residual_m'],1e-6)
 def test_closure_is_not_fixed_TCP_or_fixed_13mm(self):
  samples=t.context(self.o)['closure_samples'];self.assertLess(samples[4]['pad_center_delta_world_m'][2],-.01)
  self.assertLess(samples[-1]['pad_center_delta_world_m'][2],-.017)
  self.assertNotAlmostEqual(samples[4]['pad_center_delta_world_m'][2],samples[-1]['pad_center_delta_world_m'][2])
  self.assertIn('predictions',json.dumps(t.context(self.o)))
 def test_robot_context_does_not_read_task_object_truth(self):
  o=copy.deepcopy(self.o);o.update(GT='PRIVATE_SENTINEL',task='UNRELATED',RGB_REFERENCE='PRIVATE_SENTINEL',target_pose=[8,8,8]);o['state']['object_pose']=[7,7,7]
  self.assertEqual(t.context(o),t.context(self.o));self.assertNotIn('PRIVATE_SENTINEL',json.dumps(t.context(o)))
 def test_offsets_rotate_with_flange_no_world_height_answer(self):
  o=copy.deepcopy(self.o);s=o['state'];oldR=Rotation.from_quat(np.roll(s['flange_pose_world'][3:],-1)).as_matrix();rot=Rotation.from_euler('z',.4).as_matrix();newR=rot@oldR
  s['flange_pose_world'][3:]=np.roll(Rotation.from_matrix(newR).as_quat(),1).tolist()
  s['actual_grasp_center_world']=(np.array(s['flange_pose_world'][:3])+rot@(np.array(self.o['state']['actual_grasp_center_world'])-self.o['state']['flange_pose_world'][:3])).tolist()
  a=t.context(o);b=t.context(self.o)
  np.testing.assert_allclose(a['closure_samples'][5]['pad_center_delta_world_m'],rot@b['closure_samples'][5]['pad_center_delta_world_m'],atol=2e-7)
 def test_unknown_joints_and_tampered_calibration_reject(self):
  o=copy.deepcopy(self.o);o['state']['joint_names'].pop();o['state']['qpos'].pop()
  with self.assertRaisesRegex(ValueError,'JOINT_MISSING'):t.context(o)
  with tempfile.TemporaryDirectory() as d:
   f=Path(d)/'bad.json';f.write_bytes(t.CALIBRATION.read_bytes()+b' ')
   with patch.object(t,'CALIBRATION',f),self.assertRaisesRegex(ValueError,'CALIBRATION_HASH'):t.context(self.o)
 def test_request_only_adds_tool_context_output_contract_unchanged(self):
  req=p.request(self.w,self.o);self.assertTrue(req['instruction'].startswith(self.oldrequest['instruction']))
  self.assertEqual({k:v for k,v in req.items() if k!='instruction'},{k:v for k,v in self.oldrequest.items() if k!='instruction'})
  provider,_=compile_schema(req['output_schema']);check_provider(provider)
  forged=copy.deepcopy(req);forged['instruction']+=' HOST CHOOSES HEIGHT'
  with self.assertRaisesRegex(ValueError,'PNP_VERSIONED_REQUEST'):p.validate_request(forged,self.w,self.o)
 def test_raw_fine_waypoints_remain_exact_in_adapter(self):
  # Old failed answer is a regression input, NOT success under new prompt.
  from platform_v1.research import action_proposal as ap
  attempt=json.loads((RUN/'episode/private/research_broker/broker-003/attempt.json').read_text());raw=attempt['parsed'];r=raw['result'];before=copy.deepcopy(r)
  host=ap.host_context(self.w,self.o);binding=attempt['binding']
  refs=raw['evidence_refs'];d=p.adapt(r,host,self.w,self.o,attempt['attachments'],binding,refs)
  self.assertEqual(r,before);self.assertEqual(d['actions'],before['fine_actions']);self.assertEqual(d['actions'][0]['pose'][2],.032);self.assertFalse(d['grants_execution'])
