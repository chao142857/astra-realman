"""RGB-D contract/failure tests using saved public sensors; no model or physics."""
import copy
import json
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research import rgbd_world, geometry_quality
from platform_v1.research.da3_geometry import calibrated_cameras
from platform_v1.research.object_world import project

ROOT=Path(__file__).resolve().parents[3]/'rgbd-world-20261009'

class RGBDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/'inputs/D0_control/observations.json').exists():raise unittest.SkipTest('RGBD diagnostic archive not installed')
        cls.observations=json.loads((ROOT/'inputs/D0_control/observations.json').read_text())
        cls.config=json.loads((ROOT/'PROTOCOL.json').read_text())
        cls.saved=json.loads((ROOT/'results/D0_01/build.json').read_text())
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.obs=copy.deepcopy(self.observations)
        self.store=PublicStore(ROOT/'inputs/D0_control/public',self.obs[0]['episode_id'])
        for o in self.obs:self.store.observe(o,o['execution_epoch'])
        self.epoch=[self.obs[0]['execution_epoch']]
        self.head=WorldHead(Path(self.temp.name),self.store,epoch=lambda:self.epoch[0],deadline=time.monotonic()+600,emit=lambda *x:None)
        self.head.public_plane=self.saved['state']['public_plane']
    def tearDown(self):self.temp.cleanup()
    def bad_store(self,edit):
        o=copy.deepcopy(self.obs[0]);edit(o)
        store=PublicStore(self.store.root,o['episode_id']);store.observe(o,o['execution_epoch']);return store
    def reference(self):return self.store.publish_world(self.saved['state'],{},self.saved['provenance'])
    def test_true_sensor_data_metric_and_aligned(self):
        d,v,r=self.store.depth(self.obs[0]['observation_id'],'fixed')
        self.assertEqual(d.dtype,np.float32);self.assertEqual(d.shape,(480,640));self.assertGreater(v.sum(),10000)
        self.assertTrue(np.all(d[~v]==0));self.assertEqual(r['unit'],'m')
        self.assertEqual(r['simulation_step'],self.obs[0]['state']['sim_step'])
    def test_units_not_silently_converted(self):
        s=self.bad_store(lambda o:o['depth'][0].update(unit='mm'))
        with self.assertRaisesRegex(ValueError,'DEPTH_UNITS'):s.depth(self.obs[0]['observation_id'],'assembly')
    def test_resize_alignment_rejected(self):
        s=self.bad_store(lambda o:o['depth'][0]['alignment'].update(resize=[320,240]))
        with self.assertRaisesRegex(ValueError,'ALIGNMENT'):s.depth(self.obs[0]['observation_id'],'assembly')
    def test_depth_hash_rejected(self):
        s=self.bad_store(lambda o:o['depth'][0]['depth'].update(sha256='0'*64))
        with self.assertRaisesRegex(ValueError,'DEPTH_HASH'):s.depth(self.obs[0]['observation_id'],'assembly')
    def test_rgb_binding_rejected(self):
        s=self.bad_store(lambda o:o['depth'][0].update(aligned_rgb_sha256='0'*64))
        with self.assertRaisesRegex(ValueError,'DEPTH_RGB_HASH'):s.depth(self.obs[0]['observation_id'],'assembly')
    def test_path_escape_rejected(self):
        s=self.bad_store(lambda o:o['depth'][0]['depth'].update(file='../private/truth.npy'))
        with self.assertRaisesRegex(ValueError,'PATH_ESCAPE'):s.depth(self.obs[0]['observation_id'],'assembly')
    def test_old_frame_or_unsynchronized_depth_rejected(self):
        s=self.bad_store(lambda o:o['depth'][0].update(simulation_step=o['state']['sim_step']-1))
        with self.assertRaisesRegex(ValueError,'SYNC'):s.depth(self.obs[0]['observation_id'],'assembly')
        s=self.bad_store(lambda o:o['depth'][0].update(frame_id='another_frame'))
        with self.assertRaisesRegex(ValueError,'FRAME_BINDING'):s.depth(self.obs[0]['observation_id'],'assembly')
    def test_camera_roundtrip_no_GT(self):
        ext,k=calibrated_cameras(self.obs[0]);d,v,_=self.store.depth(self.obs[0]['observation_id'],'fixed')
        mask=np.zeros(v.shape,np.uint8);mask[120:160:8,200:260:8]=1
        points=rgbd_world.backproject(d,v,mask,ext[1],k[1]);uv,z=project(points,ext[1],k[1])
        y,x=np.where(v & (mask>0))
        np.testing.assert_allclose(uv,np.column_stack([x,y]),atol=.0001)
        np.testing.assert_allclose(z,d[y,x],atol=1e-6)
    def test_missing_or_duplicate_depth_cameras_rejected(self):
        s=self.bad_store(lambda o:o['depth'].pop())
        with self.assertRaisesRegex(ValueError,'THREE_DEPTH_CAMERAS'):
            s.depth(self.obs[0]['observation_id'],'assembly')
        s=self.bad_store(lambda o:o['depth'][1].update(camera='assembly'))
        with self.assertRaisesRegex(ValueError,'THREE_DEPTH_CAMERAS'):
            s.depth(self.obs[0]['observation_id'],'assembly')
    def test_nonfinite_sensor_timestamps_rejected(self):
        for key in ('sensor_timestamp','readback_completed_monotonic'):
            # PublicStore's strict JSON boundary rejects these even before depth loading.
            with self.assertRaisesRegex(ValueError,'Out of range float'):
                self.bad_store(lambda o:o['depth'][0].update({key:float('inf')}))
    def test_build_and_update_no_worker_or_broker_dispatch(self):
        reference=self.reference();self.epoch[0]=self.obs[1]['execution_epoch']
        with patch.object(self.head,'submit',side_effect=AssertionError('no model dispatch')):
            world=self.head.update(reference['world_id'],self.obs[1]['observation_id'],self.obs[1]['execution_feedback']['completed_monotonic'])
        e=world['state']['entities']['block-01'];self.assertEqual(e['measurement_kind'],'current_depth_region')
        self.assertNotEqual(e['observation_id'],reference['state']['observation_id'])
        self.assertEqual(world['state']['execution_feedback'],self.obs[1]['execution_feedback'])
        self.assertEqual(world['state']['resource_metrics']['SAM_calls'],0)
        self.assertFalse(world['state']['rebuild_dispatches_model'])
        with self.assertRaisesRegex(ValueError,'STALE_UPDATE'):self.head.update(reference['world_id'],self.obs[2]['observation_id'],0)
    def test_future_completion_and_feedback_rejected(self):
        ref=self.reference();self.epoch[0]=self.obs[1]['execution_epoch']
        with self.assertRaisesRegex(ValueError,'BEFORE_COMPLETION'):
            self.head.update(ref['world_id'],self.obs[1]['observation_id'],self.obs[1]['captured_monotonic']+1)
        bad=copy.deepcopy(self.obs[1]);bad['execution_feedback']['completed_monotonic']=bad['captured_monotonic']+1
        self.store.observations[bad['observation_id']]=bad # explicit test injection only
        with self.assertRaisesRegex(ValueError,'FUTURE_EXECUTION'):
            self.head.update(ref['world_id'],bad['observation_id'],0)
    def test_invalid_execution_evidence_cannot_be_usable(self):
        ref=self.reference();self.epoch[0]=self.obs[1]['execution_epoch']
        bad=copy.deepcopy(self.obs[1]);bad['execution_feedback']['ok']=False
        self.store.observations[bad['observation_id']]=bad
        world=self.head.update(ref['world_id'],bad['observation_id'],0)
        self.assertTrue(all(e['status']=='unknown' for e in world['state']['entities'].values()))
    def test_empty_depth_unknown_with_history_not_stale_geometry(self):
        ref=self.reference();self.epoch[0]=self.obs[1]['execution_epoch'];original=self.store.depth
        def empty(oid,camera):
            d,v,r=original(oid,camera);return np.zeros_like(d),np.zeros_like(v),r
        with patch.object(self.store,'depth',side_effect=empty):
            world=self.head.update(ref['world_id'],self.obs[1]['observation_id'],0)
        e=world['state']['entities']['block-01'];self.assertEqual(e['status'],'unknown')
        self.assertEqual(e['surface_cloud'],[]);self.assertIsNone(e['point_world_m'])
        self.assertTrue(e['historical_geometry']['surface_cloud']);self.assertEqual(world['state']['scene_layers']['static']['current_support_count'],0)
    def test_duplicate_instance_geometry_claims_unknown(self):
        entities=copy.deepcopy(self.saved['state']['entities']);entities['copy']=copy.deepcopy(entities['block-01'])
        rgbd_world.reject_identity_conflicts(entities)
        self.assertEqual(entities['copy']['reason'],'INSTANCE_MASK_COMPETITION')
        self.assertIsNone(entities['block-01']['point_world_m'])
    def test_dynamic_geometry_not_accumulated_as_static(self):
        rows=json.loads((ROOT/'results/public_replays/D1_v2/updates.json').read_text())
        first=rows[0]['world']['state'];e=first['entities']['block-01']
        self.assertEqual(e['status'],'coarse');self.assertEqual(e['motion'],'moving')
        self.assertGreater(np.linalg.norm(np.array(e['point_world_m'])-e['historical_geometry']['point_world_m']),.1)
        self.assertEqual(first['scene_layers']['unassigned_current']['temporal_fusion'],False)
        self.assertLessEqual(np.array(first['scene_layers']['static']['points'])[:,2].max(),.005)
    def test_depth_occlusion_unknown_and_recovery(self):
        rows=json.loads((ROOT/'results/public_replays/D1_v2/updates.json').read_text())
        hidden=rows[-2]['world']['state']['entities']['block-01'];recovered=rows[-1]['world']['state']['entities']['block-01']
        self.assertEqual(hidden['status'],'unknown');self.assertIn('occluded',hidden['visibility'].values())
        self.assertTrue(hidden['historical_geometry']['surface_cloud']);self.assertEqual(recovered['status'],'coarse')
    def test_shadow_and_physical_admission_still_require_task_evidence(self):
        ref=self.reference()
        with self.assertRaisesRegex(ValueError,'NOT_TASK_USABLE'):geometry_quality.require_task_usable(ref,{'object_id':'block-01'})
        self.assertEqual(self.store.get_object(ref['world_id'],'block-01')['grants_execution'],False)
    def test_rebuild_never_automatically_dispatches_model(self):
        ref=self.reference()
        with patch.object(self.head,'submit',side_effect=AssertionError('no model dispatch')):
            request=self.head.request_rebuild(ref['world_id'],self.obs[0]['observation_id'],'depth unknown',['geometry'])
        self.assertEqual(request['status'],'REQUESTED_NOT_DISPATCHED')

if __name__=='__main__':unittest.main(verbosity=2)
