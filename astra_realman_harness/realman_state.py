"""Read-only RealMan JSON transport. No vendor SDK or robot driver import."""
import socket
import time
from urllib.parse import quote
from io_utils import strict_json

COMMANDS = {
    "get_current_arm_state": b'{"command":"get_current_arm_state"}\r\n',
    "get_current_work_frame": b'{"command":"get_current_work_frame"}\r\n',
    "get_current_tool_frame": b'{"command":"get_current_tool_frame"}\r\n',
}
TRANSPORT = "realman_tcp_json_raw_integer_v1"
RPY_METADATA = {
    "representation": "roll-pitch-yaw", "unit": "rad", "array_order": ["roll", "pitch", "yaw"],
    "rotation_convention": "ZYX intrinsic", "matrix": "Rz(yaw) @ Ry(pitch) @ Rx(roll)",
    "source": "user-confirmed; https://develop.realman-robotics.com/robot4th/FQA/sdk/",
}
UNIT_SOURCE = "https://develop.realman-robotics.com/robot4th/json/armState/"
FRAME_SOURCE = "https://develop.realman-robotics.com/robot4th/json/coordinate/"

def read_query(host, port, command, timeout=3.0):
    # Index the immutable read vocabulary before opening any connection.
    if command not in COMMANDS:
        raise ValueError("READ_COMMAND_NOT_ALLOWED")
    started = time.time()
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.settimeout(timeout)
        conn.sendall(COMMANDS[command])
        data = bytearray()
        deadline = time.monotonic() + timeout
        while b"\n" not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("READ_RESPONSE_TIMEOUT")
            conn.settimeout(remaining)
            part = conn.recv(4096)
            if not part:
                break
            data.extend(part)
            if len(data) > 65536:
                raise ValueError("READ_RESPONSE_TOO_LARGE")
    raw_text = bytes(data).split(b"\n", 1)[0].decode("utf-8").rstrip("\r")
    response = strict_json(raw_text)
    expected = command[4:]
    if not isinstance(response, dict) or not (
            response.get("command") == command or response.get("state") == expected):
        raise ValueError("UNEXPECTED_READ_RESPONSE:" + command)
    if response.get("get_state") is False:
        raise ValueError("CONTROLLER_READ_FAILED:" + command)
    return {"command": command, "transport": TRANSPORT, "started_at": started,
            "received_at": time.time(), "raw_text": raw_text, "raw_response": response}

def int_vector(value, length):
    return isinstance(value, list) and len(value) == length and all(type(x) is int for x in value)

def decode_pose(raw, transport):
    result = {"raw": raw, "raw_units": ["micrometre"]*3 + ["milliradian"]*3,
              "position_m": None, "rpy_rad": None, "units": {"position": "m", "orientation": "rad"},
              "orientation_metadata": dict(RPY_METADATA), "conversion_count": 0,
              "units_confirmed": False}
    # Never infer the scale from magnitude or accept already-converted floats.
    if transport != TRANSPORT or not int_vector(raw, 6):
        result["error"] = "POSE_RAW_INTEGER_PROVENANCE_REQUIRED"
        return result
    result.update(position_m=[x/1_000_000 for x in raw[:3]], rpy_rad=[x/1000 for x in raw[3:]],
                  conversion_count=1, units_confirmed=True,
                  conversion={"xyz_divisor": 1_000_000, "rpy_divisor": 1000})
    return result

def frame_id(arm, kind, name):
    if arm not in ("left", "right") or kind not in ("work", "tool"):
        raise ValueError("INVALID_FRAME_SCOPE")
    if not isinstance(name, str) or not name or len(name) > 64:
        raise ValueError("INVALID_CONTROLLER_FRAME_NAME")
    return "realman:%s:%s:%s" % (arm, kind, quote(name, safe=""))

def decode_frame(sample, arm, kind):
    raw = sample["raw_response"]
    name = raw.get("frame_name" if kind == "work" else "tool_name")
    pose = decode_pose(raw.get("pose"), sample["transport"])
    valid_name = isinstance(name, str) and 0 < len(name) <= 64
    return {"name": name, "id": frame_id(arm, kind, name) if valid_name else None,
            "reported": valid_name and pose["units_confirmed"], "pose": pose,
            "raw_response": raw, "received_at": sample["received_at"],
            "relative_to": "controller_base" if kind == "work" else "controller_flange",
            "definition_source": FRAME_SOURCE,
            "physical_calibration_status": "UNCONFIRMED",
            "note": "Controller-reported definition only; not a calibrated lab-world or grasp-center transform."}

