"""Strict, versioned proposals. This module has no device access."""
import math
import re
from io_utils import identifier, number, vector, strict_json

VERSION = "astra.realman.proposal.v1"
COMMON = {"type", "arm", "frame"}
FIELDS = {
    "move_delta": COMMON | {"target", "delta_m", "speed_m_s"},
    "move_pose": COMMON | {"target", "position_m", "quaternion_wxyz", "speed_m_s"},
    "gripper": COMMON | {"opening_fraction"},
    "hold": COMMON | {"duration_s"},
    "observe": COMMON,
}
TOP = {"schema_version", "proposal_id", "observation_id", "created_at",
       "expires_at", "reason", "actions"}

def validate(proposal):
    errors = []
    if not isinstance(proposal, dict) or set(proposal) != TOP:
        return ["PROPOSAL_FIELDS"]
    if proposal["schema_version"] != VERSION:
        errors.append("SCHEMA_VERSION")
    for field in ("proposal_id", "observation_id"):
        if not identifier(proposal[field]):
            errors.append("INVALID_" + field.upper())
    for field in ("created_at", "expires_at"):
        if not number(proposal[field]) or proposal[field] <= 0:
            errors.append("INVALID_" + field.upper())
    if not isinstance(proposal["reason"], str) or not 1 <= len(proposal["reason"]) <= 2000:
        errors.append("REASON_REQUIRED")
    actions = proposal["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 3:
        return errors + ["ACTION_COUNT"]
    for i, a in enumerate(actions):
        prefix = "ACTION_%d:" % i
        if not isinstance(a, dict) or not isinstance(a.get("type"), str):
            errors.append(prefix + "TYPE")
            continue
        kind = a["type"]
        expected_fields = FIELDS.get(kind, set())
        if kind in ("move_delta", "move_pose") and a.get("target") == "controller_tool":
            expected_fields = expected_fields | {"tool_frame"}
        if kind not in FIELDS or set(a) != expected_fields:
            errors.append(prefix + "FIELDS_OR_TYPE")
            continue
        arm = a["arm"]
        if arm not in ("left", "right"):
            errors.append(prefix + "ARM")
        expected = str(arm) + ("_gripper" if kind == "gripper" else "_base")
        named = kind in ("move_delta", "move_pose") and a.get("target") == "controller_tool"
        if named:
            pattern = r"realman:" + str(arm) + r":work:[A-Za-z0-9_.%~-]{1,256}"
            tool_pattern = r"realman:" + str(arm) + r":tool:[A-Za-z0-9_.%~-]{1,256}"
            if not isinstance(a["frame"], str) or not re.fullmatch(pattern, a["frame"]):
                errors.append(prefix + "NAMED_WORK_FRAME")
            if not isinstance(a.get("tool_frame"), str) or not re.fullmatch(tool_pattern, a["tool_frame"]):
                errors.append(prefix + "NAMED_TOOL_FRAME")
        elif a["frame"] != expected:
            errors.append(prefix + "FRAME_MUST_BE_" + expected)
        if kind in ("move_delta", "move_pose"):
            if a["target"] not in ("tcp", "flange", "controller_tool"):
                errors.append(prefix + "TARGET")
            if not number(a["speed_m_s"]) or a["speed_m_s"] <= 0:
                errors.append(prefix + "SPEED")
        if kind == "move_delta" and not vector(a["delta_m"], 3):
            errors.append(prefix + "DELTA")
        if kind == "move_pose":
            if not vector(a["position_m"], 3):
                errors.append(prefix + "POSITION")
            q = a["quaternion_wxyz"]
            if not vector(q, 4) or abs(sum(x*x for x in q) - 1.0) > 0.002:
                errors.append(prefix + "QUATERNION")
        if kind == "gripper":
            g = a["opening_fraction"]
            if not number(g) or not 0 <= g <= 1:
                errors.append(prefix + "GRIPPER_RANGE")
        if kind == "hold" and (not number(a["duration_s"]) or not 0 < a["duration_s"] <= 2):
            errors.append(prefix + "HOLD_DURATION")
    return errors

def parse(text):
    proposal = strict_json(text)
    errors = validate(proposal)
    if errors:
        raise ValueError(";".join(errors))
    return proposal

def fixture_proposal(observation, now, arm="right"):
    """Synthetic test output; never described as a model/API result."""
    if arm not in ("left", "right"):
        raise ValueError("INVALID_FIXTURE_ARM")
    action = {"type": "move_delta", "arm": arm, "frame": arm + "_base",
              "target": "tcp", "delta_m": [0, 0, 0.005], "speed_m_s": 0.005}
    if observation.get("source", {}).get("kind") == "real_capture":
        state = observation.get("robot", {}).get("arms", {}).get(arm, {})
        canonical = state.get("canonical", {})
        work, tool = canonical.get("work_frame"), canonical.get("tool_frame")
        if not work or not tool or not work.get("reported") or not tool.get("reported"):
            raise ValueError("FIXTURE_REQUIRES_REPORTED_CURRENT_FRAMES")
        action.update(frame=work["id"], target="controller_tool", tool_frame=tool["id"])
    return {
        "schema_version": VERSION, "proposal_id": "fixture-" + observation["observation_id"],
        "observation_id": observation["observation_id"],
        "created_at": now, "expires_at": now + 20,
        "reason": "SYNTHETIC FIXTURE: +5 mm on declared work-frame Z, not assumed lab vertical; no API or execution.",
        "actions": [action]
    }
