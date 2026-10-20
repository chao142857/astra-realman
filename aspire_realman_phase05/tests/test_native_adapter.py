from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from cap_harness.contracts import ArmCommand, ExecutionResult, JOINT_DIMENSIONS, Observation, RobotAction, RobotState, SynchronizedTrajectory, Trajectory
from cap_harness.errors import ApiError, ErrorCode
from cap_harness.protocols import EnvironmentAdapter
from aspire_realman import RealManAdapter, CodecConfig, EndpointBinding, TransformEdge, MemorySource, ReplaySource, build_realman_runtime
from aspire_realman import codec
from aspire_realman.fixtures import synthetic_station, MockSegmentation
ROOT = Path(__file__).resolve().parents[2]


def historical_scope(source, arms=('left',)):
    raw = source.read()['canonical_states']; bindings = {}
    # Explicit archived evidence; not a new hardware state/absolute grasp calibration.
    for arm in arms:
        bindings[arm] = EndpointBinding(arm, raw[arm]['work_frame']['id'],raw[arm]['tool_frame']['id'],
            raw[arm]['work_frame']['definition_fingerprint'], raw[arm]['tool_frame']['definition_fingerprint'],
            'ARCHIVED_ZERO_WORK_TOOL_NUMERIC_BINDING; see Phase0 calibration_handoff_1011 / right_wrist_calibration_20261017')
    return CodecConfig(arms, raw[arms[0]]['work_frame']['id'], bindings)


class NativeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.source, self.config = synthetic_station()
        self.adapter = RealManAdapter(self.source, self.config)

    def test_native_registration_and_protocol(self):
        self.assertEqual(JOINT_DIMENSIONS['realman'],6)
        self.assertIsInstance(self.adapter,EnvironmentAdapter)
        state=self.adapter.get_robot_state()
        self.assertIsInstance(state,RobotState)
        self.assertEqual(state.embodiment,'realman')
        self.assertEqual(state.joint_positions['left'].shape,(6,))
        command=ArmCommand('joint_position',[0]*6,embodiment='realman')
        self.assertEqual(command.target.shape,(6,))

    def test_units_and_nonidentity_base_transforms(self):
        s=self.adapter.get_robot_state()
        np.testing.assert_allclose(s.joint_positions['left'],np.deg2rad([0,10,20,30,40,50]))
        np.testing.assert_allclose(s.joint_velocities['left'],np.deg2rad([1,2,3,4,5,6]))
        np.testing.assert_allclose(s.end_effector_poses['left'].position,[.3,.1,.8])
        np.testing.assert_allclose(s.end_effector_poses['right'].position,[-.3,.5,.5])
        np.testing.assert_allclose(s.end_effector_poses['left'].quaternion_wxyz,[2**-.5,0,0,2**-.5])
        self.assertIsNone(s.metadata['pose_endpoint']['left']['actual_grasp_TCP'])

    def test_observation_uses_native_contract_and_optical_parent(self):
        obs=self.adapter.get_observation()
        self.assertIsInstance(obs,Observation)
        c=obs.cameras['synthetic_overhead']
        self.assertEqual(c.frame,'synthetic:camera_optical')
        self.assertEqual(c.camera_pose.frame,'synthetic:work')
        np.testing.assert_allclose(c.camera_pose.position,[.13,-.21,.44])
        self.assertGreater(np.count_nonzero(c.depth_m),0)

    def test_missing_cross_base_transform_cannot_fall_back_to_identity(self):
        bad=replace(self.config,transforms=())
        with self.assertRaisesRegex(codec.ObservationUnavailable,'CALIBRATION_PATH_MISSING'):
            RealManAdapter(self.source,bad).get_robot_state()

    def test_estimated_and_synthetic_transforms_do_not_qualify_real_geometry(self):
        edges=tuple(replace(e,status='ESTIMATED') for e in self.config.transforms)
        with self.assertRaises(codec.ObservationUnavailable):
            RealManAdapter(self.source,replace(self.config,transforms=edges)).get_robot_state()
        data=self.source.read();data['mode']='HISTORICAL_REPLAY'
        with self.assertRaisesRegex(codec.ObservationUnavailable,'BINDING_SOURCE_KIND_MISMATCH'):
            RealManAdapter(MemorySource(data),self.config).get_robot_state()

    def test_changed_frame_fingerprint_is_rejected(self):
        data=self.source.read();data['canonical_states']['left']['work_frame']['definition_fingerprint']='changed'
        with self.assertRaisesRegex(codec.ObservationUnavailable,'FINGERPRINT'):
            RealManAdapter(MemorySource(data),self.config).get_robot_state()

    def test_invalid_sdk_units_and_nonfinite_state(self):
        data=self.source.read();data['canonical_states']['left']['ee_pose']['units']['xyz']='mm'
        with self.assertRaises(codec.ObservationUnavailable):RealManAdapter(MemorySource(data),self.config).get_robot_state()
        data=self.source.read();data['canonical_states']['left']['joint_deg'][0]=float('nan')
        with self.assertRaises(ValueError):RealManAdapter(MemorySource(data),self.config).get_robot_state()
        with self.assertRaises(ValueError):codec.finite([True]*6,(6,))
        with self.assertRaises(ValueError):codec.finite([True,0,0,0,0,0],(6,))
        with self.assertRaises(ValueError):codec.finite(['1']*6,(6,))

    def test_gripper_feedback_validation(self):
        for value in [True,-1,1001,float('nan')]:
            data=self.source.read();data['canonical_states']['left']['gripper_state']['position']=value
            with self.assertRaises(codec.ObservationUnavailable):RealManAdapter(MemorySource(data),self.config).get_robot_state()

    def test_unknown_extrinsic_is_only_a_self_pose_and_has_no_usable_depth(self):
        data=self.source.read();data['cameras'][0]['calibration_status']='UNKNOWN'
        adapter=RealManAdapter(MemorySource(data),self.config)
        c=adapter.get_observation().cameras['synthetic_overhead']
        self.assertEqual(c.camera_pose.frame,c.frame)
        self.assertEqual(np.count_nonzero(c.depth_m),0)
        self.assertFalse(adapter.monitor_snapshot()['camera_metadata']['synthetic_overhead']['geometry_eligible'])

    def test_rgb_only_camera_never_invents_depth(self):
        data=self.source.read();data['cameras'][0].pop('depth_m')
        c=RealManAdapter(MemorySource(data),self.config).get_observation().cameras['synthetic_overhead']
        self.assertFalse(np.any(c.depth_m))
        self.assertEqual(c.camera_pose.frame,c.frame)

    def test_wrist_pose_uses_dynamic_endpoint_and_rejects_time_skew(self):
        data=self.source.read();cam=data['cameras'][0]
        cam['parent_frame']='synthetic:left:Arm_Tip'
        adapter=RealManAdapter(MemorySource(data),self.config)
        state=adapter.get_robot_state();c=adapter.get_observation().cameras['synthetic_overhead']
        expected=state.end_effector_poses['left'].as_matrix()@cam['T_parent_camera_optical']
        np.testing.assert_allclose(c.camera_pose.as_matrix(),expected,atol=1e-8)
        cam['captured_at']-=1
        c=RealManAdapter(MemorySource(data),self.config).get_observation().cameras['synthetic_overhead']
        self.assertEqual(c.camera_pose.frame,c.frame)
        self.assertFalse(np.any(c.depth_m))

    def test_bad_and_contradictory_transform_graphs(self):
        with self.assertRaises(ValueError):TransformEdge('a','b',np.zeros((4,4)),'VERIFIED','test')
        with self.assertRaises(ValueError):TransformEdge('a','b',np.eye(4),'UNKNOWN','test')
        inverse=np.linalg.inv(self.config.transforms[0].matrix);inverse[0,3]+=.1
        wrong=TransformEdge(self.config.transforms[0].source,'synthetic:work',inverse,'SYNTHETIC','explicit test')
        with self.assertRaisesRegex(ValueError,'CONTRADICTORY'):
            replace(self.config,transforms=self.config.transforms+(wrong,))

    def test_all_raw_command_methods_refuse_before_payload(self):
        class Poison:
            def __iter__(self):raise AssertionError('payload inspected')
        for method in ['step','execute_trajectory','set_gripper','set_grippers']:
            r=getattr(self.adapter,method)(Poison())
            self.assertFalse(r.ok)
            self.assertEqual(r.error.code,ErrorCode.SAFETY_INTERLOCK)
        self.assertEqual(self.adapter.go_home().error.code,ErrorCode.SAFETY_INTERLOCK)
        with self.assertRaises(ApiError):self.adapter.reset(None,0)
        self.assertEqual(self.adapter.hardware_commands_sent,0)
        with self.assertRaises(AttributeError):self.adapter.physical_motion_authorized=True
        with self.assertRaises(TypeError):RealManAdapter(self.source,self.config,allow_motion=True)

    def test_native_trajectory_and_synchronized_trajectory_are_refused(self):
        state=self.adapter.get_robot_state()
        t=Trajectory(np.array([state.joint_positions['left']]*2),.02,state.joint_names['left'],'mock',False,state,arm='left',embodiment='realman')
        sync=SynchronizedTrajectory({a:np.array([state.joint_positions[a]]*2) for a in state.arms},.02,state.joint_names,'mock',False,state,embodiment='realman')
        self.assertEqual(self.adapter.execute_trajectory(t).steps_executed,0)
        self.assertEqual(self.adapter.execute_trajectory(sync).steps_executed,0)

    def test_runtime_preserves_native_classes_and_no_home_inference(self):
        runtime=build_realman_runtime(self.source,self.config,segmentation_provider=MockSegmentation())
        try:
            self.assertEqual(type(runtime.api).__name__,'CapApi')
            self.assertEqual(type(runtime.runtime).__name__,'EmbeddedAgentRuntime')
            self.assertEqual(runtime.api._home_joint_positions,{})
            self.assertTrue(runtime.api.localize_object('synthetic object').ok)
            with self.assertRaisesRegex(codec.ObservationUnavailable,'REALMAN_MODEL'):
                runtime.adapter.get_planning_context()
        finally:runtime.close()

    def test_cache_publishes_coherent_updates_and_rejects_old_sequence(self):
        runtime=build_realman_runtime(self.source,self.config)
        try:
            before=runtime.runtime.session.visual_snapshot()
            snapshot=self.source.read();snapshot['sequence']=2
            snapshot['canonical_states']['left']['joint_deg'][0]=12
            snapshot['cameras'][0]['rgb'][:,:,:]=32
            self.source.publish(snapshot)
            after=runtime.runtime.session.visual_snapshot()
            self.assertEqual(after['observation_seq'],2)
            self.assertNotEqual(before['camera_metadata']['synthetic_overhead']['frame_hash'],after['camera_metadata']['synthetic_overhead']['frame_hash'])
            self.assertAlmostEqual(after['state']['left_joint_pos'][0],np.deg2rad(12))
            with self.assertRaisesRegex(ValueError,'SEQUENCE'):self.source.publish(snapshot)
            snapshot['sequence']=3;snapshot['cameras']=[];self.source.publish(snapshot)
            cache=runtime.runtime.session.visual_snapshot()
            self.assertTrue(cache['camera_metadata']['synthetic_overhead']['missing'])
            self.assertTrue(cache['stale'])
        finally:runtime.close()

    def test_camera_role_serial_cannot_silently_change(self):
        snapshot=self.source.read();snapshot['sequence']=2;snapshot['cameras'][0]['serial']='OTHER'
        self.source.publish(snapshot)
        with self.assertRaisesRegex(codec.ObservationUnavailable,'ROLE_SERIAL_CHANGED'):self.adapter.get_observation()

    def test_source_is_snapshot_not_hardware_factory(self):
        class Hardware:
            def read(self):raise AssertionError('hardware polled')
        with self.assertRaises(TypeError):RealManAdapter(Hardware(),self.config)
        snap=self.source.read();snap['canonical_states']['left']['joint_deg'][0]=100
        self.assertEqual(self.source.read()['canonical_states']['left']['joint_deg'][0],0)
        self.adapter.close();self.adapter.close()
        with self.assertRaises(RuntimeError):self.adapter.get_robot_state()


