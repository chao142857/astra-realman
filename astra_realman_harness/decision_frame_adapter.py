"""Backend-independent adapter. Unknown SDK pose frames remain unknown."""
import copy
import time
from io_utils import vector

def adapt_observation(observation):
    arms = {}
    for arm, canonical in observation["canonical_states"].items():
        ee = canonical.get("ee_pose", {})
        work = canonical.get("work_frame", {}).get("name")
        tool = canonical.get("tool_frame", {}).get("name")
        work_id = "realman:%s:work:%s" % (arm, work) if work else None
        tool_id = "realman:%s:tool:%s" % (arm, tool) if tool else None
        # Names and zero offsets never establish a pose's reference/target frames.
        confirmed = (ee.get("frame_semantics_status") == "CONFIRMED" and
                     ee.get("reference_frame") == work_id and ee.get("target_frame") == tool_id)
        pose = {"reference_frame": work_id, "tool_frame": tool_id,
                "frame_binding_status": "CONFIRMED" if confirmed else "UNCONFIRMED"}
        arms[arm] = {
            "available": bool(canonical.get("joint_deg")),
            "captured_at": canonical.get("timestamp"),
            "joints_deg": canonical.get("joint_deg"),
            "controller_errors": canonical.get("system_error", {}).get("codes"),
            "state_units_confirmed": (canonical.get("source", {}).get("joint_unit") == "deg" and
                                      ee.get("units") == {"xyz": "m", "rpy": "rad"} and
                                      ee.get("unit_scale_applied") == 1),
            "frame_snapshot_stable": canonical.get("frame_snapshot_stable"),
            "canonical": {"pose": pose}, "poses": {},
            "sdk_canonical": copy.deepcopy(canonical)
        }
        if confirmed and vector(ee.get("xyz_m"), 3) and vector(ee.get("rpy_rad"), 3):
            arms[arm]["poses"]["controller_tool"] = {
                "frame": work_id, "tool_frame": tool_id, "position_m": list(ee["xyz_m"]),
                "rpy_rad": list(ee["rpy_rad"]), "frame_binding_status": "CONFIRMED"}
    result = copy.deepcopy(observation)
    result["schema_version"] = "astra.observation.v1"
    result["robot"] = {"arms": arms}
    return result

def adapt_action(action, observation, created_at):
    tool = observation["canonical_states"].get(action["arm"], {}).get("tool_frame", {}).get("name")
    if not tool or action.get("tool_frame") != "realman:%s:tool:%s" % (action["arm"], tool):
        raise ValueError("CURRENT_TOOL_FRAME_UNAVAILABLE_OR_MISMATCH")
    return {
        "schema_version": "astra.realman.proposal.v1",
        "proposal_id": "decision-" + observation["observation_id"],
        "observation_id": observation["observation_id"],
        "created_at": created_at, "expires_at": created_at + 30,
        "reason": "Structured decision backend shadow proposal; no execution",
        "actions": [{"type": "move_delta", "arm": action["arm"], "frame": action["frame"],
                     "target": "controller_tool", "tool_frame": action["tool_frame"],
                     "delta_m": list(action["translation_m"]), "speed_m_s": .005}]
    }


# Trusted adapter declaration: no camera-frame value is transformed into a robot
# command. The model's proposal already declares a robot work-frame delta.
TRANSFORM_CONTRACT = {
    "id": "robot_work_delta_identity.v2",
    "camera_to_robot_transform_used": False,
    "method": "Use explicitly declared work-axis delta; no camera extrinsic transform.",
}

def current_frame_ids(state):
    work, tool = state.get("work_frame"), state.get("tool_frame")
    return (work.get("id") if isinstance(work, dict) else None,
            tool.get("id") if isinstance(tool, dict) else None)

def local_translation_preview(action, state):
    """Only produce a position preview for a formally bound, matching EE pose."""
    ee = state.get("ee_pose", {})
    if (ee.get("frame_semantics_status") != "CONFIRMED" or
            ee.get("reference_frame_id") != action["frame"] or
            ee.get("target_frame_id") != action["tool_frame"] or
            not vector(ee.get("xyz_m"), 3) or not vector(ee.get("rpy_rad"), 3)):
        return {"status": "UNAVAILABLE", "reason": "EE_POSE_FRAME_BINDING_UNCONFIRMED",
                "execution_permitted": False}
    return {"status": "NUMERIC_PREVIEW_ONLY", "frame": action["frame"], "tool_frame": action["tool_frame"],
            "start_xyz_m": list(ee["xyz_m"]),
            "target_xyz_m": [x+d for x,d in zip(ee["xyz_m"],action["translation_m"])],
            "rpy_rad": list(ee["rpy_rad"]), "execution_permitted": False}
