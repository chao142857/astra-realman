"""Offline preparation boundary, NOT a native EnvironmentAdapter yet.

Real per-arm frames remain separate. Unknown common-world/TCP transforms are
never replaced by identity. The six draft methods use JSON dictionaries so this
module runs on the existing Python 3.8/3.9 installations without new packages.
No SDK, network, camera, subprocess, model, planner, or dispatcher is imported.
"""
import copy
import json
import math
from pathlib import Path

ARMS = ('left', 'right')


def _vector(value, length):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError('VECTOR_SHAPE')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('VECTOR_NONFINITE_OR_TYPE')
    return list(value)


def rpy_rad_to_wxyz(rpy):
    """R = Rz(yaw) @ Ry(pitch) @ Rx(roll); never reinterpret rad as degrees."""
    roll, pitch, yaw = _vector(rpy, 3)
    cr, cp, cy = (math.cos(v/2) for v in (roll, pitch, yaw))
    sr, sp, sy = (math.sin(v/2) for v in (roll, pitch, yaw))
    return [cr*cp*cy+sr*sp*sy, sr*cp*cy-cr*sp*sy,
            cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy]


class ReplaySource:
    """Read a supplied local metadata snapshot; never follow recorded asset paths."""
    __slots__ = ('_snapshot',)

    def __init__(self, snapshot):
        if not isinstance(snapshot, dict) or snapshot.get('mode') != 'REPLAY_METADATA_ONLY':
            raise ValueError('EXPLICIT_REPLAY_REQUIRED')
        if set(snapshot.get('canonical_states', {})) != set(ARMS):
            raise ValueError('BOTH_RECORDED_ARMS_REQUIRED')
        self._snapshot = copy.deepcopy(snapshot)

    @classmethod
    def from_json(cls, path):
        # JSON only; never pickle/npz with object loading or recorded executable code.
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def read(self):
        return copy.deepcopy(self._snapshot)


