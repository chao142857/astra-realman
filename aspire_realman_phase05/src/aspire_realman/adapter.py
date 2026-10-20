"""Actual native EnvironmentAdapter; all command paths end in a typed refusal."""
from __future__ import annotations
import hashlib
import time
from typing import Any, Mapping
import numpy as np
from cap_harness.contracts import ExecutionResult, Observation, RobotAction, RobotState, StepResult, SynchronizedTrajectory, TaskContext, Trajectory
from cap_harness.errors import ApiError, ErrorCode
from . import codec
from .codec import CodecConfig
from .sources import MemorySource, ReplaySource


class RealManAdapter:
    embodiment = 'realman'

    def __init__(self, source: MemorySource, config: CodecConfig):
        if type(source) not in {MemorySource, ReplaySource}:
            raise TypeError('ONLY_OFFLINE_SOURCE_IMPLEMENTATIONS_ACCEPTED')
        self._source = source
        cameras = source.read().get('cameras', [])
        self._expected_cameras = {c['role']: c['serial'] for c in cameras}
        if len(self._expected_cameras) != len(cameras):
            raise ValueError('DUPLICATE_CAMERA_ROLE')
        self.config = config
        self._closed = False
        self._refusals: list[dict[str, Any]] = []

    @property
    def arms(self) -> tuple[str, ...]:
        return self.config.arms

    @property
    def physical_motion_authorized(self) -> bool:
        return False

    @property
    def hardware_commands_sent(self) -> int:
        return 0

    @property
    def refusals(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(r) for r in self._refusals)

    def resolve_arm(self, arm: str) -> str:
        if arm == 'primary':
            return self.arms[0]
        if arm == 'secondary' and len(self.arms) > 1:
            return self.arms[1]
        return arm

    def _read(self) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError('ADAPTER_CLOSED')
        snapshot = self._source.read()
        cameras = snapshot.get('cameras', [])
        if len({c['role'] for c in cameras}) != len(cameras):
            raise ValueError('DUPLICATE_CAMERA_ROLE')
        if any(self._expected_cameras.get(c['role']) != c['serial'] for c in cameras):
            raise codec.ObservationUnavailable('CAMERA_ROLE_SERIAL_CHANGED')
        return snapshot

    def get_robot_state(self) -> RobotState:
        return codec.robot_state(self._read(), self.config)

    def get_observation(self) -> Observation:
        return codec.observation(self._read(), self.config)

    def get_task_context(self) -> TaskContext:
        return codec.task_context(self._read())

    def _error(self, operation: str) -> ApiError:
        self._refusals.append({'operation': operation, 'timestamp_s': time.time(), 'hardware_commands_sent': 0})
        return ApiError(ErrorCode.SAFETY_INTERLOCK,
            'Phase0.5 observation-only adapter has no physical command transport', recoverable=False,
            details={'operation': operation, 'hardware_commands_sent': 0, 'dispatch_attempted': False})

    def reset(self, task_ref: object = None, seed: int = 0) -> Observation:
        raise self._error('reset')

    def step(self, action: RobotAction) -> StepResult:
        return StepResult(ok=False, error=self._error('step'), diagnostics={'hardware_commands_sent': 0})

    def execute_trajectory(self, trajectory: Trajectory | SynchronizedTrajectory) -> ExecutionResult:
        return self._deny('execute_trajectory')

    def _deny(self, operation: str) -> ExecutionResult:
        return ExecutionResult(ok=False, steps_executed=0, error=self._error(operation),
            diagnostics={'hardware_commands_sent': 0, 'dispatch_attempted': False, 'physical_postcondition': 'NOT_ATTEMPTED'})

    def set_gripper(self, position: float, *, arm: str = 'primary') -> ExecutionResult:
        return self._deny('set_gripper')

    def set_grippers(self, positions: Mapping[str, float]) -> ExecutionResult:
        return self._deny('set_grippers')

    def go_home(self, *, arm: str = 'both') -> ExecutionResult:
        return self._deny('go_home')

    def get_planning_context(self):
        # Explicitly block CapApi's Panda/identity fallback. No RealMan model or
        # physical grasp TCP has yet been independently bound to this station.
        raise codec.ObservationUnavailable('REALMAN_MODEL_AND_GRASP_TCP_UNAVAILABLE; planning/dispatch disabled')

    def monitor_snapshot(self) -> dict[str, Any]:
        snapshot = self._read()
        now = time.time()
        state = codec.robot_state(snapshot, self.config)
        frames, metadata = {}, {}
        for camera in snapshot.get('cameras', []):
            role = camera['role']; rgb = camera.get('rgb'); stamp = float(camera.get('captured_at', state.timestamp_s))
            geometry_eligible = False
            if rgb is not None:
                frames[role] = np.asarray(rgb, dtype=np.uint8)
                converted = codec.camera_observation(camera, state, self.config, synthetic=snapshot['mode']=='SYNTHETIC')
                geometry_eligible = converted.camera_pose.frame == state.base_frame and bool(np.any(converted.depth_m > 0))
            metadata[role] = {'serial': camera['serial'], 'source_kind': snapshot['mode'],
                'timestamp_s': stamp, 'age_ms': max(0, now-stamp)*1000,
                'stale': snapshot['mode'] != 'SYNTHETIC', 'missing': rgb is None,
                'geometry_eligible': geometry_eligible,
                'calibration_status': camera.get('calibration_status', 'UNKNOWN'),
                'exposure_synchronized': 'UNKNOWN', 'stale_after_ms': 1000,
                'frame_hash': hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest() if rgb is not None else None}
        for role, serial in self._expected_cameras.items():
            if role not in metadata:
                metadata[role] = {'serial': serial, 'source_kind': snapshot['mode'], 'missing': True,
                                  'stale': True, 'geometry_eligible': False, 'frame_hash': None}
        cache_state = {f'{arm}_joint_pos': state.joint_positions[arm] for arm in state.arms}
        cache_state.update({f'{arm}_gripper_pos': np.array([state.gripper_positions[arm]]) for arm in state.arms})
        return {'ok': True, 'timestamp_s': float(snapshot['captured_at']), 'refresh_timestamp_s': now,
                'observation_seq': int(snapshot.get('sequence', 1)), 'cameras': frames,
                'camera_metadata': metadata, 'state': cache_state}

    def close(self) -> None:
        # Caller owns the source. Never stop another process or close a device.
        self._closed = True
