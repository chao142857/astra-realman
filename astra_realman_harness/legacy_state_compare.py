"""Read-only comparison using audited methods extracted from the existing driver."""
import ast
import hashlib
import json
import logging
import math
import time
from pathlib import Path
from types import SimpleNamespace
from io_utils import vector
from realman_state import read_query, COMMANDS

LEGACY_SOURCE = Path("/home/tongji/aloha/RealMan_Control/realman_arm.py")
TOLERANCE = {"joint_deg": .05, "xyz_m": .0005, "rpy_rad": .005}

def load_legacy_read_methods():
    import numpy as np
    source = LEGACY_SOURCE.read_text()
    tree = ast.parse(source, filename=str(LEGACY_SOURCE))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RmArm")
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    chosen = [methods["_json_to_numpy"], methods["get_arm_position"]]
    # Compile only these two previously inspected read methods. Never import/run
    # project top-level code, a constructor, get_joint_angle's gripper read, or demo.
    readonly_cls = ast.ClassDef(name="LegacyReadMethods", bases=[], keywords=[], body=chosen, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[readonly_cls], type_ignores=[]))
    namespace = {"np": np, "json": json, "logging": logging}
    exec(compile(module, str(LEGACY_SOURCE), "exec"), namespace)
    provenance = {"file": str(LEGACY_SOURCE), "sha256": hashlib.sha256(source.encode()).hexdigest(),
                  "pose_function": "RmArm.get_arm_position", "pose_line": methods["get_arm_position"].lineno,
                  "joint_decoder": "RmArm._json_to_numpy and existing get_joint_angle *0.001 expression",
                  "joint_line": methods["get_joint_angle"].lineno,
                  "joint_wire_source": "arm_state.joint from the same get_current_arm_state read",
                  "constructor_called": False, "gripper_getter_called": False}
    return namespace["LegacyReadMethods"], provenance

class StateReadSocket:
    """The original pose getter can transmit only its constant state query."""
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.sample = None
    def send(self, payload):
        if payload != COMMANDS["get_current_arm_state"]:
            raise ValueError("LEGACY_READ_COMMAND_NOT_ALLOWED")
        if self.sample is not None:
            raise ValueError("LEGACY_ONLY_ONE_READ")
        self.sample = read_query(self.host, self.port, "get_current_arm_state")
        return len(payload)
    def recv(self, size):
        if self.sample is None:
            raise ValueError("LEGACY_RECV_BEFORE_SEND")
        payload = self.sample["raw_text"].encode()
        if len(payload) > size:
            raise ValueError("LEGACY_BUFFER_TOO_SMALL")
        return payload

def read_legacy(host, port):
    cls, provenance = load_legacy_read_methods()
    reader = cls()
    transport = StateReadSocket(host, port)
    reader.arm = transport
    reader.cmd_get_current_arm_state = COMMANDS["get_current_arm_state"].decode()
    pose = reader.get_arm_position()
    raw = transport.sample["raw_response"]["arm_state"]
    joint_buffer = json.dumps({"joint": raw["joint"]}).encode()
    # Exact unit expression used by existing RmArm.get_joint_angle, operating on
    # raw joint integers; no extra query or gripper interaction.
    joints = reader._json_to_numpy(joint_buffer, "joint") * .001
    return {"raw_socket_sample": transport.sample, "legacy_pose_mm_rad": pose,
            "joint_deg": joints.tolist(),
            "ee_pose": {"xyz_m": [float(pose[k])/1000 for k in ("x","y","z")],
                        "rpy_rad": [float(pose[k]) for k in ("roll","pitch","yaw")]},
            "timestamp": transport.sample["received_at"], "provenance": provenance,
            "normalization": "legacy xyz mm -> m /1000; legacy joints already deg; SDK values never used here"}

def difference(a, b, angle=False):
    if not vector(a, len(b)):
        raise ValueError("COMPARISON_VECTOR")
    return [((x-y+math.pi)%(2*math.pi)-math.pi) if angle else x-y for x,y in zip(a,b)]

def compare(canonical, before, after):
    if canonical is None:
        return {"status": "SDK_FAILED_NO_COMPARISON"}
    chosen = min((before, after), key=lambda x:abs(x["timestamp"]-canonical["timestamp"]))
    fields = {
        "joint_deg": (canonical["joint_deg"], chosen["joint_deg"], before["joint_deg"], after["joint_deg"], False),
        "xyz_m": (canonical["ee_pose"]["xyz_m"], chosen["ee_pose"]["xyz_m"],
                  before["ee_pose"]["xyz_m"], after["ee_pose"]["xyz_m"], False),
        "rpy_rad": (canonical["ee_pose"]["rpy_rad"], chosen["ee_pose"]["rpy_rad"],
                    before["ee_pose"]["rpy_rad"], after["ee_pose"]["rpy_rad"], True),
    }
    result = {"difference_sign": "SDK minus nearest legacy read",
              "tolerances_for_diagnostic_only": TOLERANCE,
              "time_offset_ms": (canonical["timestamp"]-chosen["timestamp"])*1000,
              "bracket_duration_ms": (after["timestamp"]-before["timestamp"])*1000}
    consistent, stable = True, True
    for name, (a,b,lo,hi,angle) in fields.items():
        diff = difference(a,b,angle)
        drift = difference(hi,lo,angle)
        result[name] = {"difference": diff, "max_abs_difference": max(map(abs,diff)),
                        "legacy_bracket_delta": drift, "max_abs_legacy_bracket_delta":max(map(abs,drift))}
        consistent &= result[name]["max_abs_difference"] <= TOLERANCE[name]
        stable &= result[name]["max_abs_legacy_bracket_delta"] <= TOLERANCE[name]
    result["static_within_diagnostic_tolerance"] = bool(stable)
    result["status"] = "CONSISTENT" if stable and consistent else "MISMATCH_OR_NOT_STATIC"
    result["execution_permitted"] = False
    return result