class OfflineRealManAdapter:
    """Unconditionally motion-disabled draft; there is no enable flag or transport."""
    __slots__ = ('_source',)
    embodiment = 'realman_rm65_draft'

    def __init__(self, source):
        if type(source) is not ReplaySource:
            raise TypeError('ONLY_LOCAL_REPLAY_SOURCE_ACCEPTED')
        self._source = source

    @property
    def hardware_commands_sent(self):
        return 0

    @property
    def physical_motion_authorized(self):
        return False

    def get_robot_state(self):
        snapshot = self._source.read()
        states = {}
        for arm, raw in snapshot['canonical_states'].items():
            if raw.get('arm') != arm:
                raise ValueError('ARM_IDENTITY_MISMATCH')
            if raw.get('frame_snapshot_stable') is not True:
                raise ValueError('UNSTABLE_WORK_TOOL_SNAPSHOT')
            if raw['ee_pose'].get('units') != {'xyz': 'm', 'rpy': 'rad'}:
                raise ValueError('SDK_UNITS_NOT_CONFIRMED')
            joints = _vector(raw['joint_deg'], 6)
            pose = raw['ee_pose']
            xyz, rpy = _vector(pose['xyz_m'], 3), _vector(pose['rpy_rad'], 3)
            position = raw.get('gripper_state', {}).get('position')
            opening = None
            if position is not None:
                if isinstance(position, bool) or not isinstance(position, (int, float)) or not math.isfinite(position) or not 0 <= position <= 1000:
                    raise ValueError('GRIPPER_FEEDBACK_RANGE')
                opening = position / 1000.0
            states[arm] = {
                'joint_positions_rad': [math.radians(v) for v in joints],
                'joint_positions_source_deg': joints,
                'joint_velocities_rad_s': None,
                'velocity_valid': False,
                'reported_endpoint_pose': {
                    'position_m': xyz, 'quaternion_wxyz': rpy_rad_to_wxyz(rpy),
                    'source_rpy_rad': rpy,
                    'reference_frame': pose.get('reference_frame_id'),
                    'endpoint_frame': pose.get('target_frame_id'),
                    'frame_semantics_status': pose.get('frame_semantics_status', 'UNKNOWN'),
                },
                'active_work_frame': copy.deepcopy(raw['work_frame']),
                'active_tool_frame': copy.deepcopy(raw['tool_frame']),
                'actual_grasp_tcp_transform': None,
                'gripper_opening': opening,
                'grasp_confirmed': 'UNKNOWN',
                'system_error': copy.deepcopy(raw['system_error']),
                'timestamp_s': raw['timestamp'],
            }
        return {'mode': 'REPLAY_METADATA_ONLY', 'arms': states,
                'common_base_frame': None, 'T_left_base_right_base': None,
                'native_robot_state_ready': False,
                'hardware_commands_sent': 0, 'provenance': snapshot['provenance']}

    def get_observation(self, camera_names=None):
        snapshot = self._source.read()
        cameras = snapshot.get('cameras', [])
        if camera_names is not None:
            wanted = [camera_names] if isinstance(camera_names, str) else list(camera_names)
            if not wanted or len(set(wanted)) != len(wanted) or set(wanted) - {c['role'] for c in cameras}:
                raise ValueError('UNKNOWN_OR_DUPLICATE_CAMERA')
            cameras = [c for c in cameras if c['role'] in wanted]
        return {'mode': 'REPLAY_METADATA_ONLY', 'observation_id': snapshot['observation_id'],
                'timestamp_s': snapshot['captured_at'], 'fresh_live_observation': False,
                'cameras': copy.deepcopy(cameras), 'robot_state': self.get_robot_state(),
                'pixel_arrays_loaded': False, 'exposure_synchronized': 'UNKNOWN',
                'hardware_commands_sent': 0}

    def localize_object(self, query, *, camera_name=None, target_frame=None):
        """Never invent geometry from RGB-only log metadata or estimated extrinsics."""
        obs = self.get_observation(camera_name)
        return {'ok': False, 'error': 'OFFLINE_RGBD_AND_PROVIDER_UNAVAILABLE',
                'query': query, 'target_frame': target_frame,
                'camera_roles': [c['role'] for c in obs['cameras']],
                'geometry': None, 'hardware_commands_sent': 0,
                'reason': 'Recorded V17/V19 sample has RGB references, no loaded aligned depth or SAM3 result; native localization is not invoked.'}

    @staticmethod
    def _denied(operation):
        return {'ok': False, 'error': 'SAFETY_INTERLOCK', 'operation': operation,
                'status': 'PHASE0_OFFLINE_ONLY', 'steps_executed': 0,
                'hardware_commands_sent': 0, 'dispatch_attempted': False,
                'execution_postcondition': 'NOT_ATTEMPTED',
                'reason': 'This package has no hardware transport and cannot enable motion.'}

    def move_to_pose(self, target_pose, tolerance=0.01, max_steps=120, *, arm='left', strategy=None):
        return self._denied('move_to_pose')

    def move_to_joints(self, target, tolerance=0.01, max_steps=120, *, arm='left', strategy=None):
        return self._denied('move_to_joints')

    def move_synchronized(self, targets, tolerance=0.01, max_steps=120, strategy=None):
        return self._denied('move_synchronized')

    def set_gripper(self, position, *, arm='left'):
        return self._denied('set_gripper')

    def open_gripper(self, *, arm='left'):
        return self._denied('open_gripper')

    def close_gripper(self, *, arm='left'):
        return self._denied('close_gripper')

    def set_grippers(self, positions):
        return self._denied('set_grippers')

    def step(self, action):
        return self._denied('step')

    def execute_trajectory(self, trajectory):
        return self._denied('execute_trajectory')

    def go_home(self, *, arm='both'):
        return self._denied('go_home')

    def reset(self, task_ref=None, seed=0):
        return self._denied('reset')

    def close(self):
        # Owns no service, camera, SDK handle, worker or external resource.
        return None
