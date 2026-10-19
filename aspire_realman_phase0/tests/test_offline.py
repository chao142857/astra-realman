import ast
import copy
import json
import math
from pathlib import Path
import unittest
from aspire_realman_phase0 import OfflineRealManAdapter, ReplaySource, rpy_rad_to_wxyz

ROOT = Path(__file__).resolve().parents[1]


class OfflineSafetyTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((ROOT/'evidence/replay_snapshot.json').read_text())
        self.adapter = OfflineRealManAdapter(ReplaySource(self.snapshot))

    def test_original_sample_provenance(self):
        self.assertIn('step-001/after/observation.json', self.snapshot['provenance']['source_path'])
        self.assertEqual(len(self.snapshot['provenance']['raw_file_sha256']), 64)
        self.assertEqual(len(self.adapter.get_observation()['cameras']), 4)

    def test_joint_degrees_converted_once(self):
        state = self.adapter.get_robot_state()['arms']['left']
        self.assertAlmostEqual(state['joint_positions_rad'][0], math.radians(self.snapshot['canonical_states']['left']['joint_deg'][0]))
        self.assertEqual(state['reported_endpoint_pose']['position_m'], self.snapshot['canonical_states']['left']['ee_pose']['xyz_m'])

    def test_sdk_unknown_frames_preserved(self):
        state = self.adapter.get_robot_state()
        self.assertIsNone(state['common_base_frame'])
        self.assertIsNone(state['T_left_base_right_base'])
        self.assertFalse(state['native_robot_state_ready'])
        for arm in state['arms'].values():
            self.assertIsNone(arm['actual_grasp_tcp_transform'])
            self.assertIsNone(arm['reported_endpoint_pose']['reference_frame'])
            self.assertEqual(arm['reported_endpoint_pose']['frame_semantics_status'], 'UNKNOWN')

    def test_gripper_is_opening_not_grasp(self):
        raw = self.snapshot['canonical_states']['right']['gripper_state']['position']
        state = self.adapter.get_robot_state()['arms']['right']
        self.assertEqual(state['gripper_opening'], raw/1000)
        self.assertEqual(state['grasp_confirmed'], 'UNKNOWN')

    def test_missing_velocity_not_fabricated_zero(self):
        state = self.adapter.get_robot_state()['arms']['left']
        self.assertIsNone(state['joint_velocities_rad_s'])
        self.assertFalse(state['velocity_valid'])

    def test_replay_never_fresh_live(self):
        obs = self.adapter.get_observation()
        self.assertFalse(obs['fresh_live_observation'])
        self.assertFalse(obs['pixel_arrays_loaded'])
        self.assertEqual(obs['exposure_synchronized'], 'UNKNOWN')

    def test_filter_and_unknown_camera(self):
        self.assertEqual(len(self.adapter.get_observation('right_wrist')['cameras']), 1)
        with self.assertRaises(ValueError):self.adapter.get_observation('new_usb_camera')
        with self.assertRaises(ValueError):self.adapter.get_observation([])
        with self.assertRaises(ValueError):self.adapter.get_observation(['left_wrist','left_wrist'])

    def test_all_motion_paths_reject_before_payload_access(self):
        # A payload that fails if inspected shows rejection precedes planning/dispatch.
        class Poison:
            def __iter__(self):raise AssertionError('command payload touched')
        for method in ['move_to_pose','move_to_joints','move_synchronized','set_gripper','set_grippers','step','execute_trajectory']:
            with self.subTest(method=method):
                result = getattr(self.adapter, method)(Poison())
                self.assertEqual(result['error'], 'SAFETY_INTERLOCK')
                self.assertFalse(result['dispatch_attempted'])
                self.assertEqual(result['hardware_commands_sent'], 0)
                self.assertEqual(result['steps_executed'], 0)
        for method in ['go_home','reset','open_gripper','close_gripper']:
            self.assertEqual(getattr(self.adapter, method)()['error'], 'SAFETY_INTERLOCK')

    def test_motion_cannot_be_enabled(self):
        with self.assertRaises(TypeError):OfflineRealManAdapter(ReplaySource(self.snapshot), allow_motion=True)
        with self.assertRaises(AttributeError):self.adapter.physical_motion_authorized = True
        self.assertFalse(self.adapter.physical_motion_authorized)

    def test_injected_hardware_source_rejected(self):
        class HardwareSource:
            def read(self):raise AssertionError('hardware was polled')
        with self.assertRaises(TypeError):OfflineRealManAdapter(HardwareSource())

    def test_metadata_paths_never_opened(self):
        self.snapshot['cameras'][0]['image_path'] = '/dev/video0'
        adapter = OfflineRealManAdapter(ReplaySource(self.snapshot))
        self.assertFalse(adapter.get_observation()['pixel_arrays_loaded'])

    def test_no_geometry_fabricated_from_rgb(self):
        result = self.adapter.localize_object('object', camera_name='left_wrist', target_frame='shared_work')
        self.assertFalse(result['ok'])
        self.assertIsNone(result['geometry'])
        self.assertEqual(result['hardware_commands_sent'], 0)

    def test_replay_defensive_copy(self):
        original = self.adapter.get_robot_state()['arms']['left']['joint_positions_rad'][0]
        self.snapshot['canonical_states']['left']['joint_deg'][0] = 99
        self.adapter.get_observation()['cameras'].clear()
        self.assertEqual(self.adapter.get_robot_state()['arms']['left']['joint_positions_rad'][0], original)
        self.assertEqual(len(self.adapter.get_observation()['cameras']), 4)

    def test_invalid_arm_units_and_frame_snapshot(self):
        for field,value in [('arm','right'),('frame_snapshot_stable',False),('joint_deg',[float('nan')]*6)]:
            snap=copy.deepcopy(self.snapshot);snap['canonical_states']['left'][field]=value
            with self.assertRaises(ValueError):OfflineRealManAdapter(ReplaySource(snap)).get_robot_state()
        self.snapshot['canonical_states']['left']['ee_pose']['units']['xyz']='mm'
        with self.assertRaises(ValueError):OfflineRealManAdapter(ReplaySource(self.snapshot)).get_robot_state()

    def test_nonfinite_or_out_of_range_gripper(self):
        for value in [float('nan'),1001,-1,True]:
            self.snapshot['canonical_states']['left']['gripper_state']['position']=value
            with self.assertRaises(ValueError):OfflineRealManAdapter(ReplaySource(self.snapshot)).get_robot_state()

    def test_explicit_replay_required(self):
        with self.assertRaises(ValueError):ReplaySource({'mode':'LIVE'})

    def test_rpy_quaternion_axis_and_norm(self):
        q=rpy_rad_to_wxyz([0,0,math.pi/2])
        for a,b in zip(q,[math.sqrt(0.5),0,0,math.sqrt(0.5)]):self.assertAlmostEqual(a,b)
        q=rpy_rad_to_wxyz([1.2,-0.7,2.4])
        self.assertAlmostEqual(sum(v*v for v in q),1)
        with self.assertRaises(ValueError):rpy_rad_to_wxyz([True,0,0])

    def test_real_calibration_matrices_are_rigid_but_stay_estimates(self):
        inventory=json.loads((ROOT/'evidence/camera_transform_inventory.json').read_text())
        self.assertEqual(len(inventory['cameras']),4)
        for camera in inventory['cameras']:
            t=camera['T_parent_camera_optical']; r=[row[:3] for row in t[:3]]
            self.assertEqual(t[3],[0,0,0,1])
            for i in range(3):
                for j in range(3):self.assertAlmostEqual(sum(r[k][i]*r[k][j] for k in range(3)),float(i==j),places=6)
            det=sum(r[0][i]*(r[1][(i+1)%3]*r[2][(i+2)%3]-r[1][(i+2)%3]*r[2][(i+1)%3]) for i in range(3))
            self.assertAlmostEqual(det,1,places=6)
            self.assertEqual(camera['evidence_status'],'ESTIMATED_NOT_INDEPENDENTLY_CERTIFIED')
            self.assertFalse(camera['execution_authorization'])
        self.assertIsNone(inventory['common_world_transform'])

    def test_offline_module_has_no_transport_imports(self):
        import aspire_realman_phase0.offline as module
        tree=ast.parse(Path(module.__file__).read_text())
        imports=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imports.update(v.name.split('.')[0] for v in node.names)
            elif isinstance(node,ast.ImportFrom):imports.add(node.module.split('.')[0])
        self.assertEqual(imports,{'copy','json','math','pathlib'})
