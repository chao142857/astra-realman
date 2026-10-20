"""Focused software regressions only; injected pixels never count as live evidence."""
import time
import unittest
import numpy as np
from aspire_realman_live.source import LiveSource
from aspire_realman_live.quality import camera_quality
from aspire_realman_live.runtime import build_live_runtime


def fixture():
    now = time.time()
    return {'role':'tabletop','serial':'346222072496','rgb':np.zeros((4,5,3),np.uint8),
        'depth_m':np.ones((4,5),np.float32),'intrinsics':[[10,0,2],[0,10,2],[0,0,1]],
        'intrinsics_source':'INJECTED_UNIT_TEST_ONLY','host_clock_id':'test-boot',
        'alignment':'depth_to_color','depth_unit':'m','captured_at':now,
        'received_monotonic_s':time.monotonic(),'color_timestamp_ms':now*1000,'depth_timestamp_ms':now*1000,
        'color_timestamp_domain':'timestamp_domain.global_time','depth_timestamp_domain':'timestamp_domain.global_time',
        'color_frame_number':10,'depth_frame_number':10}


class QualityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.source=LiveSource('unit-test-only',clock_id='test-boot')
        self.camera=fixture()
        self.source.publish(self.camera,owner_id='unit-test-only')

    def test_stopped_owner_retains_original_stamp_and_native_cache_stale(self):
        runtime=build_live_runtime(self.source)
        try:
            before=runtime.runtime.session.visual_snapshot()
            self.source.close()
            after=runtime.runtime.session.visual_snapshot()
            self.assertEqual(before['timestamp_s'],after['timestamp_s'])
            self.assertTrue(after['stale'])
            self.assertEqual(after['state'],{})
        finally: runtime.close()

    def test_old_exposure_cannot_be_refreshed_by_current_receipt(self):
        c=self.camera.copy();c['color_timestamp_ms']-=60000;c['depth_timestamp_ms']-=60000
        q=camera_quality(c,self.source.read())
        self.assertTrue(q['stale']);self.assertGreater(q['age_ms'],59000)
        self.assertFalse(q['exposure_freshness_verified'])

    def test_device_clock_cannot_be_compared_to_host_or_arm(self):
        c=self.camera.copy();c['color_timestamp_domain']='hardware_clock'
        q=camera_quality(c,self.source.read())
        self.assertTrue(q['stale']);self.assertIsNone(q['device_color_depth_skew_ms'])
        self.assertIsNone(q['camera_arm_skew_ms']['left'])

    def test_depth_missing_invalid_and_temporal_skew_are_ineligible(self):
        for z in [np.zeros((4,5),np.float32),np.full((4,5),np.nan,np.float32)]:
            c=self.camera.copy();c['depth_m']=z
            self.assertFalse(camera_quality(c,self.source.read())['depth_usable_for_optical_inspection'])
        c=self.camera.copy();c['depth_timestamp_ms']-=100
        self.assertFalse(camera_quality(c,self.source.read())['color_depth_temporally_eligible'])

    def test_repeated_frame_wrong_role_and_other_owner_rejected(self):
        with self.assertRaises(ValueError):self.source.publish(self.camera,owner_id='unit-test-only')
        c=self.camera.copy();c['serial']='unknown'
        with self.assertRaises(ValueError):self.source.publish(c,owner_id='unit-test-only')
        with self.assertRaises(ValueError):self.source.publish(self.camera,owner_id='someone-else')

    def test_state_observation_and_planning_do_not_fallback(self):
        runtime=build_live_runtime(self.source)
        try:
            for fn in [runtime.adapter.get_robot_state,runtime.adapter.get_observation,runtime.adapter.get_planning_context]:
                with self.assertRaises(RuntimeError):fn()
            self.assertFalse(any(runtime.api.configured_providers.values()))
            self.assertFalse(runtime.adapter.set_gripper(.5).ok)
            self.assertFalse(runtime.adapter.execute_trajectory(None).ok)
            self.assertFalse(runtime.adapter.go_home().ok)
            from cap_harness.contracts import StepResult
            self.assertIsInstance(runtime.api.step(None),StepResult)
            self.assertEqual(runtime.api.move_to_pose(None).error.code.value,'safety_interlock')
            self.assertEqual(runtime.adapter.hardware_commands_sent,0)
        finally:runtime.close()
