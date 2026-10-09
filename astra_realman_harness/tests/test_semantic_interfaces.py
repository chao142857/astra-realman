"""No-model interface tests; archived annotations never represent real E0."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from platform_v1.research import model_context as ctx
from platform_v1.research import semantic_rgbd as bridge
from platform_v1.research.contracts import digest
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research.fusion import semantic_schema
from platform_v1.research.geometry_quality import require_task_usable

ROOT=Path(__file__).resolve().parents[3]/'rgbd-world-20261009'

class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs=json.loads((ROOT/'inputs/D0_control/observations.json').read_text())[0]
        cls.annotation=json.loads((ROOT/'inputs/D0_control/annotation.json').read_text())
        cls.saved=json.loads((ROOT/'results/D0_01/build.json').read_text())
        cls.protocol=json.loads((ROOT/'PROTOCOL.json').read_text())
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=PublicStore(ROOT/'inputs/D0_control/public',self.obs['episode_id'])
        self.store.observe(self.obs,self.obs['execution_epoch'])
        a=self.annotation
        self.e=self.store.evidence_record('offline','semantic_e0',a['result'],a['provenance'],[self.obs['observation_id']],a['attachments'])
        self.head=WorldHead(Path(self.temp.name),self.store,epoch=lambda:self.obs['execution_epoch'],deadline=time.monotonic()+100,emit=lambda *x:None)
        self.head.public_plane=self.saved['state']['public_plane']
    def tearDown(self):self.temp.cleanup()
    def prepare(self):return bridge.prepare_masks(self.store,self.obs['observation_id'],self.e['evidence_id'],self.head.public_plane)
    def test_query_is_compact_and_preserves_version_source(self):
        w=self.store.publish_world(self.saved['state'],{},self.saved['provenance'],{'semantic/e':1})
        before=digest(self.store.get_world(w['world_id']));q=self.store.query_world(w['world_id'])
        self.assertLess(len(json.dumps(q)),32768)
        self.assertLess(len(json.dumps(q)),len(json.dumps(w))/20)
        for key in ('world_id','world_revision','read_versions','provenance'):self.assertEqual(w[key],q[key])
        self.assertEqual(q['query']['source_state_sha256'],digest(w['state']))
        self.assertEqual(digest(self.store.get_world(w['world_id'])),before)
        self.assertNotIn('surface_cloud',q['state']['entities']['block-01'])
        self.assertFalse(q['query']['grants_execution'])
    def test_query_unknown_history_stays_separate(self):
        w=copy.deepcopy(self.saved);e=w['state']['entities']['block-01']
        e.update(status='unknown',point_world_m=None,measurement_kind='unknown',historical_geometry={'point_world_m':[1,2,3],'observation_id':'old'})
        q=ctx.compact_world(w)['state']['entities']['block-01']
        self.assertIsNone(q['point_world_m']);self.assertEqual(q['measurement_kind'],'unknown')
        self.assertEqual(q['historical_geometry']['measurement_kind'],'historical_not_current')
    def test_selection_and_budget_no_silent_truncation(self):
        q=ctx.compact_world(self.saved,['block-01']);self.assertEqual(list(q['state']['entities']),['block-01'])
        for ids in (['bad'],['block-01','block-01']):
            with self.assertRaisesRegex(ValueError,'ENTITY_IDS'):ctx.compact_world(self.saved,ids)
        with self.assertRaisesRegex(ValueError,'TOO_LARGE'):ctx.compact_world(self.saved,max_bytes=100)
    def test_semantic_input_whitelist_action_proprioception(self):
        o=copy.deepcopy(self.obs);o['private_truth']='injected';o['calibration']['fixed']['private_pose']='injected'
        semantic=ctx.observation_view(o,'semantic_e0');s=json.dumps(semantic)
        for key in ('depth','state','execution_feedback','private_truth','private_pose','file'):self.assertNotIn('"'+key+'"',s)
        self.assertEqual(semantic['calibration']['wrist']['pose_world_xyz_wxyz'],o['calibration']['wrist']['pose_world_xyz_wxyz'])
        action=ctx.observation_view(o,'action');self.assertIn('flange_pose_world',action['state']);self.assertNotIn('depth',action)
    def request(self):return {'role':'semantic_e0','output_schema':semantic_schema(),'world_id':None,'evidence_ids':[],
        'images':[{'camera':c,'roi':None,'observation_id':'o'} for c in ('assembly','fixed','wrist')]}
    def test_initial_request_three_full_same_frame(self):
        ctx.validate_initial_semantic_request(self.request())
        for edit in (lambda r:r['images'].pop(),lambda r:r['images'][0].update(roi=[0,0,.5,.5]),lambda r:r['images'][0].update(observation_id='old')):
            r=self.request();edit(r)
            with self.assertRaisesRegex(ValueError,'THREE_FROZEN'):ctx.validate_initial_semantic_request(r)
        for edit in (lambda r:r.update(world_id='w'),lambda r:r.update(evidence_ids=['e'])):
            r=self.request();edit(r)
            with self.assertRaisesRegex(ValueError,'RGB_GEOMETRY_ONLY'):ctx.validate_initial_semantic_request(r)
    def test_calibration_movement_is_measurement_not_contract_change(self):
        a=copy.deepcopy(self.obs['calibration']);b=copy.deepcopy(a);b['wrist']['pose_world_xyz_wxyz'][0]+=.04
        self.assertEqual(ctx.calibration_key(a),ctx.calibration_key(b))
        b['wrist']['intrinsic'][0][0]+=1;self.assertNotEqual(ctx.calibration_key(a),ctx.calibration_key(b))
    def test_visibility_never_promotes_unknown(self):
        for v in ('unknown','unknown_association','out_of_view','occluded'):self.assertEqual(ctx.canonical_visibility(v),v)
        self.assertEqual(ctx.canonical_visibility('visible_RGB_support'),'visible')
    def test_saved_sensor_bbox_mask_build_keeps_provenance_and_admission(self):
        masks,report=self.prepare();self.assertEqual(report['Astra_calls'],0);self.assertGreater(len(masks),0)
        self.assertFalse(any(key[0]=='region-01' for key in masks))
        for r in masks.values():
            self.assertEqual(r['producer'],bridge.METHOD);self.assertEqual(r['semantic_provenance'],self.e['provenance'])
        with patch.object(self.head,'submit',side_effect=AssertionError('model forbidden')):
            w=self.head.build_rgbd(self.obs['observation_id'],self.e['evidence_id'],masks,{k:self.protocol[k] for k in ('geometry','tracker')})
        self.assertEqual(w['state']['entities']['block-01']['status'],'coarse')
        self.assertEqual(w['state']['entities']['region-01']['status'],'unknown')
        self.assertEqual(w['state']['geometry_quality']['task_usable'],'unknown')
        self.assertTrue(any(k.startswith('task_selection/') for k in w['read_versions']))
        self.assertIn('visibility/observed_support_v1',w['read_versions'])
        with self.assertRaisesRegex(ValueError,'NOT_TASK_USABLE'):require_task_usable(w,{})
    def test_real_entry_rejects_diagnostic_without_dispatch(self):
        with self.assertRaisesRegex(ValueError,'REAL_E0_REQUIRED'):
            self.head.build_rgbd_from_semantic(self.obs['observation_id'],self.e['evidence_id'],{})
    def test_unknown_id_and_partial_view_never_measured(self):
        e=self.store.evidence[self.e['evidence_id']];e['result']['entities'][0]['identity_status']='unknown'
        masks,r=self.prepare();self.assertEqual(masks,{})
        self.assertIn('UNRESOLVED_IDENTITY',[x['reason'] for x in r['rows']])
    def test_missing_sensor_or_forged_image_rejected(self):
        o=self.store.observations[self.obs['observation_id']];saved=o.pop('depth')
        with self.assertRaisesRegex(ValueError,'THREE_DEPTH'):self.prepare()
        o['depth']=saved
        self.store.evidence[self.e['evidence_id']]['attachments'][0]['source_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'FROZEN_IMAGE'):self.prepare()
    def test_competing_ids_not_largest_component_choice(self):
        entities=self.store.evidence[self.e['evidence_id']]['result']['entities'];duplicate=copy.deepcopy(entities[0]);duplicate['entity_id']='other';entities.append(duplicate)
        masks,r=self.prepare();self.assertEqual(masks,{})
        self.assertIn('INSTANCE_MASK_COMPETITION',[x['reason'] for x in r['rows']])
    def test_bad_observation_and_duplicate_views_rejected(self):
        e=self.store.evidence[self.e['evidence_id']];e['observation_ids']=['old']
        with self.assertRaisesRegex(ValueError,'FROZEN_SEMANTIC'):self.prepare()
        e['observation_ids']=[self.obs['observation_id']];views=e['result']['entities'][0]['views'];views[1]=copy.deepcopy(views[0])
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ENTITY_VIEW'):self.prepare()

class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.d=np.ones((40,40));self.v=np.ones((40,40),bool)
        self.k=np.array([[200,0,20],[0,200,20],[0,0,1.]])
        self.plane={'normal':[0,0,1],'offset':-1};self.box=[.1,.1,.9,.9]
    def mask(self):return bridge.component_mask(self.d,self.v,np.eye(4),self.k,self.box,self.plane)
    def test_unique_component(self):
        self.d[10:16,10:16]=1.1;m,r=self.mask();self.assertEqual(int(m.sum()),36)
    def test_multiple_components_unknown(self):
        self.d[10:16,10:16]=1.1;self.d[24:30,24:30]=1.1;m,r=self.mask()
        self.assertIsNone(m);self.assertEqual(r['qualifying_components'],2)
    def test_invalid_depth_unknown(self):
        self.d[10:16,10:16]=1.1;self.v[:]=False;m,r=self.mask();self.assertIsNone(m)
    def test_roi_truncation_and_frame_clipping_unknown(self):
        self.d[3:16,10:16]=1.1;m,r=self.mask();self.assertIsNone(m);self.assertEqual(r['reason'],'COMPONENT_TRUNCATED_BY_BBOX')
        self.box=[0,.1,.9,.9];m,r=self.mask();self.assertIsNone(m);self.assertEqual(r['reason'],'CLIPPED_BBOX')
    def test_depth_discontinuity_splits_touching_pixels(self):
        self.d[10:16,10:16]=1.1;self.d[10:16,16:22]=1.2;m,r=self.mask()
        self.assertIsNone(m);self.assertEqual(r['qualifying_components'],2)

if __name__=='__main__':unittest.main(verbosity=2)
