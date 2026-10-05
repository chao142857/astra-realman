"""Independent policy evaluator. A passed check NEVER authorizes execution."""
import math
from io_utils import number, vector
from protocol import validate
from transforms import rpy_to_quaternion, delta_preview

def check_policy(policy):
    if policy.get("mode") != "dry_run_only":
        raise ValueError("POLICY_MODE_MUST_BE_DRY_RUN_ONLY")
    if type(policy.get("fixture_only")) is not bool:
        raise ValueError("FIXTURE_FLAG_MUST_BE_BOOLEAN")
    for key in ("max_observation_age_s", "max_proposal_age_s", "max_proposal_ttl_s",
                "max_clock_skew_s", "max_translation_m", "max_rotation_deg",
                "max_speed_m_s", "max_gripper_change", "max_camera_skew_s"):
        if not number(policy.get(key)) or policy[key] <= 0:
            raise ValueError("INVALID_POLICY:" + key)
    if type(policy.get("max_actions")) is not int or policy["max_actions"] != 1:
        raise ValueError("THIS_HARNESS_REQUIRES_SINGLE_ACTION")
    if not isinstance(policy.get("allowed_arms"), list) or not policy["allowed_arms"]:
        raise ValueError("ALLOWED_ARMS_REQUIRED")
    if any(a not in ("left", "right") for a in policy["allowed_arms"]):
        raise ValueError("INVALID_ALLOWED_ARM")
    for arm in policy["allowed_arms"]:
        c = policy.get("arms", {}).get(arm)
        if not isinstance(c, dict):
            raise ValueError("ARM_POLICY_REQUIRED:" + arm)
        for name in ("base_frame_confirmed", "arm_identity_confirmed", "tcp_confirmed",
                     "gripper_mapping_confirmed", "camera_registration_confirmed"):
            if type(c.get(name)) is not bool:
                raise ValueError("CONFIRMATION_MUST_BE_BOOLEAN:" + name)
        workspace = c.get("workspace_m")
        if workspace is not None:
            if (not isinstance(workspace, dict) or set(workspace) != {"min", "max"}
                    or not vector(workspace["min"], 3) or not vector(workspace["max"], 3)
                    or any(x >= y for x, y in zip(workspace["min"], workspace["max"]))):
                raise ValueError("INVALID_WORKSPACE")
    return policy

