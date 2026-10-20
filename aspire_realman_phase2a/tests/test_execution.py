"""Execution contract acceptance, not planner or physical-control validation."""
from dataclasses import replace
from pathlib import Path
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from cap_harness.contracts import RobotState,Pose,Trajectory,SynchronizedTrajectory
from cap_harness.errors import ApiError,ErrorCode
from aspire_realman_phase2a.model import ARMS,NAMES,FRAME,compress_spheres
from aspire_realman_phase2a.execution import ExecutionEngine,StubTransport,PhysicalDispatch,gripper_contract,v17_pose_contract,sdk_joint_endpoint_contract,sdk_stream_sample_contract


class StubAcceptance(unittest.TestCase):
    def setUp(self):
        persistent=os.environ.get('PHASE2A_STUB_EVIDENCE')
        if persistent:
            path=Path(persistent).resolve()/self._testMethodName
            path.relative_to(Path(__file__).resolve().parents[2])
            path.mkdir(parents=True,exist_ok=False);self.temp=SimpleNamespace(name=str(path))
        else:
            self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        # Bounds in these contract tests are synthetic, not a robot model.
        self.manifest={'joint_limits':{a:[{'lower':-2.,'upper':2.,'velocity':1.}]*6 for a in ARMS}}
        self.positions={a:np.zeros(6) for a in ARMS}
    def engine(self,**kwargs):
        transport=StubTransport(self.positions,**kwargs)
        return ExecutionEngine(transport,self.manifest,Path(self.temp.name)/str(len(list(Path(self.temp.name).iterdir()))))
    def trajectory(self,*,sync=True):
        state=RobotState(joint_positions=self.positions,joint_velocities=self.positions,
            end_effector_poses={a:Pose(np.zeros(3),np.array([1.,0,0,0]),FRAME) for a in ARMS},
            gripper_positions={a:1. for a in ARMS},joint_names=NAMES,base_frame=FRAME,
            embodiment='realman',metadata={'source_kind':'SYNTHETIC_OFFLINE'})
        values=np.array([np.zeros(6),np.full(6,.02),np.full(6,.04)])
        common=dict(dt_s=.1,planner='CONTRACT_TEST_NOT_PLANNER',collision_aware=False,expected_start=state,embodiment='realman')
        return SynchronizedTrajectory(joint_positions={a:values for a in ARMS},joint_names=NAMES,**common) if sync else Trajectory(joint_positions=values,joint_names=NAMES['left'],arm='left',**common)
    def assert_error(self,result,code):
        self.assertFalse(result.ok);self.assertEqual(result.error.code,code)
        self.assertEqual(result.diagnostics['hardware_commands_sent'],0)
    def test_shared_time_grid_and_feedback(self):
        e=self.engine();r=e.execute(self.trajectory(),request_id='dual')
        self.assertTrue(r.ok);self.assertEqual(r.steps_executed,3)
        self.assertEqual([x['scheduled_s'] for x in e.transport.events],[0.,.1,.2])
        self.assertTrue(all(x['same_tick_arm_packet']==list(ARMS) for x in e.transport.events))
        self.assertTrue(all(np.allclose(e.transport.positions[a],.04) for a in ARMS))
        self.assertFalse(r.diagnostics['hardware_synchronization_verified'])
    def test_no_endpoint_sequential_fallback(self):
        e=self.engine(timed_dual=False)
        self.assert_error(e.execute(self.trajectory()),ErrorCode.UNSUPPORTED)
        self.assertEqual(e.transport.events,[])
    def test_duplicate_claim_persists_after_failure(self):
        e=self.engine(fail_at=0);trajectory=self.trajectory()
        self.assert_error(e.execute(trajectory,request_id='consumed'),ErrorCode.CONTROLLER_FAILED)
        e.transport.fail_at=None
        self.assert_error(e.execute(trajectory,request_id='consumed'),ErrorCode.SAFETY_INTERLOCK)
        self.assertEqual(e.transport.events,[])
        self.assertEqual(len(list(e.ledger.glob('*.claim.json'))),1)
    def test_cancellation_stops_remaining_ticks(self):
        e=self.engine(cancel_at=0);r=e.execute(self.trajectory())
        self.assert_error(r,ErrorCode.CANCELLED);self.assertEqual(r.steps_executed,1)
        self.assertEqual(len(e.transport.events),1)
        self.assert_error(e.set_gripper(.5,'left',request_id='after_abort'),ErrorCode.CANCELLED)
    def test_controller_error_and_timeout_never_retry(self):
        for kwargs,code,steps in [({'fail_at':1},ErrorCode.CONTROLLER_FAILED,1),({'delay_at':{1:3}},ErrorCode.TIMEOUT,2)]:
            with self.subTest(kwargs=kwargs):
                e=self.engine(**kwargs);r=e.execute(self.trajectory(),timeout_s=1.)
                self.assert_error(r,code);self.assertEqual(r.steps_executed,steps)
                self.assertEqual(len(e.transport.events),steps)
    def test_stale_start_and_limits_reject_before_tick(self):
        e=self.engine();e.transport.positions['right'][0]=.01
        self.assert_error(e.execute(self.trajectory()),ErrorCode.STALE_PLAN)
        e=self.engine();t=self.trajectory(sync=False)
        for bad in [np.array([[0.]*6,[3.]*6]),np.array([[0.]*6,[.5]*6])]:
            self.assert_error(e.execute(replace(t,joint_positions=bad)),ErrorCode.INVALID_REQUEST)
        self.assertEqual(e.transport.events,[])
    def test_gripper_wire_ack_and_executor_exclusion(self):
        e=self.engine();r=e.set_gripper(.4329,'right',request_id='gripper')
        self.assertTrue(r.ok);self.assertEqual(e.transport.openings['right'],.432)
        self.assertEqual(gripper_contract('right',.4329)['v17_wire']['hand_pos'],[432])
        self.assertEqual(r.diagnostics['grasp_confirmed'],'UNKNOWN')
        saved=json.loads(next(e.ledger.glob('*.result.json')).read_text())
        self.assertTrue(saved['ok']);self.assertEqual(saved['feedback'][0]['position_raw'],432)
        e.lock.acquire()
        try:self.assert_error(e.set_gripper(.5,'left',request_id='busy'),ErrorCode.SAFETY_INTERLOCK)
        finally:e.lock.release()
        self.assert_error(e.set_gripper(.5,'right',request_id='gripper'),ErrorCode.SAFETY_INTERLOCK)
    def test_trajectory_does_not_silently_ignore_gripper_changes(self):
        e=self.engine();t=replace(self.trajectory(sync=False),gripper_positions=np.array([1.,.5,0.]))
        self.assert_error(e.execute(t),ErrorCode.UNSUPPORTED);self.assertEqual(e.transport.events,[])
    def test_physical_dispatch_has_no_enable_switch(self):
        with self.assertRaises(ApiError) as ctx:PhysicalDispatch(allow_motion=True)
        self.assertEqual(ctx.exception.code,ErrorCode.SAFETY_INTERLOCK)
        contract=v17_pose_contract([.1,.2,.3],[0,0,0])
        self.assertEqual(contract['sdk_method'],'rm_movej_p')
        self.assertFalse(contract['timed_trajectory']);self.assertFalse(contract['dual_synchronization'])
        endpoint=sdk_joint_endpoint_contract([np.pi/2]*6,speed_percent=1)
        self.assertTrue(np.allclose(endpoint['args'][0],[90]*6));self.assertFalse(endpoint['physical_dispatch_available'])
        with self.assertRaises(ValueError):sdk_stream_sample_contract([0.]*6,relative_time_s=0.,period_s=.05,follow=True)
    def test_conservative_merge_keeps_every_original_sphere(self):
        original={'link':[{'center':[x,0,0],'radius':.02} for x in np.arange(7)*.01]}
        merged,proof=compress_spheres(original,3)
        for src in original['link']:
            self.assertTrue(any(np.linalg.norm(np.array(src['center'])-dst['center'])+src['radius']<=dst['radius']+1e-9 for dst in merged['link']))
        self.assertEqual(sum(p['source_count'] for p in proof['link']),7)


if __name__=='__main__':unittest.main(verbosity=2)
