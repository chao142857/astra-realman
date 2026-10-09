"""Admission/causality and genuine archived-RGB mechanism tests; no model or physics."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from platform_v1.research import cheap_update, geometry_quality, integration
from platform_v1.research.world_head import WorldHead
from research_fixtures import owner

WS=Path(__file__).resolve().parents[3]
OLD=WS/'da3-small-acceptance-20261009'

class GeometryGateTests(unittest.TestCase):
    def setUp(self):
        if not OLD.exists():self.skipTest('sealed local G1 data not installed')
        self.obs=json.loads((OLD/'inputs/G1/public_input.json').read_text())['observations'][0]
        self.state=json.loads((OLD/'runs/G1/world_geometry.json').read_text())['state']
        self.images={c:np.array(Image.open(OLD/'inputs/G1'/p).convert('RGB')) for c,p in self.obs['images'].items()}
        self.plane={'normal':[0,0,1],'offset':0,'source':'PUBLIC_TABLE'}
    def test_sealed_failure_numeric_valid_but_plane_conflict_not_task_usable(self):
        q=geometry_quality.assess(self.state,self.obs,self.images,self.plane)
        self.assertEqual((q['numeric_valid'],q['self_consistent'],q['task_usable']),('pass','fail','fail'))
        self.assertIn('PUBLIC_PLANE_CONFLICT',q['reason'])
        bad={'state':dict(self.state,geometry_quality=q)}
        with self.assertRaisesRegex(ValueError,'NOT_TASK_USABLE'):
            integration.action_request(bad,self.obs,{}, {},4)
    def test_finite_and_known_alone_cannot_authorize_planning(self):
        q=geometry_quality.assess(self.state,self.obs,self.images,None)
        self.assertEqual(q['self_consistent'],'unknown');self.assertEqual(q['task_usable'],'unknown')
        with self.assertRaises(ValueError):geometry_quality.require_task_usable({'state':self.state},{})
    def test_nonfinite_is_separate_failure(self):
        state=copy.deepcopy(self.state);state['surface_samples'][0]['point_world_m'][0]=float('nan')
        self.assertEqual(geometry_quality.assess(state,self.obs,self.images,self.plane)['numeric_valid'],'fail')
    def test_current_detection_does_not_copy_historical_bbox(self):
        hue=60
        mask,_=cheap_update.current_mask(self.images['fixed'],hue)
        self.assertIsNotNone(mask)
        empty,reason=cheap_update.current_mask(np.zeros_like(self.images['fixed']),hue)
        self.assertIsNone(empty);self.assertEqual(reason,'NO_CURRENT_APPEARANCE_SUPPORT')
    def test_repeated_source_and_precompletion_input_rejected(self):
        ref={'observation_id':self.obs['observation_id'],'entities':{}}
        with self.assertRaisesRegex(ValueError,'BEFORE_COMPLETION'):
            cheap_update.measure(ref,self.obs,self.obs,self.images,self.images,self.obs['captured_monotonic']+1)
        with self.assertRaisesRegex(ValueError,'NONCAUSAL'):
            cheap_update.measure(ref,self.obs,self.obs,self.images,self.images,0)

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.o=owner(Path(self.temp.name)/'owner',None)
        self.a=self.o.research;self.first=self.o.observe()
        state={'backend':'semantic_lwh_v1','observation_id':self.first['observation_id'],
            'captured_monotonic':self.first['captured_monotonic'],'robot_state':self.first['state'],
            'scene_healthy':True,'entities':{},'geometry_only':False}
        self.w=self.a.store.publish_world(state,{'observation_ids':[self.first['observation_id']],
            'execution_epoch':self.o.epoch},'ENGINEERING_REFERENCE')
    def tearDown(self):self.o.close();self.temp.cleanup()
    def test_update_uses_existing_store_and_never_submits_learning_or_broker(self):
        now=self.o.observe()
        with patch.object(self.a.world,'submit',side_effect=AssertionError('DA3 forbidden')), \
             patch.object(self.a.broker,'submit',side_effect=AssertionError('Astra forbidden')):
            w=self.a.dispatch('lwh_update',{'reference_world_id':self.w['world_id'],
                'observation_id':now['observation_id'],'completed_monotonic':self.first['captured_monotonic']})
        self.assertEqual(w['world_revision'],self.w['world_revision']+1)
        self.assertEqual(w['state']['resource_metrics']['DA3_calls'],0)
        self.assertEqual(w['state']['robot_state'],now['state'])
        self.assertTrue(w['state']['rebuild_needed'])
        self.assertEqual(self.o.b.commands,[]);self.assertEqual(self.a.broker.calls,0)
    def test_rebuild_request_does_not_dispatch(self):
        with patch.object(self.a.world,'submit',side_effect=AssertionError('no dispatch')):
            r=self.a.dispatch('lwh_rebuild_request',{'reference_world_id':self.w['world_id'],
                'observation_id':self.first['observation_id'],'reason':'unreliable coarse state','components':['geometry']})
        self.assertEqual(r['status'],'REQUESTED_NOT_DISPATCHED');self.assertEqual(self.a.world.rows,{})
    def test_stale_update_cannot_merge(self):
        now=self.o.observe();self.a.world.update(self.w['world_id'],now['observation_id'],0)
        with self.assertRaisesRegex(ValueError,'STALE_UPDATE_BASE'):
            self.a.world.update(self.w['world_id'],now['observation_id'],0)
    def test_revision_changed_during_compute_cannot_merge(self):
        now=self.o.observe()
        def changed(*args):
            self.a.store.publish_world(self.w['state'],self.w['binding'],'ENGINEERING_REFERENCE')
            return {'resource_metrics':{}}
        with patch('platform_v1.research.cheap_update.measure',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'STALE_UPDATE_AFTER_COMPUTE'):
                self.a.world.update(self.w['world_id'],now['observation_id'],0)
        self.assertEqual(self.a.store.revision,self.w['world_revision']+1)
    def test_direct_broker_cannot_bypass_geometry_gate(self):
        self.a.broker.config=object() # rejected before any config use or process creation
        req={'backend':'existing_codex_infer','role':'action','instruction':'test','images':[],
            'evidence_ids':[],'world_id':self.w['world_id'],'output_schema':{},'timeout_s':1}
        with self.assertRaisesRegex(ValueError,'NOT_TASK_USABLE'):self.a.broker.submit(req)
        self.assertEqual(self.a.broker.calls,0)

if __name__=='__main__':unittest.main(verbosity=2)
