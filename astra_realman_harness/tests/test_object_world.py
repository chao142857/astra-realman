"""Contract/adversarial tests; archived RGB is a diagnostic, NOT a new episode."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research import object_world, object_tracking, geometry_quality

ROOT=Path(__file__).resolve().parents[3]/'object-centric-world-20261009'

class ObjectWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/'inputs/C1_normal_init2/observations.json').exists():raise unittest.SkipTest('local archive not exported')
        cls.obs=json.loads((ROOT/'inputs/C1_normal_init2/observations.json').read_text())
        cls.annotation=json.loads((ROOT/'inputs/C1_normal_init2/semantic_annotation.json').read_text())
        cls.maskrecords=json.loads((ROOT/'inputs/C1_normal_init2/diagnostic_masks.json').read_text())
        cls.protocol=json.loads((ROOT/'PROTOCOL.json').read_text())
        cls.plane=json.loads((ROOT/'inputs/public_plane.json').read_text())
        cls.built=json.loads((ROOT/'results/diagnostic_02/C1_normal_init2_build.json').read_text())
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=PublicStore(ROOT/'inputs','C1_normal_init2')
        for o in self.obs:self.store.observe(o,0)
        self.e=self.store.evidence_record('offline','semantic_e0',self.annotation['result'],self.annotation['provenance'],
            [self.obs[0]['observation_id']],self.annotation['attachments'])
        self.masks={}
        for rec in copy.deepcopy(self.maskrecords):
            rec['semantic_evidence_id']=self.e['evidence_id'];self.masks[(rec['entity_id'],rec['camera'])]=rec
        self.head=WorldHead(Path(self.temp.name),self.store,epoch=lambda:0,deadline=time.monotonic()+300,emit=lambda *x:None)
        self.head.public_plane=self.plane
        self.config={k:self.protocol[k] for k in ('geometry','tracker')}
    def tearDown(self):self.temp.cleanup()
    def build(self):return self.head.build_objects(self.obs[0]['observation_id'],self.e['evidence_id'],self.masks,self.config)
    def entities(self):
        es=copy.deepcopy(self.annotation['result']['entities'])
        for e in es:
            for v in e['views']:v['camera']=v['attachment_id']
        return es
    def test_build_publishes_queryable_instance_with_no_pseudo_point(self):
        with patch.object(self.head,'submit',side_effect=AssertionError('learned worker forbidden')):
            w=self.build()
        e=self.store.get_object(w['world_id'],'block-01')['object']
        self.assertEqual(e['status'],'coarse');self.assertGreater(len(e['occupancy']['indices']),0)
        self.assertIsNone(e['point_world_m']);self.assertEqual(e['semantic_source']['provenance'],'OFFLINE_RGB_ANNOTATION_NOT_MODEL_RAW')
        self.assertEqual(e['diagnostics']['constraining_views'],['assembly','fixed'])
        with self.assertRaisesRegex(ValueError,'NOT_TASK_USABLE'):geometry_quality.require_task_usable(w,{})
        e['label']='mutated';self.assertNotEqual(self.store.get_object(w['world_id'],'block-01')['object']['label'],'mutated')
    def test_foreign_image_hash_rejected(self):
        self.masks[('block-01','fixed')]['image_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'MASK_EVIDENCE_BINDING'):self.build()
    def test_foreign_prompt_rejected(self):
        self.masks[('block-01','fixed')]['bbox_prompt_normalized']=[0,0,1,1]
        with self.assertRaisesRegex(ValueError,'MASK_PROMPT_BINDING'):self.build()
    def test_unknown_instance_cannot_produce_geometry(self):
        es=self.entities()
        for e in es:e['identity_status']='unknown'
        w=object_world.build(self.obs[0],es,self.masks,self.config['geometry'],self.plane,{'source':'test'})
        self.assertTrue(all(e['occupancy'] is None for e in w['entities'].values()))
    def test_partial_views_do_not_carve(self):
        es=self.entities()
        for e in es:
            for v in e['views']:v['visibility']='partial'
        w=object_world.build(self.obs[0],es,self.masks,self.config['geometry'],self.plane,{'source':'test'})
        self.assertTrue(all(e['reason']=='INSUFFICIENT_COMPLETE_SILHOUETTES' for e in w['entities'].values()))
    def test_duplicate_instance_and_overlapping_identities_rejected(self):
        es=self.entities();es[1]=copy.deepcopy(es[0])
        with self.assertRaisesRegex(ValueError,'DUPLICATE_INSTANCE'):object_world.build(self.obs[0],es,self.masks,self.config['geometry'],self.plane,{'source':'test'})
        es[1]['entity_id']='duplicate'
        for c in ('assembly','fixed','wrist'):
            self.masks[('duplicate',c)]=copy.deepcopy(self.masks[('block-01',c)])
        w=object_world.build(self.obs[0],es,self.masks,self.config['geometry'],self.plane,{'source':'test'})
        self.assertTrue(all(e['occupancy'] is None for e in w['entities'].values()))
    def test_weak_baseline_and_wrong_axes_not_positions(self):
        cfg=copy.deepcopy(self.config['geometry']);cfg['min_baseline_m']=10
        w=object_world.build(self.obs[0],self.entities(),self.masks,cfg,self.plane,{'source':'test'})
        self.assertIsNone(w['entities']['block-01']['occupancy'])
        obs=copy.deepcopy(self.obs[0]);obs['calibration']['wrist']['axes']='OpenCV'
        with self.assertRaisesRegex(ValueError,'CAMERA_AXES'):object_world.build(obs,self.entities(),self.masks,cfg,self.plane,{'source':'test'})
    def test_bad_time_and_bad_mask_shape_fail_closed(self):
        obs=copy.deepcopy(self.obs[0]);obs['capture_span_s']=1
        with self.assertRaisesRegex(ValueError,'UNSYNCHRONIZED'):object_world.build(obs,self.entities(),self.masks,self.config['geometry'],self.plane,{'source':'test'})
        self.masks[('block-01','fixed')]['mask']={'shape':[10,10],'runs':[[0,100]]}
        with self.assertRaisesRegex(ValueError,'MASK_PIXEL_COORDINATES'):self.build()
    def test_mask_roundtrip_and_invalid_runs(self):
        m=np.zeros((14,10),np.uint8);m[2:4,4:8]=1
        np.testing.assert_array_equal(m,object_world.decode_mask(object_world.encode_mask(m)))
        with self.assertRaisesRegex(ValueError,'MASK_RUNS'):object_world.decode_mask({'shape':[2,2],'runs':[[0,5]]})
    def test_blank_current_rgb_is_unknown_not_old_bbox(self):
        record=next(r for r in self.obs[0]['rgb'] if r['camera']=='fixed')
        image=np.array(Image.open(ROOT/'inputs'/record['file']).convert('RGB'))
        mask=object_world.decode_mask(self.masks[('block-01','fixed')]['mask'])
        r=object_tracking.track_view(image,np.zeros_like(image),mask,'fixed',self.protocol['tracker'])
        self.assertIsNone(r['mask']);self.assertEqual(r['association'],'unknown')
    def test_fk_predicts_camera_and_detects_conflicting_pose(self):
        r=object_tracking.fk_camera_consistency(self.obs[0],self.obs[3]);self.assertEqual(r['status'],'pass')
        other=copy.deepcopy(self.obs[3]);other['calibration']['wrist']['pose_world_xyz_wxyz'][0]+=.1
        self.assertEqual(object_tracking.fk_camera_consistency(self.obs[0],other)['status'],'fail')
    def test_update_keeps_historical_3d_separate_and_zero_models(self):
        ref=self.store.publish_world(self.built['state'],{},self.built['provenance'])
        with patch.object(self.head,'submit',side_effect=AssertionError('no learned worker')):
            w=self.head.update(ref['world_id'],self.obs[1]['observation_id'],self.obs[0]['captured_monotonic'])
        e=w['state']['entities']['block-01']
        self.assertEqual(e['status'],'unknown');self.assertIsNone(e['occupancy']);self.assertIsNotNone(e['historical_geometry']['occupancy'])
        self.assertEqual(w['state']['resource_metrics']['segmentation_calls'],0)
        self.assertEqual(w['state']['fk_camera_check']['status'],'pass')
        with self.assertRaisesRegex(ValueError,'STALE_UPDATE_BASE'):self.head.update(ref['world_id'],self.obs[2]['observation_id'],0)
    def test_rebuild_does_not_dispatch(self):
        ref=self.store.publish_world(self.built['state'],{},self.built['provenance'])
        with patch.object(self.head,'submit',side_effect=AssertionError('no dispatch')):
            r=self.head.request_rebuild(ref['world_id'],self.obs[1]['observation_id'],'insufficient 3D',['geometry'])
        self.assertEqual(r['status'],'REQUESTED_NOT_DISPATCHED')

if __name__=='__main__':unittest.main(verbosity=2)
