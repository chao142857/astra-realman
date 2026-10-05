"""Passive pose telemetry: no tolerance, verdict, or runtime gate."""
import math

def pose_telemetry(before, commanded, actual):
    result={"passive_only":True,"before_pose":before,"commanded_pose":commanded,"actual_pose":actual}
    try:
        result["actual_xyz_delta_m"]=[a-b for a,b in zip(actual["xyz_m"],before["xyz_m"])]
        result["translation_residual_m"]=[a-b for a,b in zip(actual["xyz_m"],commanded["xyz_m"])]
        result["rotation_residual_rad"]=[math.atan2(math.sin(a-b),math.cos(a-b)) for a,b in zip(actual["rpy_rad"],commanded["rpy_rad"])]
    except (KeyError,TypeError,ValueError) as exc:
        result["telemetry_error"]=str(exc)
    return result
