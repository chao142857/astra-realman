"""Optional checks of UNMODIFIED pinned ASPIRE core; all data is synthetic.
No SDK, camera, model server, MCP HTTP listener or physical dispatcher is created.
The yam_real identity below belongs only to the upstream synthetic test fixture;
recorded RealMan data is never relabelled as YAM to bypass the contract registry.
"""
import math
import unittest

try:
    import numpy as np
    from cap_harness.api import CapApi
    from cap_harness.agent.embedded import EmbeddedAgentRuntime
    from cap_harness.agent.mcp import _pose_input_schema
    from cap_harness.contracts import (CameraObservation, ExecutionResult, JOINT_DIMENSIONS,
        Observation, Pose, RobotState, Segmentation, SegmentationSet, Trajectory)
    from cap_harness.errors import ApiError, ErrorCode
    from cap_harness.geometry import pose_from_mapping
    from cap_harness.registry import ToolRegistry
    AVAILABLE=True
except ImportError:
    AVAILABLE=False


@unittest.skipUnless(AVAILABLE, 'native core requires pinned ASPIRE source and existing NumPy runtime')
class NativeCoreTests(unittest.TestCase):
    def setUp(self):
        class SyntheticFixture:
            embodiment='yam_real'  # Only a synthetic fixture for existing upstream types.
            def __init__(self):self.refusals=0
            def get_robot_state(self):
                return RobotState(
                    joint_positions={a:np.zeros(6) for a in ('left','right')},
                    joint_velocities={a:np.zeros(6) for a in ('left','right')},
                    end_effector_poses={a:Pose([0,0,0],[1,0,0,0],'synthetic_fixture') for a in ('left','right')},
                    gripper_positions={'left':0.5,'right':0.5},base_frame='synthetic_fixture',embodiment='yam_real')
            def get_observation(self):
                return Observation(cameras={'synthetic_rgbd':CameraObservation(
                    rgb=np.zeros((4,4,3),dtype=np.uint8),depth_m=np.array([[0.9,1,1.1,1.2],[1,1.05,1.15,1.3],[1.1,0.95,1.2,1.4],[1.05,1.25,1.35,1.5]]),
                    intrinsics=[[10,0,1.5],[0,10,1.5],[0,0,1]],frame='synthetic_camera_optical',
                    camera_pose=Pose([0.2,0.3,0.4],[1,0,0,0],'synthetic_fixture'))},robot_state=self.get_robot_state())
            def set_gripper(self,position,*,arm):
                self.refusals+=1
                return ExecutionResult(ok=False,steps_executed=0,error=ApiError(ErrorCode.SAFETY_INTERLOCK,'synthetic fixture has no hardware transport'))
            def execute_trajectory(self,trajectory):return self.set_gripper(0,arm='left')
        class MaskFixture:
            def segment_text(self,camera,text):
                return SegmentationSet(ok=True,segmentations=[Segmentation(
                    mask=np.ones((4,4),dtype=bool),label=text,score=1,camera_name='synthetic_rgbd',frame=camera.frame)])
        self.adapter=SyntheticFixture()
        self.api=CapApi(self.adapter,segmentation_provider=MaskFixture(),default_camera='synthetic_rgbd')

    def test_realman_embodiment_is_rejected_not_silently_aliased(self):
        self.assertNotIn('realman',JOINT_DIMENSIONS)
        with self.assertRaisesRegex(ValueError,'unsupported embodiment'):
            RobotState(joint_positions=[0]*6,joint_velocities=[0]*6,
                end_effector_poses=Pose([0,0,0],[1,0,0,0],'realman:left:work:World'),
                gripper_positions=0.5,base_frame='realman:left:work:World',embodiment='realman')

    def test_native_common_frame_contract_rejects_separate_bases(self):
        with self.assertRaisesRegex(ValueError,'expected'):
            RobotState(joint_positions={'left':[0]*6,'right':[0]*6},joint_velocities={'left':[0]*6,'right':[0]*6},
                end_effector_poses={'left':Pose([0,0,0],[1,0,0,0],'left_work'),'right':Pose([0,0,0],[1,0,0,0],'right_work')},
                gripper_positions={'left':0.5,'right':0.5},base_frame='shared_work',embodiment='yam_real')

    def test_native_pose_schema_and_degree_conversion(self):
        self.assertEqual(_pose_input_schema()['oneOf'],[{'required':['quaternion_wxyz']},{'required':['rpy_deg']}])
        p=pose_from_mapping({'position':[0.1,0.2,0.3],'rpy_deg':[0,0,90],'frame':'synthetic_fixture'})
        np.testing.assert_allclose(p.quaternion_wxyz,[math.sqrt(0.5),0,0,math.sqrt(0.5)],atol=1e-8)
        with self.assertRaises(ValueError):pose_from_mapping({'position':[0,0,0],'frame':'x','rpy_deg':[0,0,0],'quaternion_wxyz':[1,0,0,0]})

    def test_native_observation_and_state(self):
        self.assertEqual(self.api.get_robot_state().arms,('left','right'))
        self.assertEqual(tuple(self.api.get_observation('synthetic_rgbd').cameras),('synthetic_rgbd',))

    def test_native_localization_with_mock_mask_and_synthetic_depth(self):
        r=self.api.localize_object('synthetic_object')
        self.assertTrue(r.ok,r.error)
        self.assertEqual(r.point_cloud.frame,'synthetic_fixture')
        np.testing.assert_allclose(r.point_cloud.points[0],[0.065,0.165,1.3],atol=1e-8)
        self.assertTrue(np.all(r.geometry.extents > 0))
        self.assertEqual(r.geometry.point_count,16)
        self.assertEqual(self.adapter.refusals,0)

    def test_native_gripper_and_trajectory_reach_denial(self):
        r=self.api.set_gripper(0.7,arm='left')
        self.assertEqual(r.error.code,ErrorCode.SAFETY_INTERLOCK)
        s=self.api.get_robot_state()
        trajectory=Trajectory(np.zeros((2,6)),0.1,s.joint_names['left'],'synthetic_planner',False,s,arm='left',embodiment='yam_real')
        self.assertEqual(self.api.execute_trajectory(trajectory).error.code,ErrorCode.SAFETY_INTERLOCK)
        self.assertEqual(self.adapter.refusals,2)

    def test_native_pose_and_sync_without_planner_refuse(self):
        pose=Pose([0.1,0.2,0.3],[1,0,0,0],'synthetic_fixture')
        self.assertFalse(self.api.move_to_pose(pose,arm='left').ok)
        self.assertFalse(self.api.move_synchronized({'left':pose,'right':pose}).ok)
        self.assertEqual(self.adapter.refusals,0)

    def test_native_embedded_session_runs_only_mock_job(self):
        registry=self.api.register_tools(ToolRegistry())
        runtime=EmbeddedAgentRuntime(self.api,registry)
        try:
            job=runtime.session.start_tool('set_gripper',{'position':0.3,'arm':'right'})
            result=runtime.session.wait(job,timeout_s=3)
            self.assertIsNotNone(result)
            self.assertEqual(self.adapter.refusals,1)
            self.assertFalse(result['result']['ok'])
        finally:runtime.close()
