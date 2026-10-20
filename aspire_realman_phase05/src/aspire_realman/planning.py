"""Readiness audit only: never generate fallback robot geometry or call cuRobo."""
from __future__ import annotations
from typing import Any, Mapping


def planning_readiness(manifest: Mapping[str, Any]) -> dict[str, Any]:
    required = ['urdf_sha256', 'collision_model_sha256', 'joint_order_12',
                'joint_limits', 'left_base_to_work', 'right_base_to_work',
                'left_actual_tcp', 'right_actual_tcp', 'gripper_collision_geometry',
                'controller_fk_validation', 'trajectory_timing_validation',
                'inflight_stop_validation', 'curobo_realman_model_registration']
    missing = [name for name in required if not manifest.get(name)]
    return {'ready_for_physical_planning': False,
            'offline_artifacts_complete': not missing,
            'missing': missing, 'motion_permitted': False,
            'reason': 'Phase0.5 has no execution transport. Model/calibration fields require independent real-station evidence; no identity/simulation defaults.'}
