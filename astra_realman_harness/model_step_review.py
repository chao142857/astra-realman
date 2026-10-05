"""Pure review of one observed model step; never imports or calls hardware code."""
from copy import deepcopy
from decision_protocol import validate_action
from io_utils import number, vector

EVIDENCE_LOG = "/home/tongji/alex/astra_realman_harness/logs/supervised-step-20261002T203531-b1cddd33"
WORK_ID = "realman:left:work:World"
TOOL_ID = "realman:left:tool:Arm_Tip"
FRAME_FINGERPRINTS = {
    "work_frame": "5eb2b7dec61339bd9dffd69371bc53796702c56935fec3013477fb062df15a7b",
    "tool_frame": "96597c27c1da9c9743f5374b56f0a156394a5a8793821b5ae1c6b18bc8e3df77",
}

def _dict(value):
    return value if isinstance(value, dict) else {}

def review_proposal(action, observation, now, generated_at):
    """Review an exact segment for display, not for execution.

    EXECUTE is an external operator approval step. An executor must separately
    refresh controller state/frame/error, reject scene/state drift, consume a
    one-shot approval and issue at most one command. This module cannot grant
    execution or manufacture a local workspace from a step-size limit.
    """
    obs = _dict(observation)
    a = _dict(action)
    gates, errors = [], []

    def gate(name, valid, error, details=None):
        gates.append({"gate": name, "status": "PASS" if valid else "FAIL",
                      "blocking": not valid, "details": details})
        if not valid:
            errors.append(error)

    schema_errors = validate_action(action, translation_limit_m=.003)
    gate("single_structured_action", not schema_errors, "ACTION_SCHEMA_REJECT", schema_errors)
    errors.extend(schema_errors)
    delta = a.get("translation_m")
    nonzero = bool(not schema_errors and any(v != 0 for v in delta))
    gate("left_arm_only", a.get("arm") == "left", "LEFT_ARM_REQUIRED")
    gate("translation_axis_limit", vector(delta, 3) and all(abs(v) <= .003 for v in delta),
         "TRANSLATION_AXIS_LIMIT", {"limit_m": .003, "requested": delta})
    gate("rotation_zero", vector(a.get("rotation_rpy_rad"), 3) and
         all(v == 0 for v in a["rotation_rpy_rad"]), "ROTATION_DISABLED")
    gate("gripper_hold", a.get("gripper") == "hold", "GRIPPER_DISABLED")
    states = _dict(obs.get("canonical_states"))
    gate("both_robot_states", set(states) == {"left", "right"}, "BOTH_STATES_REQUIRED")
    stamps = []
    for arm in ("left", "right"):
        s = _dict(states.get(arm))
        ee, fault = _dict(s.get("ee_pose")), _dict(s.get("system_error"))
        codes = fault.get("codes")
        healthy = (isinstance(codes, list) and bool(codes) and
                   all(type(c) is int and c == 0 for c in codes) and
                   fault.get("has_error") is False)
        gate(arm + "_controller_health", healthy, arm.upper() + "_ERROR_OR_UNKNOWN", fault)
        units = (s.get("arm") == arm and vector(s.get("joint_deg"), 6) and
                 vector(ee.get("xyz_m"), 3) and vector(ee.get("rpy_rad"), 3) and
                 ee.get("units") == {"xyz": "m", "rpy": "rad"} and
                 number(ee.get("unit_scale_applied")) and ee["unit_scale_applied"] == 1 and
                 _dict(s.get("source")).get("joint_unit") == "deg")
        gate(arm + "_native_units", units, arm.upper() + "_UNITS_UNKNOWN")
        raw = _dict(s.get("raw_sdk_state"))
        gate(arm + "_raw_values_preserved", raw.get("joint") == s.get("joint_deg") and
             vector(raw.get("pose"), 6) and raw["pose"][:3] == ee.get("xyz_m") and
             raw["pose"][3:] == ee.get("rpy_rad"), arm.upper() + "_RAW_VALUE_MISMATCH")
        stamps.append(s.get("timestamp"))

    left = _dict(states.get("left"))
    connection = _dict(left.get("connection"))
    gate("physical_left_controller", connection.get("arm") == "left" and
         connection.get("ip") == "192.168.1.19" and connection.get("port") == 8080 and
         connection.get("connection_verified") is True and
         type(connection.get("sdk_handle_id")) is int and connection["sdk_handle_id"] > 0,
         "LEFT_ENDPOINT_UNCONFIRMED", {"ip": connection.get("ip"), "user_evidence": "19左，用19"})
    gate("frame_snapshot_stable", left.get("frame_snapshot_stable") is True,
         "LEFT_FRAME_CHANGED_DURING_CAPTURE")
    for key, name, frame_id in (("work_frame", "World", WORK_ID),
                               ("tool_frame", "Arm_Tip", TOOL_ID)):
        frame = _dict(left.get(key))
        raw = _dict(left.get("raw_" + key))
        pose = _dict(frame.get("pose"))
        zero_pose = (vector(pose.get("xyz_m"), 3) and vector(pose.get("rpy_rad"), 3) and
                     all(v == 0 for v in pose["xyz_m"] + pose["rpy_rad"]))
        ok = (frame.get("id") == frame_id and frame.get("name") == name and
              frame.get("read_status") == "VERIFIED" and
              frame.get("definition_fingerprint") == FRAME_FINGERPRINTS[key] and
              pose.get("units") == {"xyz": "m", "rpy": "rad"} and zero_pose and
              raw.get("name") == name and vector(raw.get("pose"), 6) and
              all(v == 0 for v in raw["pose"]))
        gate(key + "_matches_verified_definition", ok, key.upper() + "_CHANGED_OR_UNKNOWN",
             {"id": frame.get("id"), "name": frame.get("name"), "pose": pose})
    gate("proposal_uses_current_frames", a.get("frame") == WORK_ID and
         a.get("tool_frame") == TOOL_ID, "ACTION_FRAME_MISMATCH")
    ctx = _dict(obs.get("decision_safety_context"))
    evidence = _dict(ctx.get("relative_work_motion"))
    gate("verified_work_relative_motion", evidence.get("status") == "VERIFIED_BY_REAL_SINGLE_STEP" and
         evidence.get("source") == EVIDENCE_LOG + "/summary.json" and evidence.get("arm") == "left" and
         evidence.get("work_frame_id") == WORK_ID and evidence.get("tool_frame_id") == TOOL_ID,
         "RELATIVE_MOTION_EVIDENCE_MISSING", evidence)
    for key in ("work_frame", "tool_frame"):
        prior_frame = _dict(evidence.get(key))
        current_frame = _dict(left.get(key))
        gate(key + "_same_as_real_step", bool(prior_frame) and
             prior_frame.get("id") == current_frame.get("id") and
             prior_frame.get("definition_fingerprint") == current_frame.get("definition_fingerprint") and
             prior_frame.get("pose") == current_frame.get("pose"),
             key.upper() + "_DIFFERS_FROM_VERIFIED_STEP")
    gates.append({"gate": "current_teach_frame_is_work", "status": "PENDING_FRESH_RECHECK",
                  "blocking_execution": nonzero,
                  "details": "Read rm_get_teach_frame after EXECUTE; require work mode=0 before any command."})

    cameras = obs.get("cameras")
    cameras = cameras if isinstance(cameras, list) else []
    metrics = _dict(obs.get("camera_capture"))
    serials = [c.get("serial") for c in cameras if isinstance(c, dict)]
    expected = metrics.get("expected_serials")
    ct = [c.get("captured_at") for c in cameras if isinstance(c, dict)]
    camera_set_ok = (len(cameras) == 4 and len(serials) == 4 and
                     all(isinstance(s, str) and s for s in serials) and len(set(serials)) == 4 and
                     isinstance(expected, list) and len(expected) == 4 and
                     set(serials) == set(expected) and not obs.get("capture_failures") and
                     all(isinstance(c.get("image_path"), str) and c["image_path"].startswith("/")
                         for c in cameras))
    gate("four_current_images", camera_set_ok, "FOUR_IMAGE_CAPTURE_REQUIRED",
         {"serials": serials, "capture_failures": obs.get("capture_failures")})
    span = (max(ct) - min(ct)) * 1000 if len(ct) == 4 and all(number(t) for t in ct) else None
    gate("camera_timestamp_record", number(span) and number(obs.get("capture_span_ms")) and
         abs(span - obs["capture_span_ms"]) <= .001 and
         metrics.get("timestamp_semantics_confirmed") is True, "CAMERA_TIMING_RECORD_INVALID",
         {"capture_span_ms": span, "hardware_synchronized": metrics.get("hardware_synchronized")})

    start, end = obs.get("capture_started_at"), obs.get("capture_finished_at")
    captured = obs.get("captured_at")
    all_times = [now, generated_at, start, end, captured] + stamps + ct
    times_valid = all(number(t) for t in all_times) and len(ct) == 4
    ordered = (times_valid and start <= end <= generated_at + .1 <= now + 1.1 and
               start - .1 <= captured <= end + .1 and
               all(start - 1 <= t <= end + .1 for t in stamps + ct) and
               -1 <= now - min(stamps + ct + [start]) <= 180)
    gate("capture_proposal_time_order", ordered, "CAPTURE_OR_PROPOSAL_TIME_INVALID",
         {"review_age_limit_s": 180, "fresh_state_required_before_execution": True,
          "generated_at": generated_at, "capture_started_at": start, "capture_finished_at": end})

    ee = _dict(left.get("ee_pose"))
    current = {"xyz_m": deepcopy(ee.get("xyz_m")), "rpy_rad": deepcopy(ee.get("rpy_rad")),
               "frame": WORK_ID, "tool_frame": TOOL_ID,
               "semantics": "relative step preview bound to prior real World-motion verification"}
    target = None
    if vector(current["xyz_m"], 3) and vector(current["rpy_rad"], 3) and vector(delta, 3):
        target = deepcopy(current)
        target["xyz_m"] = [current["xyz_m"][i] + delta[i] for i in range(3)]
    gates.append({"gate": "local_workspace", "status": "PENDING_OPERATOR_CONFIRMATION" if nonzero
                  else "NOT_APPLICABLE", "blocking_execution": nonzero,
                  "scope": "operator_review_of_this_exact_segment",
                  "details": {"start": current, "target": target,
                  "note": "No box inferred from step limits; EXECUTE approves only the displayed segment."}})
    gates.append({"gate": "operator_execute", "status": "PENDING" if nonzero else "NOT_APPLICABLE",
                  "blocking_execution": nonzero, "required_input": "EXECUTE"})
    return {"status": "REJECT" if errors else ("AWAITING_EXECUTE" if nonzero else "PASS_NOOP"),
            "gates": gates, "errors": list(dict.fromkeys(errors)), "action": deepcopy(action),
            "current_pose": current, "target_pose": target, "nonzero": nonzero,
            "capture_span_ms": span, "execution_permitted": False, "motion_commands_sent": 0,
            "fresh_state_required_before_execution": True,
            "excluded_from_relative_motion_gates": ["camera_extrinsics", "offline_DH_model", "full_tool_geometry"],
            "approval_scope": "This displayed proposal and segment only; no second action or loop."}