def assess(proposal, observation, policy, now):
    check_policy(policy)
    errors = validate(proposal)
    if policy.get("fixture_only") is True and observation.get("source", {}).get("kind") != "offline_fixture":
        errors.append("SYNTHETIC_POLICY_FORBIDDEN_FOR_REAL_OBSERVATION")
    checked = []
    if not errors:
        if not isinstance(observation, dict) or observation.get("schema_version") != "astra.observation.v1":
            errors.append("OBSERVATION_SCHEMA")
        elif proposal["observation_id"] != observation.get("observation_id"):
            errors.append("OBSERVATION_ID_MISMATCH")
        capture = observation.get("captured_at") if isinstance(observation, dict) else None
        if not number(capture):
            errors.append("OBSERVATION_TIME_INVALID")
        elif now - capture > policy["max_observation_age_s"]:
            errors.append("STALE_OBSERVATION")
        elif capture - now > policy["max_clock_skew_s"]:
            errors.append("FUTURE_OBSERVATION")
        created, expires = proposal["created_at"], proposal["expires_at"]
        if created - now > policy["max_clock_skew_s"]:
            errors.append("FUTURE_PROPOSAL")
        if now - created > policy["max_proposal_age_s"]:
            errors.append("STALE_PROPOSAL")
        if number(capture) and created < capture - policy["max_clock_skew_s"]:
            errors.append("PROPOSAL_PREDATES_OBSERVATION")
        if expires <= now or expires <= created:
            errors.append("EXPIRED_PROPOSAL")
        if expires - created > policy["max_proposal_ttl_s"]:
            errors.append("PROPOSAL_TTL_TOO_LONG")
        if len(proposal["actions"]) > policy["max_actions"]:
            errors.append("TOO_MANY_ACTIONS_FOR_POLICY")
    if not errors:
        arms = observation.get("robot", {}).get("arms", {})
        if not isinstance(arms, dict):
            errors.append("ROBOT_STATE_SCHEMA")
            arms = {}
        real = observation.get("source", {}).get("kind") == "real_capture"
        if real:
            # Validate all arms enabled by trusted policy, including any enabled non-target arm.
            # Inactive arms cannot be proposed and are not queried or required.
            for name in policy["allowed_arms"]:
                other = arms.get(name, {})
                faults = other.get("controller_errors")
                if not isinstance(faults, list) or not faults or any(type(x) is not int for x in faults):
                    errors.append("ARM_%s:CONTROLLER_STATUS_UNAVAILABLE" % name)
                elif any(x != 0 for x in faults):
                    errors.append("ARM_%s:CONTROLLER_ERROR_PRESENT" % name)
                if other.get("state_units_confirmed") is not True:
                    errors.append("ARM_%s:STATE_UNITS_UNCONFIRMED" % name)
                if other.get("frame_snapshot_stable") is not True:
                    errors.append("ARM_%s:FRAME_SNAPSHOT_UNCONFIRMED" % name)
                if not other.get("canonical", {}).get("pose", {}).get("frame_binding_status") == "CONFIRMED":
                    errors.append("ARM_%s:STATE_FRAME_BINDING_UNCONFIRMED" % name)
            metrics = observation.get("camera_capture", {})
            if metrics.get("timestamp_semantics_confirmed") is not True:
                errors.append("CAMERA_TIMESTAMP_SEMANTICS_UNCONFIRMED")
            expected = metrics.get("expected_serials")
            actual = [c.get("serial") for c in observation.get("cameras", [])]
            if not expected or len(actual) != len(set(actual)) or set(actual) != set(expected):
                errors.append("CAMERA_SET_INCOMPLETE")
            ct = [c.get("captured_at") for c in observation.get("cameras", [])]
            if not ct or not all(number(t) for t in ct):
                errors.append("CAMERA_TIMESTAMP_UNAVAILABLE")
            else:
                span = (max(ct)-min(ct))*1000
                reported_span = observation.get("capture_span_ms")
                if not number(reported_span) or abs(reported_span-span) > .001:
                    errors.append("CAMERA_SPAN_INCONSISTENT")
                if span > policy["max_camera_skew_s"]*1000:
                    errors.append("CAMERA_TIME_SKEW")
            if observation.get("capture_failures"):
                errors.append("OBSERVATION_CAPTURE_FAILURE")
        cameras = observation.get("cameras", [])
        timestamps = [c.get("captured_at") for c in cameras if isinstance(c, dict)]
        for i, a in enumerate(proposal["actions"]):
            e = []
            arm, kind = a["arm"], a["type"]
            if arm not in policy["allowed_arms"]:
                e.append("ARM_NOT_ALLOWED")
            else:
                config = policy["arms"][arm]
                state = arms.get(arm, {})
                if not isinstance(state, dict):
                    state = {}
                if kind != "observe":
                    if config["arm_identity_confirmed"] is not True:
                        e.append("ARM_IDENTITY_UNCONFIRMED")
                    if not number(state.get("captured_at")):
                        e.append("STATE_TIME_UNAVAILABLE")
                    elif (now - state["captured_at"] > policy["max_observation_age_s"]
                          or state["captured_at"] - now > policy["max_clock_skew_s"]):
                        e.append("STATE_STALE_OR_FUTURE")
                    faults = state.get("controller_errors")
                    if not isinstance(faults, list) or not faults or any(type(v) is not int for v in faults):
                        e.append("CONTROLLER_STATUS_UNAVAILABLE")
                    elif any(v != 0 for v in faults):
                        e.append("CONTROLLER_ERROR_PRESENT")
                    if state.get("available") is not True:
                        e.append("ROBOT_STATE_UNAVAILABLE")
                    if not vector(state.get("joints_deg"), 6):
                        e.append("JOINT_STATE_UNAVAILABLE")
                if kind in ("move_delta", "move_pose"):
                    if a["target"] == "controller_tool":
                        pose = state.get("canonical", {}).get("pose", {})
                        if (config.get("controller_frame_mapping_confirmed") is not True or
                                pose.get("frame_binding_status") != "CONFIRMED"):
                            e.append("CONTROLLER_FRAME_MAPPING_UNCONFIRMED")
                        if config.get("controller_tool_geometry_confirmed") is not True:
                            e.append("CONTROLLER_TOOL_GEOMETRY_UNCONFIRMED")
                        if pose.get("tool_frame") != a.get("tool_frame"):
                            e.append("CURRENT_TOOL_FRAME_MISMATCH")
                    elif not config["base_frame_confirmed"]:
                        e.append("BASE_FRAME_UNCONFIRMED")
                    if a["target"] == "tcp" and not config["tcp_confirmed"]:
                        e.append("TCP_UNCONFIRMED")
                    if not config["camera_registration_confirmed"]:
                        e.append("CAMERA_REGISTRATION_UNCONFIRMED")
                    if (not timestamps or not all(number(t) for t in timestamps)
                            or any(now-t > policy["max_observation_age_s"] or
                                   t-now > policy["max_clock_skew_s"] for t in timestamps)):
                        e.append("CAMERA_TIME_UNAVAILABLE_OR_STALE")
                    elif max(timestamps)-min(timestamps) > policy["max_camera_skew_s"]:
                        e.append("CAMERA_TIME_SKEW")
                    current = state.get("poses", {}).get(a["target"]) if isinstance(state.get("poses"), dict) else None
                    if not isinstance(current, dict) or current.get("frame") != a["frame"] or not vector(current.get("position_m"), 3):
                        e.append("CURRENT_POSE_UNAVAILABLE")
                        current = None
                    target = None
                    if a["speed_m_s"] > policy["max_speed_m_s"]:
                        e.append("SPEED_LIMIT")
                    if kind == "move_delta":
                        distance = math.sqrt(sum(x*x for x in a["delta_m"]))
                        if current:
                            target = [x+d for x,d in zip(current["position_m"], a["delta_m"])]
                    else:
                        distance = (math.sqrt(sum((x-y)**2 for x,y in zip(a["position_m"],current["position_m"])))
                                    if current else None)
                        target = a["position_m"]
                        cq = rpy_to_quaternion(current.get("rpy_rad")) if current else None
                        if not vector(cq, 4) or abs(sum(x*x for x in cq)-1) > 0.002:
                            e.append("CURRENT_ORIENTATION_UNAVAILABLE")
                        else:
                            norm = math.sqrt(sum(x*x for x in cq) * sum(x*x for x in a["quaternion_wxyz"]))
                            dot = abs(sum(x*y for x,y in zip(cq,a["quaternion_wxyz"]))) / norm
                            rotation = math.degrees(2*math.acos(min(1.0,dot)))
                            if rotation > policy["max_rotation_deg"]:
                                e.append("ROTATION_LIMIT")
                    if distance is not None and distance > policy["max_translation_m"] + 1e-12:
                        e.append("TRANSLATION_LIMIT")
                    ws = config["workspace_m"]
                    if ws is None:
                        e.append("WORKSPACE_UNCONFIRMED")
                    elif target is not None:
                        points = [target] + ([current["position_m"]] if current else [])
                        if any(not all(lo <= p <= hi for lo,p,hi in zip(ws["min"],point,ws["max"])) for point in points):
                            e.append("WORKSPACE_LIMIT")
                elif kind == "gripper":
                    if not config["gripper_mapping_confirmed"]:
                        e.append("GRIPPER_MAPPING_UNCONFIRMED")
                    old = state.get("gripper_opening_fraction")
                    if not number(old) or not 0 <= old <= 1:
                        e.append("GRIPPER_STATE_UNAVAILABLE")
                    elif abs(a["opening_fraction"]-old) > policy["max_gripper_change"]:
                        e.append("GRIPPER_STEP_LIMIT")
            checked.append({"index": i, "type": kind, "arm": arm, "errors": e,
                            "transform_preview": delta_preview(a, arms.get(arm, {})) if kind == "move_delta" else None})
            errors.extend("ACTION_%d:%s" % (i, x) for x in e)
    return {
        "decision": "REJECTED" if errors else "VALID_DRY_RUN_ONLY",
        "errors": errors, "actions_checked": checked,
        "execution_permitted": False, "hardware_commands_sent": 0,
        "execution_backend": "NOT_IMPLEMENTED",
        "remaining_execution_checks": ["operator authorization", "verified frame/TCP/calibration",
                                        "IK and collision-checked trajectory", "fresh state revalidation"],
    }
