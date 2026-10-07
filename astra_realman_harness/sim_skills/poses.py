"""Explicit conversion; legacy pad-centre position is NOT a flange/tool position."""
import math


def pad_pose_to_tool_rpy(pad_xyz_wxyz, flange_to_pad_xyz, flange_to_tool_xyz,
                         world_to_work_xyz_rpy):
    import numpy as np
    from scipy.spatial.transform import Rotation
    for value, size in ((pad_xyz_wxyz, 7), (flange_to_pad_xyz, 3),
                        (flange_to_tool_xyz, 3), (world_to_work_xyz_rpy, 6)):
        if len(value) != size or any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
            raise ValueError('POSE_FORMAT_OR_NONFINITE')
    p = np.asarray(pad_xyz_wxyz, float)
    if abs(np.linalg.norm(p[3:]) - 1) > 1e-6:
        raise ValueError('UNIT_WXYZ_REQUIRED')
    rotation = Rotation.from_quat(np.roll(p[3:], -1))
    tool_world = p[:3] + rotation.apply(np.asarray(flange_to_tool_xyz) - flange_to_pad_xyz)
    # T_work_world is supplied explicitly; no assumed identity of work/world.
    work_rotation = Rotation.from_euler('xyz', world_to_work_xyz_rpy[3:])
    return [*(work_rotation.apply(tool_world) + world_to_work_xyz_rpy[:3]),
            *(work_rotation * rotation).as_euler('xyz')]
