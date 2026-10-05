"""Execution verification using operator-selected tracking tolerances."""
import math
from io_utils import vector
POSITION_RESIDUAL_M=.001
ROTATION_RESIDUAL_RAD=math.radians(.5)

def verify_execution(command_return, robot_errors, commanded_delta, before_pose, target_pose, after_pose):
    errors=[]
    if type(command_return)is not int or command_return!=0:
        errors.append("COMMAND_RETURN_NOT_ZERO")
    if (not isinstance(robot_errors,dict) or set(robot_errors)!={"left","right"} or
        any(not isinstance(c,list) or not c or any(type(v)is not int or v!=0 for v in c)
            for c in robot_errors.values())):
        errors.append("ROBOT_ERROR_OR_UNKNOWN")
    if (not vector(commanded_delta,3) or
        any(not isinstance(p,dict) or not vector(p.get("xyz_m"),3) or not vector(p.get("rpy_rad"),3)
            for p in (before_pose,target_pose,after_pose))):
        return {"status":"REJECT","errors":errors+["INVALID_POSE_OR_DELTA"]}
    actual=[a-b for a,b in zip(after_pose["xyz_m"],before_pose["xyz_m"])]
    residual=[a-t for a,t in zip(after_pose["xyz_m"],target_pose["xyz_m"])]
    rotation=[math.atan2(math.sin(a-t),math.cos(a-t)) for a,t in zip(after_pose["rpy_rad"],target_pose["rpy_rad"])]
    directions=[]
    for axis,requested,observed in zip(("x","y","z"),commanded_delta,actual):
        status=("NOT_COMMANDED" if requested==0 else
                "OPPOSITE" if requested*observed<0 else
                "NO_RESOLVED_MOVEMENT" if observed==0 else "CORRECT")
        directions.append({"axis":axis,"requested_m":requested,"actual_m":observed,"status":status})
        if status=="OPPOSITE":errors.append("OPPOSITE_DIRECTION_"+axis.upper())
    if any(abs(v)>POSITION_RESIDUAL_M+1e-12 for v in residual):
        errors.append("TRANSLATION_RESIDUAL_OVER_1MM")
    if any(abs(v)>ROTATION_RESIDUAL_RAD+1e-12 for v in rotation):
        errors.append("ROTATION_RESIDUAL_OVER_0_5DEG")
    return {"status":"EXECUTED_VERIFIED" if not errors else "REJECT","errors":errors,
            "command_return":command_return,"robot_errors":robot_errors,
            "commanded_delta_m":commanded_delta,"actual_delta_m":actual,
            "translation_residual_m":residual,"rotation_residual_rad":rotation,
            "axis_directions":directions,"position_residual_limit_m":POSITION_RESIDUAL_M,
            "rotation_residual_limit_rad":ROTATION_RESIDUAL_RAD,
            "note":"Zero-request axes use residual checks only. Zero measured displacement is accepted only within the same residual bound."}
