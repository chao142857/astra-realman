"""Offline contract tests. Fake model/executor/depth fixtures are explicitly separate."""
import copy
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import jsonschema
from platform_v1.research import chunk_plan, fusion, integration, losses
from platform_v1.research.contracts import validate_plan, micro_chunks
from platform_v1.research.da3_geometry import calibrated_cameras, surface_samples
from platform_v1.research.task_evidence import TaskEvidenceAdapter
from scripts.prepare_research_fake_cli import prepare
from sim_skills.full_pnp.infer_process import InferConfig
from research_fixtures import owner, wait_job
from lwh_integration_fixtures import fused_fixture, action_fixture, fake_world_check, fake_world_update, geometry_state

class LWHIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.cli=prepare(self.root/'fake');self.o=owner(self.root/'owner',InferConfig(str(self.cli),fixture=True))
        self.a=self.o.research;self.obs=self.o.observe()
    def tearDown(self):
        self.o.close();self.tmp.cleanup()
    def prepare_plan(self,H=4):
        self.w,_,_=fused_fixture(self.o,self.obs);self.row=action_fixture(self.o,self.w,self.obs,H)
        self.assertEqual(self.row['status'],'READY',self.row)
        return self.row['parsed']['result']
    def load(self,H=4):
        self.prepare_plan(H);return self.a.supervisor.from_broker(self.row['request_id'])
    def test_frozen_three_view_semantic_fusion_multiple_entities_unknown_and_raw(self):
        w,_,e=fused_fixture(self.o,self.obs)
        self.assertEqual(set(w['state']['entities']),{'fixture-object','fixture-region'})
        self.assertEqual(w['state']['entities']['fixture-object']['status'],'coarse')
        self.assertEqual(w['state']['entities']['fixture-region']['status'],'unknown')
        self.assertIsNone(w['state']['entities']['fixture-region']['point_world_m'])
        self.assertFalse(w['state']['task_identity_verified']);self.assertEqual(w['provenance'],'FAKE_MODEL_RAW')
        raw=self.a.broker.rows[e['request_id']]['raw']
        self.assertEqual(json.loads(raw)['result'],e['parsed']['result'])
        self.assertEqual({a['camera'] for a in self.a.broker.rows[e['request_id']]['attachments']},{'assembly','fixed','wrist'})
        self.assertEqual(self.o.b.commands,[])
    def test_all_horizons_same_step_semantics_and_m1(self):
        self.w,_,_=fused_fixture(self.o,self.obs)
        for h in (1,4,6,8):
            row=action_fixture(self.o,self.w,self.obs,h);p=row['parsed']['result'];validate_plan(p)
            self.assertEqual(len(p['waypoints']),h);self.assertEqual(len(micro_chunks(chunk_plan.actions(p))),h)
            self.a.broker.cancel(row['request_id'])
    def test_stage_terminal_and_no_padding_or_contact(self):
        p=self.prepare_plan();q=copy.deepcopy(p);q['waypoints']=q['waypoints'][:2]
        with self.assertRaisesRegex(ValueError,'H_NOT_FILLED'):validate_plan(q)
        q['termination']={'kind':'stage_terminal','reason':'Ready pose reached'}
        with self.assertRaisesRegex(ValueError,'UNJUSTIFIED'):validate_plan(q)
        q['waypoints'][-1]['boundary_after']='precontact_handoff';validate_plan(q)
        q['waypoints'][0]['pose']=q['origin_pose_world']
        with self.assertRaisesRegex(ValueError,'NOOP'):validate_plan(q)
        q=copy.deepcopy(p);q['waypoints'][0]={'type':'gripper','opening':0}
        with self.assertRaises(jsonschema.ValidationError):validate_plan(q)
    def test_raw_stamp_and_immutable_read_set_no_self_signed_source(self):
        p=self.prepare_plan();loaded=self.a.supervisor.from_broker(self.row['request_id'])
        row=self.a.broker.rows[self.row['request_id']]
        self.assertEqual(loaded['source_stamp']['raw_sha256'],hashlib.sha256(row['raw'].encode()).hexdigest())
        self.assertEqual((loaded['H'],loaded['H_planned'],loaded['K_completed'],loaded['m']),(4,4,0,1))
        self.assertEqual(self.o.b.commands,[])
        original=copy.deepcopy(self.a.supervisor.plans[loaded['plan_id']]['plan'])
        self.a.store.read_versions={'semantic/changed':2}
        out=self.a.supervisor.step(loaded['plan_id']);self.assertEqual(out['reason'],'READ_DEPENDENCY_CHANGED')
        self.assertEqual(self.a.supervisor.plans[loaded['plan_id']]['plan'],original)
    def test_typed_request_still_requires_exact_const_before_supervisor_load(self):
        self.prepare_plan()
        schema=self.a.broker.rows[self.row['request_id']]['schema']
        schema['properties']['result']['properties']['H'].pop('const')
        with self.assertRaisesRegex(ValueError,'PLAN_REQUEST_NOT_BOUND'):
            self.a.supervisor.from_broker(self.row['request_id'])
        self.assertEqual(self.o.b.commands,[])
    def test_manual_plan_cannot_claim_model_raw(self):
        p=self.prepare_plan()
        with self.assertRaisesRegex(ValueError,'V2_REQUIRES_BROKER_RAW'):self.a.supervisor.load(p)
        p['waypoints'][0]['pose'][0]+=.001
        with self.assertRaisesRegex(ValueError,'RAW_PLAN_MISMATCH'):self.a.supervisor.load(p,broker_request_id=self.row['request_id'])
    def test_geometry_only_revision_can_change_without_rewriting_plan(self):
        p=self.load();row=self.a.supervisor.plans[p['plan_id']]
        self.a.store.publish_world(self.w['state'],self.w['binding'],'FAKE_MODEL_RAW')
        self.assertIsNone(self.a.supervisor.invalid_reason(row))
        self.assertNotEqual(row['plan']['world_revision'],self.a.store.revision)
    def test_generic_owner_evidence_gap_stays_shadow(self):
        p=self.load()
        with patch.object(self.a.world,'update',side_effect=fake_world_update(self.a)):
            self.a.supervisor.step(p['plan_id']);out=self.a.supervisor.step(p['plan_id'])
        self.assertEqual(out['reason'],'TASK_EVIDENCE_UNKNOWN');self.assertEqual(self.o.b.commands,[])
    def test_owner_rejection_and_pending_token_not_bypassed(self):
        p=self.load();self.o.proposal={'digest':'legacy-token'}
        with patch.object(self.a.world,'update',side_effect=fake_world_update(self.a)),patch.object(TaskEvidenceAdapter,'check',return_value={'status':'valid'}):
            self.a.supervisor.step(p['plan_id']);out=self.a.supervisor.step(p['plan_id'])
        self.assertEqual(out['reason'],'OWNER_REJECTED_NO_REPLAY');self.assertEqual(self.o.b.commands,[])
    def test_one_waypoint_then_fresh_postcheck_unknown_aborts_suffix(self):
        p=self.load()
        # ONLY bypass task evidence in this isolated routing test. Actual owner remains active.
        with patch.object(self.a.world,'update',side_effect=fake_world_update(self.a)),patch.object(TaskEvidenceAdapter,'check',return_value={'status':'valid'}):
            self.a.supervisor.step(p['plan_id']);out=self.a.supervisor.step(p['plan_id'])
            self.assertEqual(out['status'],'WAITING_WORLD')
            out=self.a.supervisor.step(p['plan_id'])
        self.assertEqual(out['status'],'DISCARDED');self.assertEqual(out['K_completed'],1)
        self.assertEqual([len(x['actions']) for x in self.o.b.commands],[1])
        residual=out['last_losses']['residual'];self.assertGreaterEqual(residual['captured_monotonic'],residual['completion_monotonic'])
        self.assertIsNone(residual['entity_prediction_error_m']['fixture-object'])
        self.assertFalse(out['last_losses']['L_world']['dispatches_model']);self.assertEqual(self.a.broker.calls,2)
    def test_last_waypoint_also_checked_nominal_is_not_actual_completion(self):
        p=self.load(H=1)
        with patch.object(self.a.world,'update',side_effect=fake_world_update(self.a)),patch.object(TaskEvidenceAdapter,'check',return_value={'status':'valid'}):
            for _ in range(3):out=self.a.supervisor.step(p['plan_id'])
        self.assertEqual(out['status'],'COMPLETED');t=out['trace'][0]
        self.assertEqual(t['nominal_end_offset_s'],2.)
        self.assertGreaterEqual(t['feedback']['completed_monotonic'],t['submitted_monotonic'])
        self.assertIn('post_check',t);self.assertEqual(out['K_completed'],1)
    def test_fixed_and_adaptive_suffix_use_same_owner_and_m1(self):
        p=self.load();original=copy.deepcopy(self.a.supervisor.plans[p['plan_id']]['plan'])
        def associated(reference,current):
            out=copy.deepcopy(current);out['entities']=copy.deepcopy(reference['entities']);return out
        # Synthetic associated measurements isolate scheduling only, not perception.
        with patch.object(self.a.world,'update',side_effect=fake_world_update(self.a,associated=True)), \
             patch.object(TaskEvidenceAdapter,'check',return_value={'status':'valid'}), \
             patch('platform_v1.research.supervisor.current_regions',side_effect=associated), \
             patch('platform_v1.research.losses.projective_residual',return_value={'observation_residual_m':0.,'observation_residual_status':'SYNTHETIC_FIXTURE'}):
            for _ in range(12):
                p=self.a.supervisor.step(p['plan_id'])
                if p['status'] in ('COMPLETED','DISCARDED'):break
        self.assertEqual(p['status'],'COMPLETED');self.assertEqual(p['K_completed'],4)
        self.assertEqual([len(c['actions']) for c in self.o.b.commands],[1]*4)
        self.assertEqual([t['origin']['waypoint_offset'] for t in p['trace']],[0,1,2,3])
        self.assertTrue(all('post_check' in t for t in p['trace']))
        self.assertEqual(original,self.a.supervisor.plans[p['plan_id']]['plan']);self.assertEqual(self.a.broker.calls,2)
    def test_fixed_prefix_stops_at_K_without_requesting_E(self):
        p=self.load();self.a.supervisor.policy(p['plan_id'],'fixed',1)
        with patch.object(self.a.world,'update',side_effect=fake_world_update(self.a)),patch.object(TaskEvidenceAdapter,'check',return_value={'status':'valid'}):
            for _ in range(3):p=self.a.supervisor.step(p['plan_id'])
        self.assertEqual(p['K_completed'],1);self.assertIn('PREFIX_CAP',p['last_losses']['L_chunk']['reasons'])
        self.assertEqual(self.a.broker.calls,2)
    def test_schema_artifacts_match_code(self):
        base=Path(__file__).resolve().parents[1]/'docs/structured_outputs_v1'
        self.assertEqual(json.loads((base/'ActionChunkPlan.authoritative.template.schema.json').read_text()),chunk_plan.plan_schema())
        self.assertEqual(json.loads((base/'SemanticScene.authoritative.schema.json').read_text()),fusion.semantic_schema())
    def test_learned_runtime_mounts_do_not_expose_workspace_ancestor(self):
        from platform_v1.research.learned_runtime import sandbox_parts
        venv=Path('/home/alex/astra-realman_ws/lwh-runtime/venv')
        with patch('platform_v1.research.learned_runtime.validate_config',return_value=(venv,venv.parent/'weights',[Path('/dev/nvidia0')])):
            args,exe=sandbox_parts({})
        self.assertEqual(exe,'/lwh-venv/bin/python')
        self.assertEqual(args[:6],['--ro-bind',str(venv),'/lwh-venv','--ro-bind',str(venv.parent/'weights'),'/weights'])
    def test_no_config_or_model_cannot_launch_jobs(self):
        with self.assertRaisesRegex(ValueError,'DA3_NOT_CONFIGURED'):self.a.world.submit([self.obs['observation_id']],[],'da3_small_v1')
        with self.assertRaisesRegex(ValueError,'DA3_NOT_CONFIGURED'):self.a.dispatch('lwh_prepare',{'observation_id':self.obs['observation_id']})
        self.assertEqual(self.a.broker.calls,0);self.assertEqual(self.a.world.rows,{})
    def test_fusion_rejects_mismatched_source_and_nonlearned_geometry(self):
        w,g,e=fused_fixture(self.o,self.obs)
        g['result']['world_revision']=self.a.store.revision
        g['result']['state']['backend']='bbox_rays_v1'
        with self.assertRaisesRegex(ValueError,'LEARNED_GEOMETRY_REQUIRED'):fusion.fuse(self.a.store,g,e['evidence_id'])
        g['result']['state']['backend']='da3_small_v1';g['result']['binding']['observation_ids']=['other']
        with self.assertRaisesRegex(ValueError,'FROZEN_INPUT_MISMATCH'):fusion.fuse(self.a.store,g,e['evidence_id'])
    def test_camera_axis_and_intrinsic_backprojection_roundtrip(self):
        ext,k=calibrated_cameras(self.obs)
        for i,name in enumerate(('assembly','fixed','wrist')):
            c=self.obs['calibration'][name];r=np.linalg.inv(ext[i]);point=r[:3,:3]@np.array([0,0,.5])+r[:3,3]
            x=ext[i][:3,:3]@point+ext[i][:3,3];uv=k[i]@x;uv=uv[:2]/uv[2]
            np.testing.assert_allclose(uv,k[i][:2,2],atol=1e-3)
        obs=copy.deepcopy(self.obs)
        for c in obs['calibration'].values():c['pose_world_xyz_wxyz'][:3]=[0,0,0]
        with self.assertRaisesRegex(ValueError,'BASELINE'):calibrated_cameras(obs)
    def test_sample_output_uses_depth_not_bbox_triangulation(self):
        ext,k=calibrated_cameras(self.obs)
        samples=surface_samples(np.ones((3,10,10))*.7,np.ones((3,10,10)),ext,k,self.obs)
        self.assertTrue(samples)
        for p in samples:
            i=('assembly','fixed','wrist').index(p['camera'])
            x=ext[i][:3,:3]@p['point_world_m']+ext[i][:3,3];self.assertAlmostEqual(x[2],.7,places=5)
    def test_independent_chunk_and_world_losses_fixed_adaptive_and_unknown(self):
        r={'robot_translation_m':0.,'robot_rotation_rad':0.,'entity_prediction_error_m':{'x':0.},'observation_residual_m':0.}
        args=dict(completed=1,planned=4,K_cap=4,mode='adaptive',preconditions=True,residual=r,visibility='visible')
        self.assertTrue(losses.decide_chunk(**args)['continue_next'])
        r['entity_prediction_error_m']['x']=None
        self.assertFalse(losses.decide_chunk(**args)['continue_next'])
        args['mode']='fixed';self.assertTrue(losses.decide_chunk(**args)['continue_next'])
        r['robot_translation_m']=.02
        self.assertFalse(losses.decide_chunk(**args)['continue_next'])
        r['robot_translation_m']=0.
        args['preconditions']=False;self.assertFalse(losses.decide_chunk(**args)['continue_next'])
        self.assertFalse(losses.decide_world(geometry_loss=9.,query_budget=1)['recommend_query'])
        self.assertTrue(losses.decide_world(identity_conflict=True,query_budget=1)['recommend_query'])
        self.assertFalse(losses.decide_world(identity_conflict=True,query_budget=0)['recommend_query'])
    def test_future_observation_and_forecast_prefix_binding(self):
        p=self.prepare_plan();f=losses.forecast(p,self.w['state'])
        self.assertEqual(f['after_waypoint'][-1]['depends_on_completed_prefix'],[1,2,3,4])
        with self.assertRaisesRegex(ValueError,'OBSERVATION_BEFORE_COMPLETION'):
            losses.compare(f['after_waypoint'][0],self.w['state'],self.w['state']['captured_monotonic']+1.)

if __name__=='__main__':unittest.main(verbosity=2)