def normalize_state(sample, work=None, tool=None, stable=False):
    raw = sample["raw_response"]
    state = raw.get("arm_state")
    if not isinstance(state, dict):
        raise ValueError("ARM_STATE_MISSING")
    joints = state.get("joint")
    ok = sample["transport"] == TRANSPORT and int_vector(joints, 6)
    joint = {"raw": joints, "raw_unit": "millidegree", "values_deg": [x/1000 for x in joints] if ok else None,
             "unit": "deg", "units_confirmed": ok, "conversion_count": 1 if ok else 0,
             "divisor": 1000 if ok else None}
    pose = decode_pose(state.get("pose"), sample["transport"])
    pose.update(frame=work.get("id") if work else None,
                work_frame_name=work.get("name") if work else None,
                tool_frame=tool.get("id") if tool else None,
                tool_frame_name=tool.get("name") if tool else None,
                frame_binding_status="UNCONFIRMED",
                frame_binding_note="Active frames read before/after state; pose-to-frame binding and physical meaning require confirmation.")
    err = state.get("err")
    # Official generations use either scalar or array; preserve raw alongside canonical list.
    errors = [err] if type(err) is int else err
    if not isinstance(errors, list) or not errors or any(type(x) is not int for x in errors):
        errors = None
    units = ok and pose["units_confirmed"]
    result = {
        "available": True, "captured_at": sample["received_at"], "raw_response": raw,
        "joints_deg": joint["values_deg"], "gripper_opening_fraction": None,
        "poses": {"controller_tool": pose} if pose["units_confirmed"] else {},
        "controller_errors": errors, "system_error_raw": err,
        "error_labels": {str(x): ("超速度限制" if x == 4105 else "UNKNOWN") for x in (errors or []) if x},
        "error_source": "get_current_arm_state.arm_state.err; 4105 mapping supplied by user",
        "error_clear_attempted": False, "state_units_confirmed": units,
        "frame_snapshot_stable": stable,
        "canonical": {"joint": joint, "pose": pose, "work_frame": work, "tool_frame": tool,
                      "system_errors": errors, "units_source": UNIT_SOURCE},
        "units_and_active_tool_frame": "UNITS_CONFIRMED_FRAME_BINDING_UNCONFIRMED" if units else "UNCONFIRMED",
        "provenance": {"transport": sample["transport"], "wrapper_used": False,
                       "input": "socket.recv -> strict_json (no unit conversion)",
                       "converter": "realman_state.normalize_state/decode_pose; one conversion only"},
    }
    return result

def query_state(host, port, timeout=3.0):
    """Compatibility: one raw state read, no frame claims."""
    return normalize_state(read_query(host, port, "get_current_arm_state", timeout))

def query_snapshot(host, port, arm, timeout=3.0):
    """Bracket state with frame reads; errors are recorded, never cleared."""
    samples, failures = {}, []
    order = (("work_before", "get_current_work_frame"), ("tool_before", "get_current_tool_frame"),
             ("state", "get_current_arm_state"), ("work_after", "get_current_work_frame"),
             ("tool_after", "get_current_tool_frame"))
    for label, command in order:
        try:
            samples[label] = read_query(host, port, command, timeout)
        except Exception as exc:
            failures.append({"query": command, "phase": label, "error": str(exc)[:250]})
    if "state" not in samples:
        return {"available": False, "captured_at": time.time(), "controller_errors": None,
                "state_units_confirmed": False, "frame_snapshot_stable": False,
                "joints_deg": None, "poses": {}, "queries": samples, "query_failures": failures}
    work = decode_frame(samples["work_before"], arm, "work") if "work_before" in samples else None
    tool = decode_frame(samples["tool_before"], arm, "tool") if "tool_before" in samples else None
    stable = bool(work and tool and work["reported"] and tool["reported"] and
                  all(label in samples for label, _ in order) and
                  samples["work_before"]["raw_response"] == samples["work_after"]["raw_response"] and
                  samples["tool_before"]["raw_response"] == samples["tool_after"]["raw_response"])
    result = normalize_state(samples["state"], work, tool, stable)
    result.update(queries=samples, query_failures=failures,
                  frame_snapshot_atomic=False, frame_read_finished_at=time.time())
    return result
