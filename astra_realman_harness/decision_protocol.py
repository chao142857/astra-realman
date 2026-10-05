"""One strict ActionProposal contract shared by all decision backends."""
import re
from io_utils import strict_json, vector

KEYS = frozenset(("action_type", "arm", "frame", "tool_frame", "translation_m",
                  "rotation_rpy_rad", "gripper", "done"))

def validate_action(value, *, translation_limit_m=.002):
    if type(translation_limit_m) not in (int, float) or translation_limit_m not in (.002, .003):
        return ["ACTION_TRANSLATION_POLICY"]
    errors = []
    if not isinstance(value, dict) or set(value) != KEYS:
        return ["ACTION_SCHEMA_FIELDS"]
    if value["action_type"] != "cartesian_delta":
        errors.append("ACTION_TYPE")
    if value["arm"] not in ("left", "right"):
        errors.append("ACTION_ARM")
    if not isinstance(value["frame"], str) or not re.fullmatch(
            r"realman:(left|right):work:[A-Za-z0-9_.:-]{1,64}", value["frame"]):
        errors.append("ACTION_FRAME")
    if not isinstance(value["tool_frame"], str) or not re.fullmatch(
            r"realman:(left|right):tool:[A-Za-z0-9_.:-]{1,64}", value["tool_frame"]):
        errors.append("ACTION_TOOL_FRAME")
    if isinstance(value["frame"], str) and not value["frame"].startswith("realman:%s:work:" % value["arm"]):
        errors.append("ACTION_FRAME_ARM_MISMATCH")
    if isinstance(value["tool_frame"], str) and not value["tool_frame"].startswith("realman:%s:tool:" % value["arm"]):
        errors.append("ACTION_TOOL_FRAME_ARM_MISMATCH")
    if not vector(value["translation_m"], 3):
        errors.append("ACTION_TRANSLATION")
    elif any(abs(v) > translation_limit_m for v in value["translation_m"]):
        errors.append("TRANSLATION_AXIS_LIMIT")
    if not vector(value["rotation_rpy_rad"], 3) or any(v != 0 for v in value["rotation_rpy_rad"]):
        errors.append("ROTATION_DISABLED")
    if value["gripper"] != "hold":
        errors.append("GRIPPER_DISABLED")
    if type(value["done"]) is not bool:
        errors.append("ACTION_DONE_TYPE")
    return errors

def parse_action(raw, *, translation_limit_m=.002):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("BACKEND_EMPTY_OUTPUT")
    if len(raw.encode("utf-8")) > 65536:
        raise ValueError("BACKEND_OUTPUT_TOO_LARGE")
    value = strict_json(raw)  # No Markdown extraction, repair, clipping, or NL conversion.
    errors = validate_action(value, translation_limit_m=translation_limit_m)
    if errors:
        raise ValueError("ACTION_SCHEMA_REJECT:" + ",".join(errors))
    return value
