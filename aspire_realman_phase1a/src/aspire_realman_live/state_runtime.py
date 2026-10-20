"""Single-arm diagnostic metadata via native CAP registry/program/MCP hooks.

Keeps native RobotState strict. One fixed read-only metadata program is added;
native Agent, MCP bridge, server, executor, prompts and motion tools are intact.
"""
import hashlib
import time
import numpy as np
from cap_harness.agent.program_catalog import CapProgramCatalog, CapProgramDefinition, LoadedCapProgram
from aspire_realman.codec import ObservationUnavailable
from .adapter import LiveRealManAdapter
from .quality import camera_quality
from .source import host_clock_id
from .state_owner import camera_state_receipt_bounds_ms


def current_clock_id():
    try:
        return host_clock_id()
    except OSError:
        return None  # Offline non-Linux viewer: receipt domains incomparable.


class ReadOnlyStatePrograms(CapProgramCatalog):
    def __init__(self):
        super().__init__()
        source = 'result = get_readonly_state_snapshot()\n'
        self.readonly = LoadedCapProgram(CapProgramDefinition('readonly_state',
            'Read one scoped SDK state snapshot with units, frames, provenance and missing-field reasons; never moves.', False),
            source, hashlib.sha256(source.encode()).hexdigest())

    def all(self):
        return (*super().all(), self.readonly)

    def get(self, name):
        return self.readonly if name == 'readonly_state' else super().get(name)


class SingleArmReadOnlyAdapter(LiveRealManAdapter):
    def __init__(self, owner, camera_source=None):
        self.state_owner, self._source = owner, camera_source
        self._expected_cameras = {} if camera_source is None else dict(camera_source.roles)
        self._closed, self._refusals = False, []

    @property
    def arms(self):
        return (self.state_owner.arm,)

    def get_robot_state(self):
        raise ObservationUnavailable('NATIVE_ROBOTSTATE_INCOMPLETE: measured velocity/gripper and endpoint binding required; use cap_program_readonly_state for scoped diagnostics, no World/TCP required for that display')

    def get_readonly_state_snapshot(self):
        if self._closed:
            raise RuntimeError('ADAPTER_CLOSED')
        view = self.state_owner.read(host_clock_id=current_clock_id())
        raw, quality = view['canonical_state'], view['quality']
        pose = raw['ee_pose']
        # Flatten only presentation. Source sample and all five returns remain
        # in sdk-sample-N.json. Unknown endpoint frames stay explicitly null.
        return {'ok': view['query_ok'], 'query_ok': view['query_ok'],
            'ok_semantics': 'QUERY_SUCCESS_ONLY_NOT_LIVE_OR_CONTROLLER_MEASUREMENT_FRESHNESS',
            'live_current': view['live_current'],
            'controller_measurement_freshness': view['controller_measurement_freshness'],
            'observation_kind': 'SINGLE_ARM_READONLY_DIAGNOSTIC_NOT_NATIVE_ROBOTSTATE',
            'source': {'arm_scope': view['arm_scope'], 'kind': view['source_kind'],
                'owner_id': view['owner_id'], 'sequence': view['sequence']},
            'telemetry': {'joint_positions_rad': np.deg2rad(raw['joint_deg']).tolist(),
                'joint_positions_deg': raw['joint_deg'],
                'joint_names': [f'{self.state_owner.arm}_joint_{i}' for i in range(1,7)],
                'joint_velocity_deg_s': view['joint_velocity_deg_s'], 'gripper': view['gripper_telemetry'],
                'controller_error': raw.get('system_error')},
            'endpoint': {'xyz_m': pose['xyz_m'], 'rpy_rad': pose['rpy_rad'],
                'reference_frame': pose.get('reference_frame_id'), 'target_frame': pose.get('target_frame_id'),
                'semantics_status': pose.get('frame_semantics_status', 'UNKNOWN'),
                'is_actual_grasp_center': False},
            'frames': {'active_work': raw['work_frame'], 'active_tool': raw['tool_frame'],
                'snapshot_stable': raw['frame_snapshot_stable'], 'snapshot_atomic': view['snapshot_atomic']},
            'timestamps': {'source_epoch_s': raw['timestamp'], 'domain': view['source_timestamp_domain'],
                'host_clock_id': view['host_clock_id'], 'read_interval_monotonic_s': view['read_interval_monotonic_s'],
                'device_timestamp': None},
            'quality': quality, 'owner_error': view.get('owner_error'),
            'world_transform': None, 'actual_grasp_tcp': None, 'motion_permitted': False,
            'native_robot_state_available': False, 'full_cap_observation_available': False,
            'missing_native_fields': ['measured_joint_velocity', 'measured_gripper', 'current_endpoint_frame_binding'],
            'camera_receipt_join': self._camera_join(view)}

    def _camera_join(self, view):
        if self._source is None:
            return {'available': False, 'reason': 'NO_CAMERA_OWNER_SUBSCRIPTION'}
        snapshot = self._read()
        return {c['role']: camera_state_receipt_bounds_ms(c['capture_wait_interval_monotonic_s'],
                view['read_interval_monotonic_s'], camera_clock=c['host_clock_id'], state_clock=view['host_clock_id'])
                for c in snapshot['cameras']}

    def monitor_snapshot(self):
        view = self.state_owner.read(host_clock_id=current_clock_id())
        if not view['live_current']:
            raise ObservationUnavailable('STATE_NOT_CURRENT: '+str(view['quality']))
        raw = view['canonical_state']
        cameras, metadata = {}, {}
        if self._source is not None:
            snapshot = self._read()
            cameras = {c['role']: c['rgb'] for c in snapshot['cameras']}
            metadata = {c['role']: camera_quality(c, snapshot) for c in snapshot['cameras']}
        # Incomplete numeric monitor fields, NOT typed RobotState. Raw pose is
        # named as such; it is never exposed under a grasp/World pose label.
        state = {self.arms[0]+'_joint_pos': np.deg2rad(raw['joint_deg']),
                 self.arms[0]+'_unbound_sdk_xyz_m': np.array(raw['ee_pose']['xyz_m']),
                 self.arms[0]+'_unbound_sdk_rpy_rad': np.array(raw['ee_pose']['rpy_rad'])}
        return {'ok': True, 'timestamp_s': raw['timestamp'], 'refresh_timestamp_s': time.time(),
                'observation_seq': view['sequence'], 'state': state, 'cameras': cameras, 'camera_metadata': metadata}
