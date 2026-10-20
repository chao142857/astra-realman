"""Quality gates separate host receipt, device exposure, arm time and geometry."""
import hashlib
import time
import numpy as np
from .source import TABLETOP, MISSING


def camera_quality(camera, snapshot, *, now_mono=None, now_wall=None, max_age_s=1.0):
    now_mono = time.monotonic() if now_mono is None else now_mono
    now_wall = time.time() if now_wall is None else now_wall
    receipt_age = now_mono - camera['received_monotonic_s']
    age = max(0.0, receipt_age)
    domains = [camera['color_timestamp_domain'], camera['depth_timestamp_domain']]
    # RealSense global_time is host-correlated epoch ms. Hardware-clock values
    # are NEVER subtracted from host epoch/arm timestamps without a clock model.
    mapped = all(d in {'global_time', 'timestamp_domain.global_time'} for d in domains)
    exposure_age = [(now_wall - camera[n]/1000) for n in ['color_timestamp_ms','depth_timestamp_ms']] if mapped else None
    exposure_fresh = mapped and all(-0.05 <= a <= max_age_s for a in exposure_age)
    same_domain = domains[0] == domains[1]
    skew = abs(camera['color_timestamp_ms']-camera['depth_timestamp_ms']) if same_domain else None
    z = camera['depth_m']
    valid = np.isfinite(z) & (z > 0)
    positive = z[valid]
    fraction = float(valid.mean())
    role_ok = TABLETOP.get(camera['role']) == camera['serial']
    stale = (not snapshot['owner_running'] or receipt_age < -0.001 or age > max_age_s or not exposure_fresh)
    return {'role':camera['role'], 'serial':camera['serial'], 'source_kind':'LIVE',
        'sequence':snapshot['sequence'], 'owner_id':snapshot['owner_id'],
        'owner_running':snapshot['owner_running'], 'owner_error':snapshot['owner_error'],
        'timestamp_s':camera['captured_at'], 'age_ms':max([age] + (exposure_age or []))*1000,
        # Native session recomputes stale from age; fail-closed sentinel preserves
        # owner/domain failures rather than clearing them on every cache refresh.
        'stale_after_ms':-1 if stale else max_age_s*1000,
        'stale':stale, 'missing':False, 'role_serial_verified':role_ok,
        'host_clock_id':camera['host_clock_id'], 'freshness_basis':'HOST_RECEIPT_AND_DEVICE_GLOBAL_TIME' if mapped else 'HOST_RECEIPT_ONLY_EXPOSURE_UNVERIFIED',
        'device_timestamp_domains':domains, 'device_exposure_age_ms':None if exposure_age is None else [x*1000 for x in exposure_age],
        'device_color_depth_skew_ms':skew, 'color_depth_temporally_eligible':skew is not None and skew <= 50,
        'exposure_freshness_verified':bool(exposure_fresh), 'exposure_synchronized':'UNKNOWN',
        'timestamp_verification_scope':'SDK global_time plausibility; no independent exposure clock validation',
        'color_frame_number':camera['color_frame_number'], 'depth_frame_number':camera['depth_frame_number'],
        'rgb_shape':list(camera['rgb'].shape), 'aligned_depth_shape':list(z.shape), 'depth_unit':'m',
        'depth_valid_fraction':fraction, 'nonfinite_depth_fraction':float((~np.isfinite(z)).mean()),
        'positive_depth_percentiles_m':np.percentile(positive,[1,50,99]).tolist() if positive.size else None,
        'depth_usable_for_optical_inspection':fraction >= .10 and same_domain and skew <= 50,
        'geometry_eligible':False, 'calibration_status':'HISTORICAL_EXTRINSIC_NOT_REVALIDATED',
        'world_transform':None, 'actual_grasp_tcp':None,
        'observation_kind':'CAMERA_MONITOR_ONLY', 'missing_physical_camera_roles':MISSING,
        'timestamp_s_semantics':'host receipt epoch seconds; device global_time retained separately',
        'depth_quality_policy':'valid fraction >=0.10 is only a data-availability gate, not an accuracy certificate',
        'robot_state_available':False, 'robot_state_source':snapshot['robot_state_source'],
        'arm_timestamps_s':{'left':None,'right':None}, 'camera_arm_skew_ms':{'left':None,'right':None},
        'full_cap_observation_available':False, 'full_cap_observation_reason':'REAL_ROBOT_STATE_UNAVAILABLE_ARMS_POWERED_OFF',
        'frame_hash':hashlib.sha256(np.ascontiguousarray(camera['rgb']).tobytes()).hexdigest(),
        'depth_hash':hashlib.sha256(np.ascontiguousarray(z).tobytes()).hexdigest()}
