"""Frame-explicit conversion into actual cap_harness dataclasses.

No guessed common world, TCP, velocity measurement or pixel data. The only
identity transform created here relates a named frame to itself.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
import hashlib
import math
import numbers
from types import MappingProxyType
from typing import Any, Mapping
import numpy as np
from cap_harness.contracts import CameraObservation, Observation, Pose, RobotState, TaskContext
from cap_harness.geometry import matrix_to_quaternion_wxyz


class ObservationUnavailable(RuntimeError):
    pass


def finite(value: Any, shape: tuple[int, ...]) -> np.ndarray:
    raw = np.asarray(value, dtype=object)
    if any(isinstance(v, (bool, np.bool_)) or not isinstance(v, numbers.Real) for v in raw.flat):
        raise ValueError('NONNUMERIC_OR_BOOLEAN_MEASUREMENT')
    a = np.asarray(value, dtype=float)
    if a.shape != shape or not np.all(np.isfinite(a)):
        raise ValueError('NONFINITE_OR_WRONG_SHAPE')
    return a


def rpy_matrix(rpy: Any) -> np.ndarray:
    r, p, y = finite(rpy, (3,))
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr],
                     [sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr], [-sp, cp*sr, cp*cr]])


def rigid(value: Any) -> np.ndarray:
    t = finite(value, (4, 4)).copy()
    if not np.allclose(t[3], [0,0,0,1], atol=1e-8, rtol=0):
        raise ValueError('BAD_HOMOGENEOUS_ROW')
    r = t[:3, :3]
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-6, rtol=0) or not np.isclose(np.linalg.det(r), 1, atol=1e-6):
        raise ValueError('NONRIGID_TRANSFORM')
    t.setflags(write=False)
    return t


@dataclass(frozen=True)
class TransformEdge:
    destination: str
    source: str
    matrix: np.ndarray
    status: str
    evidence: str

    def __post_init__(self):
        if not self.destination or not self.source or not self.evidence:
            raise ValueError('TRANSFORM_PROVENANCE_REQUIRED')
        if self.destination == self.source:
            raise ValueError('SELF_EDGE_UNNECESSARY')
        if self.status not in {'SYNTHETIC', 'VERIFIED', 'ESTIMATED'}:
            raise ValueError('TRANSFORM_STATUS_REQUIRED')
        object.__setattr__(self, 'matrix', rigid(self.matrix))


@dataclass(frozen=True)
class EndpointBinding:
    """Explicit scope of archived numeric endpoint evidence, not grasp TCP."""
    arm: str
    work_id: str
    tool_id: str
    work_fingerprint: str
    tool_fingerprint: str
    evidence: str
    synthetic: bool = False

    def validate(self, raw: Mapping[str, Any], synthetic_snapshot: bool) -> None:
        if self.synthetic != synthetic_snapshot:
            raise ObservationUnavailable('BINDING_SOURCE_KIND_MISMATCH')
        if not self.evidence or self.arm != raw['arm']:
            raise ObservationUnavailable('ENDPOINT_BINDING_EVIDENCE_REQUIRED')
        for key, ident, sha in [('work_frame', self.work_id, self.work_fingerprint), ('tool_frame', self.tool_id, self.tool_fingerprint)]:
            if raw[key]['id'] != ident or raw[key]['definition_fingerprint'] != sha:
                raise ObservationUnavailable('WORK_TOOL_FINGERPRINT_CHANGED')


@dataclass(frozen=True)
class CodecConfig:
    arms: tuple[str, ...]
    base_frame: str
    bindings: Mapping[str, EndpointBinding]
    transforms: tuple[TransformEdge, ...] = ()
    max_camera_state_skew_s: float = 0.05

    def __post_init__(self):
        if not self.arms or set(self.arms) - {'left', 'right'} or len(set(self.arms)) != len(self.arms):
            raise ValueError('EXPLICIT_ARM_SCOPE_REQUIRED')
        if not self.base_frame or set(self.bindings) != set(self.arms):
            raise ValueError('FRAME_AND_BINDINGS_REQUIRED')
        object.__setattr__(self, 'bindings', MappingProxyType(dict(self.bindings)))
        object.__setattr__(self, 'transforms', tuple(self.transforms))
        pairs = [(x.destination, x.source) for x in self.transforms]
        if len(set(pairs)) != len(pairs):
            raise ValueError('DUPLICATE_TRANSFORM_EDGE')
        if not np.isfinite(self.max_camera_state_skew_s) or self.max_camera_state_skew_s < 0:
            raise ValueError('INVALID_CAMERA_STATE_SKEW_LIMIT')
        adjacency = {}
        for edge in self.transforms:
            adjacency.setdefault(edge.source, []).append((edge.destination, edge.matrix))
            adjacency.setdefault(edge.destination, []).append((edge.source, np.linalg.inv(edge.matrix)))
        known = {}
        for origin in adjacency:
            if origin in known:
                continue
            known[origin] = np.eye(4); pending = deque([origin])
            while pending:
                frame = pending.popleft()
                for child, matrix in adjacency[frame]:
                    candidate = matrix @ known[frame]
                    if child in known:
                        if not np.allclose(known[child], candidate, atol=1e-6, rtol=0):
                            raise ValueError('CONTRADICTORY_FRAME_GRAPH')
                    else:
                        known[child] = candidate; pending.append(child)


def transform(config: CodecConfig, destination: str, source: str, *, synthetic: bool) -> np.ndarray:
    if destination == source:
        return np.eye(4)  # same-frame identity; never an unknown cross-base calibration
    edges: dict[str, list[tuple[str, np.ndarray]]] = {}
    for edge in config.transforms:
        if edge.status == 'ESTIMATED' or (edge.status == 'SYNTHETIC') != synthetic:
            continue
        edges.setdefault(edge.source, []).append((edge.destination, edge.matrix))
        edges.setdefault(edge.destination, []).append((edge.source, np.linalg.inv(edge.matrix)))
    pending = deque([(source, np.eye(4))]); seen = {source}
    while pending:
        frame, t = pending.popleft()
        for next_frame, edge in edges.get(frame, []):
            if next_frame in seen:
                continue
            result = edge @ t
            if next_frame == destination:
                return result
            seen.add(next_frame); pending.append((next_frame, result))
    raise ObservationUnavailable(f'CALIBRATION_PATH_MISSING:{destination}<-{source}')


def robot_state(snapshot: Mapping[str, Any], config: CodecConfig) -> RobotState:
    synthetic = snapshot['mode'] == 'SYNTHETIC'
    positions, velocities, poses, grippers, names = {}, {}, {}, {}, {}
    quality, endpoints, timestamps, atomic, errors = {}, {}, {}, {}, {}
    times = []
    for arm in config.arms:
        raw = snapshot['canonical_states'][arm]
        if raw['arm'] != arm or raw.get('frame_snapshot_stable') is not True:
            raise ObservationUnavailable('ARM_OR_FRAME_SNAPSHOT_INVALID')
        config.bindings[arm].validate(raw, synthetic)
        pose = raw['ee_pose']
        if pose.get('units') != {'xyz': 'm', 'rpy': 'rad'}:
            raise ObservationUnavailable('SDK_UNITS_UNCONFIRMED')
        positions[arm] = np.deg2rad(finite(raw['joint_deg'], (6,)))
        measured_velocity = raw.get('joint_velocity_deg_s')
        velocities[arm] = np.zeros(6) if measured_velocity is None else np.deg2rad(finite(measured_velocity, (6,)))
        quality[arm] = 'UNMEASURED_NUMERIC_PLACEHOLDER' if measured_velocity is None else 'SOURCE_REPORTED'
        local = np.eye(4); local[:3,:3] = rpy_matrix(pose['rpy_rad']); local[:3,3] = finite(pose['xyz_m'], (3,))
        to_base = transform(config, config.base_frame, raw['work_frame']['id'], synthetic=synthetic)
        world = to_base @ local
        poses[arm] = Pose(world[:3,3], matrix_to_quaternion_wxyz(world[:3,:3]), config.base_frame)
        opening = raw['gripper_state']['position']
        if isinstance(opening, bool) or not isinstance(opening, (int, float)) or not np.isfinite(opening) or not 0 <= opening <= 1000:
            raise ObservationUnavailable('GRIPPER_FEEDBACK_INVALID')
        grippers[arm] = opening / 1000
        names[arm] = tuple(f'{arm}_joint_{i}' for i in range(1,7))
        endpoints[arm] = {'frame': raw['tool_frame']['id'], 'actual_grasp_TCP': None,
                          'raw_frame_semantics': pose.get('frame_semantics_status', 'UNKNOWN'),
                          'numeric_binding_evidence': config.bindings[arm].evidence}
        times.append(float(raw['timestamp']))
        timestamps[arm] = float(raw['timestamp'])
        atomic[arm] = raw.get('snapshot_atomic', False)
        errors[arm] = raw.get('system_error')
    return RobotState(positions, velocities, poses, grippers, config.base_frame,
        joint_names=names, timestamp_s=min(times), embodiment='realman',
        metadata={'source_kind': snapshot['mode'], 'joint_velocity_quality': quality,
                  'pose_endpoint': endpoints, 'motion_permitted': False,
                  'per_arm_timestamp_s': timestamps, 'state_sample_skew_s': max(times)-min(times),
                  'sensor_snapshot_atomic': atomic, 'controller_errors': errors,
                  'grasp_confirmed': 'UNKNOWN', 'common_world_measured': not synthetic and len(config.arms)>1,
                  'physical_calibration_certified': False})


def task_context(snapshot: Mapping[str, Any]) -> TaskContext:
    return TaskContext('realman_offline', 0, 'observation_only',
                       'Observe supplied data. Physical commands are unavailable.', 'realman',
                       metadata={'mode': snapshot['mode'], 'motion_permitted': False,
                                 'provenance': snapshot.get('provenance', snapshot.get('replay_file', {}))})


def camera_observation(raw: Mapping[str, Any], state: RobotState, config: CodecConfig, *, synthetic: bool) -> CameraObservation:
    if raw.get('rgb') is None:
        raise ObservationUnavailable(f'REPLAY_PIXELS_NOT_LOADED:{raw.get("role")}')
    rgb = np.asarray(raw['rgb'])
    k = raw['intrinsics']
    if isinstance(k, Mapping):
        k = k.get('matrix', [[k.get('fx'),0,k.get('cx')],[0,k.get('fy'),k.get('cy')],[0,0,1]])
    optical = raw.get('optical_frame', 'realsense:'+raw['serial']+':color_optical')
    eligible = raw.get('geometry_eligible') is True and raw.get('depth_m') is not None
    # Unknown extrinsic uses a truthful self-frame pose. No world pose is fabricated.
    parent, camera_t = optical, np.eye(4)
    if eligible and raw.get('T_parent_camera_optical') is not None:
        parent_frame = raw.get('parent_frame')
        status = raw.get('calibration_status')
        if status == ('SYNTHETIC' if synthetic else 'VERIFIED'):
            try:
                wrist_arm = next((a for a, e in state.metadata['pose_endpoint'].items() if e['frame'] == parent_frame), None)
                if wrist_arm is not None:
                    if abs(float(raw['captured_at']) - state.timestamp_s) > config.max_camera_state_skew_s:
                        raise ObservationUnavailable('WRIST_CAMERA_STATE_TIME_SKEW')
                    to_parent = state.end_effector_poses[wrist_arm].as_matrix()
                else:
                    to_parent = transform(config, state.base_frame, parent_frame, synthetic=synthetic)
                camera_t = to_parent @ rigid(raw['T_parent_camera_optical'])
                parent = state.base_frame
            except ObservationUnavailable:
                eligible = False
        else:
            eligible = False
    else:
        eligible = False
    # Zero = invalid/no usable depth, never a manufactured positive depth surface.
    depth = np.asarray(raw['depth_m'], dtype=float) if eligible else np.zeros(rgb.shape[:2])
    return CameraObservation(rgb=rgb, depth_m=depth, intrinsics=k, frame=optical,
        camera_pose=Pose(camera_t[:3,3], matrix_to_quaternion_wxyz(camera_t[:3,:3]), parent),
        timestamp_s=float(raw.get('captured_at', state.timestamp_s)))


def observation(snapshot: Mapping[str, Any], config: CodecConfig) -> Observation:
    state = robot_state(snapshot, config)
    cameras = {c['role']: camera_observation(c, state, config, synthetic=snapshot['mode']=='SYNTHETIC') for c in snapshot.get('cameras', []) if c.get('rgb') is not None}
    if not cameras:
        raise ObservationUnavailable('NO_LOADED_CAMERA_PIXELS; metadata replay supports state queries only')
    return Observation(cameras, state, task_context(snapshot), float(snapshot.get('captured_at', state.timestamp_s)))