class HistoricalReplayTests(unittest.TestCase):
    def setUp(self):
        self.source=ReplaySource(ROOT/'aspire_realman_phase0/evidence/replay_snapshot.json')
        self.config=historical_scope(self.source)
        self.adapter=RealManAdapter(self.source,self.config)

    def test_actual_recorded_left_state_is_native_without_shared_world(self):
        state=self.adapter.get_robot_state();raw=self.source.read()['canonical_states']['left']
        self.assertEqual(state.arms,('left',))
        self.assertEqual(state.base_frame,'realman:left:work:World')
        np.testing.assert_allclose(state.joint_positions['left'],np.deg2rad(raw['joint_deg']))
        np.testing.assert_allclose(state.end_effector_poses['left'].position,raw['ee_pose']['xyz_m'])
        self.assertEqual(state.metadata['joint_velocity_quality']['left'],'UNMEASURED_NUMERIC_PLACEHOLDER')
        self.assertEqual(state.metadata['pose_endpoint']['left']['raw_frame_semantics'],'UNKNOWN')
        self.assertFalse(state.metadata['motion_permitted'])

    def test_dual_historical_state_refuses_missing_real_base_transform(self):
        config=historical_scope(self.source,('left','right'))
        with self.assertRaisesRegex(codec.ObservationUnavailable,'CALIBRATION_PATH_MISSING'):
            RealManAdapter(self.source,config).get_robot_state()

    def test_metadata_cannot_succeed_as_pixel_observation(self):
        with self.assertRaisesRegex(codec.ObservationUnavailable,'NO_LOADED_CAMERA_PIXELS'):
            self.adapter.get_observation()
        snap=self.adapter.monitor_snapshot()
        self.assertEqual(snap['cameras'],{})
        self.assertTrue(all(c['missing'] for c in snap['camera_metadata'].values()))

    def test_explicit_replay_assets_require_hash_and_root(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'img.png';Image.fromarray(np.zeros((4,4,3),dtype=np.uint8)).save(image)
            snapshot=self.source.read();snapshot['cameras'][0]['image_path']='img.png';snapshot['cameras'][0]['sha256']=hashlib.sha256(image.read_bytes()).hexdigest()
            snapshot['cameras']=snapshot['cameras'][:1];snapshot['cameras'][0]['shape']=[4,4,3]
            record=root/'record.json';record.write_text(json.dumps(snapshot))
            source=ReplaySource(record,assets_root=root);obs=RealManAdapter(source,self.config).get_observation()
            self.assertEqual(obs.cameras['left_wrist'].rgb.shape,(4,4,3))
            self.assertFalse(np.any(obs.cameras['left_wrist'].depth_m))
            snapshot['cameras'][0]['sha256']='0'*64;record.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):ReplaySource(record,assets_root=root)
            snapshot['cameras'][0]['image_path']=str(Path(__file__).resolve());record.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(ValueError,'OUTSIDE'):ReplaySource(record,assets_root=root)


class PlanningReadinessTests(unittest.TestCase):
    def test_real_model_requirements_remain_missing_without_fake_defaults(self):
        from aspire_realman.planning import planning_readiness
        manifest=json.loads((ROOT/'aspire_realman_phase05/model_requirements.json').read_text())
        report=planning_readiness(manifest)
        self.assertFalse(report['ready_for_physical_planning'])
        self.assertFalse(report['offline_artifacts_complete'])
        self.assertIn('right_base_to_work',report['missing'])
        self.assertIn('left_actual_tcp',report['missing'])
        self.assertIsNone(manifest['right_base_to_work'])
