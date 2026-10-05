"""Pure guard and one-attempt executor for one supervised 10 mm +World-Z step.

There is no SDK import, socket, file I/O, or hardware discovery here. The caller
must construct evidence from trusted readbacks, offline calculations, and the
specific operator statements, never from decision-model output. A persistent
one-shot claim belongs to the caller and must be acquired before using a port.
"""
import copy
import hashlib
import json
import math
import time

from decision_protocol import validate_action

SCHEMA_VERSION = "realman.supervised_step.v1"
WORK_ID = "realman:left:work:World"
TOOL_ID = "realman:left:tool:Arm_Tip"
MAX_AGE_S = 3.0
MAX_PRECHECK_JOINT_DRIFT_DEG = 0.02
MAX_PATH_JOINT_DELTA_DEG = 5.0
MAX_SAMPLE_JOINT_DELTA_DEG = 0.05
POSITION_TOLERANCE_M = 0.0002
ORIENTATION_TOLERANCE_RAD = 0.002
REQUIRED_READBACKS = (
    "rm_get_robot_info", "rm_get_arm_software_info", "rm_get_teach_frame",
    "rm_get_arm_max_line_speed", "rm_get_arm_max_line_acc",
)
HUMAN_EVIDENCE = {
    "arm_quote": "19左，用19",
    "authorization_quote": "让codex操作，缓慢操作，我手一直放在断电按钮上",
    "z_quote": "worldz是竖直向上",
    "clearance_quote": "不会碰到",
    "step_authorization_quote": "现在可以执行单步1cm的移动验证了",
    "scope": "left_World_plus_z_0.01m_only",
    "full_path_scope": "gripper_cables_and_arm",
}
EXACT_ACTION = {
    "action_type": "cartesian_delta", "arm": "left", "frame": WORK_ID,
    "tool_frame": TOOL_ID, "translation_m": [0, 0, 0.01],
    "rotation_rpy_rad": [0, 0, 0], "gripper": "hold", "done": False,
}
BINDING_KIND = "operator_ui_work_mode_and_documented_relative_position_step"

def _num(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False

def _vec(value, size):
    return isinstance(value, list) and len(value) == size and all(_num(x) for x in value)

def _ref(value):
    return isinstance(value, str) and bool(value.strip())

def _mapping(value):
    return value if isinstance(value, dict) else {}

def _fresh(stamp, now):
    return _num(stamp) and _num(now) and 0 <= now - stamp <= MAX_AGE_S

def _zero_return(value):
    return type(value) is int and value == 0

def _fingerprint(raw):
    try:
        return hashlib.sha256(json.dumps(raw, sort_keys=True, allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        return None

def _healthy(state):
    error = _mapping(state.get("system_error"))
    codes = error.get("codes")
    raw = _mapping(_mapping(state.get("raw_sdk_state")).get("err"))
    raw_codes = raw.get("err")
    if not (isinstance(codes, list) and isinstance(raw_codes, list) and
            type(raw.get("err_len")) is int and raw["err_len"] == len(raw_codes)):
        return False
    normalized = []
    for code in raw_codes:
        if type(code) is int and code >= 0:
            normalized.append(code)
        elif isinstance(code, str) and code.isascii() and code.isdigit():
            normalized.append(int(code))
        else:
            return False
    return (all(type(code) is int and code == 0 for code in codes) and
            codes == normalized and error.get("raw") == raw and
            error.get("has_error") is False)

def _sdk_units(state):
    source = _mapping(state.get("source"))
    pose = _mapping(state.get("ee_pose"))
    raw = _mapping(state.get("raw_sdk_state"))
    units = _mapping(pose.get("units"))
    scale = pose.get("unit_scale_applied")
    return (
        source.get("kind") == "realman_api2_sdk" and source.get("joint_unit") == "deg" and
        source.get("normalization") == "identity; no /1000 or /1e6 on SDK values" and
        units == {"xyz": "m", "rpy": "rad"} and _num(scale) and scale == 1 and
        _vec(state.get("joint_deg"), 6) and _vec(pose.get("xyz_m"), 3) and
        _vec(pose.get("rpy_rad"), 3) and _vec(raw.get("joint"), 6) and _vec(raw.get("pose"), 6) and
        raw.get("joint") == state.get("joint_deg") and
        raw.get("pose") == pose.get("xyz_m") + pose.get("rpy_rad")
    )

def _frame_valid(state, kind, expected_id, expected_name):
    frame = _mapping(state.get(kind + "_frame"))
    pose = _mapping(frame.get("pose"))
    raw = _mapping(state.get("raw_" + kind + "_frame"))
    raw_pose = raw.get("pose")
    relative_to = "controller_base" if kind == "work" else "controller_flange"
    return (
        frame.get("id") == expected_id and frame.get("name") == expected_name and
        frame.get("read_status") == "VERIFIED" and frame.get("definition_status") == "DOCUMENTED" and
        frame.get("relative_to") == relative_to and raw.get("name") == expected_name and
        _vec(raw_pose, 6) and all(value == 0 for value in raw_pose) and
        _vec(pose.get("xyz_m"), 3) and _vec(pose.get("rpy_rad"), 3) and
        all(value == 0 for value in pose["xyz_m"] + pose["rpy_rad"]) and
        pose.get("units") == {"xyz": "m", "rpy": "rad"} and
        _num(pose.get("unit_scale_applied")) and pose["unit_scale_applied"] == 1 and
        isinstance(frame.get("definition_fingerprint"), str) and len(frame["definition_fingerprint"]) == 64 and
        frame["definition_fingerprint"] == _fingerprint(raw)
    )

def _frame_signature(state):
    return tuple(_mapping(state.get(kind + "_frame")).get(key)
                 for kind in ("work", "tool") for key in ("id", "definition_fingerprint"))

def _left(snapshot):
    return _mapping(_mapping(snapshot.get("arms")).get("left"))

def _connection_ok(state, controller):
    connection = _mapping(state.get("connection"))
    return (
        connection.get("arm") == "left" and connection.get("ip") == "192.168.1.19" and
        type(connection.get("port")) is int and connection["port"] == 8080 and
        connection.get("connection_verified") is True and
        type(connection.get("sdk_handle_id")) is int and connection["sdk_handle_id"] > 0 and
        connection["sdk_handle_id"] == controller.get("sdk_handle_id")
    )

def _readbacks_ok(snapshot):
    readbacks = _mapping(snapshot.get("readbacks"))
    if not set(REQUIRED_READBACKS).issubset(readbacks):
        return False
    # Also inspect any additional readback: failed extra diagnostics cannot be hidden.
    return all(isinstance(item, dict) and _zero_return(item.get("return_code")) and
               "value" in item and item["value"] is not None for item in readbacks.values())

def _pose_match(actual, expected, xyz_tol, rpy_tol):
    return (
        _vec(actual.get("xyz_m"), 3) and _vec(actual.get("rpy_rad"), 3) and
        _vec(expected.get("xyz_m"), 3) and _vec(expected.get("rpy_rad"), 3) and
        all(abs(a - b) <= xyz_tol for a, b in zip(actual["xyz_m"], expected["xyz_m"])) and
        all(abs(a - b) <= rpy_tol for a, b in zip(actual["rpy_rad"], expected["rpy_rad"]))
    )

def _path_samples_ok(path, state):
    start = path.get("start_joint_deg")
    samples = path.get("sampled_joint_deg")
    limits = path.get("joint_limits_deg")
    current = state.get("joint_deg")
    if not (_vec(start, 6) and _vec(current, 6) and
            isinstance(samples, list) and len(samples) >= 2 and
            all(_vec(sample, 6) for sample in samples) and
            isinstance(limits, list) and len(limits) == 6 and
            all(_vec(pair, 2) and pair[0] < pair[1] for pair in limits)):
        return False
    return (
        all(abs(a - b) <= 1e-8 for a, b in zip(samples[0], start)) and
        all(abs(a - b) <= MAX_PRECHECK_JOINT_DRIFT_DEG for a, b in zip(start, current)) and
        all(lo <= value <= hi and abs(value - initial) <= MAX_PATH_JOINT_DELTA_DEG
            for sample in samples for value, initial, (lo, hi) in zip(sample, start, limits)) and
        all(abs(a-b) <= MAX_SAMPLE_JOINT_DELTA_DEG + 1e-10
            for previous, following in zip(samples, samples[1:]) for a, b in zip(previous, following))
    )

def validate_step(action, evidence, now):
    """Return every gate. Missing/malformed evidence always rejects, without I/O."""
    gates = []
    errors = []
    def gate(name, condition, detail=None):
        passed = condition is True
        gates.append({"gate": name, "status": "PASS" if passed else "REJECT", "detail": detail})
        if not passed:
            errors.append(name)
    try:
        schema_errors = validate_action(action)
    except (TypeError, KeyError, ValueError, OverflowError):
        schema_errors = ["MALFORMED_ACTION"]
    # The shared shadow schema still has its 2 mm limit. Only this exact
    # separately authorized 10 mm action overrides that single limit; all shape,
    # finite-number, frame, rotation, gripper, and done checks remain unchanged.
    if action == EXACT_ACTION and schema_errors == ["TRANSLATION_AXIS_LIMIT"]:
        schema_errors = []
    gate("action_schema", not schema_errors, schema_errors)
    gate("exact_authorized_action", not schema_errors and action == EXACT_ACTION)
    evidence = _mapping(evidence)
    gate("trusted_evidence_contract", evidence.get("schema_version") == SCHEMA_VERSION and
         evidence.get("source") == "trusted_supervised_runner")
    human = _mapping(evidence.get("human"))
    gate("specific_operator_evidence", all(human.get(key) == value for key, value in HUMAN_EVIDENCE.items()))
    controller = _mapping(evidence.get("controller"))
    gate("controller_identity", controller.get("ip") == "192.168.1.19" and
         controller.get("model") == "RM65-6FB" and type(controller.get("generation")) is int and
         controller["generation"] == 3 and type(controller.get("sdk_handle_id")) is int and
         controller["sdk_handle_id"] > 0)
    speed = _mapping(evidence.get("speed"))
    gate("fixed_speed", type(speed.get("percent")) is int and speed["percent"] == 1 and
         _num(speed.get("max_line_m_s")) and 0 < speed["max_line_m_s"] <= 0.25 and
         _num(speed.get("max_acc_m_s2")) and 0 < speed["max_acc_m_s2"] <= 1.60001,
         {"nominal_upper_speed_m_s": 0.0025})
    prechecks = evidence.get("prechecks")
    snapshots_valid = isinstance(prechecks, list) and len(prechecks) == 2 and all(isinstance(x, dict) for x in prechecks)
    gate("two_prechecks", snapshots_valid)
    snapshots = prechecks if snapshots_valid else [{}, {}]
    left_states = []
    for index, snapshot in enumerate(snapshots):
        prefix = "precheck_" + str(index)
        gate(prefix + "_fresh", _fresh(snapshot.get("timestamp"), now))
        gate(prefix + "_readbacks", _readbacks_ok(snapshot))
        gate(prefix + "_teach_work_mode", type(snapshot.get("teach_state")) is int and
             snapshot["teach_state"] == 0 and
             _mapping(_mapping(snapshot.get("readbacks")).get("rm_get_teach_frame")).get("value") == 0 and
             type(_mapping(_mapping(snapshot.get("readbacks")).get("rm_get_teach_frame")).get("value")) is int)
        readbacks = _mapping(snapshot.get("readbacks"))
        robot_info = _mapping(_mapping(readbacks.get("rm_get_robot_info")).get("value"))
        software_info = _mapping(_mapping(readbacks.get("rm_get_arm_software_info")).get("value"))
        expected_info = {"arm_dof": 6, "arm_model": 0, "force_type": 3, "robot_controller_version": 3}
        gate(prefix + "_raw_controller_identity",
             all(type(robot_info.get(key)) is int and robot_info[key] == value
                 for key, value in expected_info.items()) and
             software_info.get("product_version") == "RM65-6FB")
        gate(prefix + "_speed_readback", 
             _mapping(readbacks.get("rm_get_arm_max_line_speed")).get("value") == speed.get("max_line_m_s") and
             _mapping(readbacks.get("rm_get_arm_max_line_acc")).get("value") == speed.get("max_acc_m_s2") and
             _num(_mapping(readbacks.get("rm_get_arm_max_line_speed")).get("value")) and
             _num(_mapping(readbacks.get("rm_get_arm_max_line_acc")).get("value")))
        arms = _mapping(snapshot.get("arms"))
        for arm in ("left", "right"):
            state = _mapping(arms.get(arm))
            gate(prefix + "_" + arm + "_canonical", state.get("arm") == arm and
                 state.get("schema_version") == "astra.realman.canonical_state.v1")
            gate(prefix + "_" + arm + "_error_free", _healthy(state))
            gate(prefix + "_" + arm + "_sdk_units", _sdk_units(state))
            gate(prefix + "_" + arm + "_state_fresh", _fresh(state.get("timestamp"), now) and
                 _num(snapshot.get("timestamp")) and _num(state.get("timestamp")) and
                 state["timestamp"] <= snapshot["timestamp"])
        left = _left(snapshot)
        left_states.append(left)
        gate(prefix + "_connection", _connection_ok(left, controller))
        gate(prefix + "_work_definition", _frame_valid(left, "work", WORK_ID, "World"))
        gate(prefix + "_tool_definition", _frame_valid(left, "tool", TOOL_ID, "Arm_Tip"))
        gate(prefix + "_frame_snapshot", left.get("frame_snapshot_stable") is True)
    a, b = left_states
    gate("precheck_order", _num(snapshots[0].get("timestamp")) and _num(snapshots[1].get("timestamp")) and
         snapshots[0]["timestamp"] <= snapshots[1]["timestamp"])
    gate("unchanged_frame_definitions", _frame_signature(a) == _frame_signature(b) and
         all(_ref(x) for x in _frame_signature(a)))
    joints_a, joints_b = a.get("joint_deg"), b.get("joint_deg")
    gate("stationary_prechecks", _vec(joints_a, 6) and _vec(joints_b, 6) and
         max(abs(x-y) for x, y in zip(joints_a, joints_b)) <= MAX_PRECHECK_JOINT_DRIFT_DEG)
    path = _mapping(evidence.get("path"))
    gate("path_evidence_source", path.get("source") == "offline_kinematic_verifier" and
         _ref(path.get("evidence_file")) and path.get("binding_kind") == BINDING_KIND and
         _ref(path.get("binding_evidence")))
    gate("kinematics_evidence", path.get("kinematics_passed") is True and
         _ref(path.get("kinematics_evidence")))
    gate("sampled_joint_path", _path_samples_ok(path, b))
    start_pose = _mapping(path.get("start_pose"))
    target_pose = _mapping(path.get("target_pose"))
    ee = _mapping(b.get("ee_pose"))
    gate("path_start_matches_readback", _pose_match(start_pose, ee, 0.00002, 0.0002))
    xyz = start_pose.get("xyz_m")
    expected_target = {"xyz_m": [xyz[0], xyz[1], xyz[2]+0.01] if _vec(xyz, 3) else None,
                       "rpy_rad": start_pose.get("rpy_rad")}
    gate("exact_cartesian_path", _pose_match(target_pose, expected_target, 1e-8, 1e-9))
    gate("orientation_preserved", path.get("orientation_preserved") is True and
         _ref(path.get("orientation_evidence")))
    gate("native_self_collision_checks_passed", path.get("native_self_collision_checks_passed") is True and
         _ref(path.get("self_collision_evidence")))
    outcome = "PASS_EXECUTABLE" if not errors else "REJECT"
    return {"outcome": outcome, "decision": outcome, "errors": errors, "gates": gates,
            "scope": "one_left_World_positive_Z_10mm_step", "motion_command_attempts": 0,
            "execution_permitted": not errors,
            "note": "Pure validation. A fresh recheck and caller-owned persistent one-shot claim are still required."}

def _cross_refresh_checks(initial, refreshed):
    initial = _mapping(initial)
    refreshed = _mapping(refreshed)
    errors = []
    for key in ("human", "controller", "speed", "path"):
        if initial.get(key) != refreshed.get(key):
            errors.append("REFRESH_CHANGED_" + key.upper())
    old_checks = initial.get("prechecks")
    new_checks = refreshed.get("prechecks")
    if not (isinstance(old_checks, list) and old_checks and isinstance(new_checks, list) and new_checks):
        return errors + ["REFRESH_SNAPSHOTS_MISSING"]
    old, new = _left(_mapping(old_checks[-1])), _left(_mapping(new_checks[-1]))
    if _frame_signature(old) != _frame_signature(new):
        errors.append("REFRESH_CHANGED_FRAMES")
    old_j, new_j = old.get("joint_deg"), new.get("joint_deg")
    if not (_vec(old_j, 6) and _vec(new_j, 6) and
            max(abs(x-y) for x,y in zip(old_j, new_j)) <= MAX_PRECHECK_JOINT_DRIFT_DEG):
        errors.append("REFRESH_JOINT_DRIFT")
    old_t, new_t = old.get("timestamp"), new.get("timestamp")
    if not (_num(old_t) and _num(new_t) and new_t > old_t):
        errors.append("REFRESH_NOT_NEW")
    return errors

def _post_checks(state, before, now):
    state = _mapping(state)
    before = _mapping(before)
    errors = []
    def check(code, value):
        if value is not True:
            errors.append(code)
    check("POST_STATE_IDENTITY", state.get("arm") == "left" and
          state.get("schema_version") == "astra.realman.canonical_state.v1")
    check("POST_ERROR", _healthy(state))
    check("POST_UNITS", _sdk_units(state))
    check("POST_FRESH", _fresh(state.get("timestamp"), now) and
          _num(before.get("timestamp")) and _num(state.get("timestamp")) and
          state["timestamp"] > before["timestamp"])
    check("POST_FRAMES", state.get("frame_snapshot_stable") is True and
          _frame_signature(state) == _frame_signature(before) and
          _frame_valid(state, "work", WORK_ID, "World") and
          _frame_valid(state, "tool", TOOL_ID, "Arm_Tip"))
    check("POST_CONNECTION", state.get("connection") == before.get("connection"))
    before_pose = _mapping(before.get("ee_pose"))
    xyz = before_pose.get("xyz_m")
    expected = {"xyz_m": [xyz[0], xyz[1], xyz[2]+0.01] if _vec(xyz, 3) else None,
                "rpy_rad": before_pose.get("rpy_rad")}
    check("POST_TARGET_NOT_VERIFIED", _pose_match(_mapping(state.get("ee_pose")), expected,
          POSITION_TOLERANCE_M, ORIENTATION_TOLERANCE_RAD))
    return errors

class OneShotExecutor:
    """Calls only an injected port; consumes itself even after a rejected attempt.

    Port contract: refresh() -> new full trusted evidence; position_step(**fixed
    kwargs) -> integer SDK return; observe_result() -> fresh canonical left state.
    Port construction and persistent one-shot reservation are caller obligations.
    No automatic stop, correction, retry, cleanup motion, or second step exists.
    """
    def __init__(self, port, clock=time.time):
        self.port = port
        self.clock = clock
        self.consumed = False
        self.motion_command_attempts = 0

    def execute(self, action, evidence):
        base = {"execution_permitted": False, "motion_command_attempts": self.motion_command_attempts,
                "retry_allowed": False}
        if self.consumed:
            return dict(base, status="REJECT", errors=["ONE_SHOT_ALREADY_CONSUMED"])
        self.consumed = True
        try:
            action = copy.deepcopy(action)
            evidence = copy.deepcopy(evidence)
            initial = validate_step(action, evidence, self.clock())
        except Exception as exc:
            return dict(base, status="REJECT", errors=["PREFLIGHT_EXCEPTION"], exception_type=type(exc).__name__)
        if initial["outcome"] != "PASS_EXECUTABLE":
            return dict(base, status="REJECT", errors=initial["errors"], safety=initial)
        try:
            refreshed = copy.deepcopy(self.port.refresh())
            safety = validate_step(action, refreshed, self.clock())
            errors = list(safety["errors"]) + _cross_refresh_checks(evidence, refreshed)
        except Exception as exc:
            return dict(base, status="REJECT", errors=["REFRESH_EXCEPTION"], exception_type=type(exc).__name__)
        if errors:
            return dict(base, status="REJECT", errors=errors, safety=safety)
        # Count the attempt before crossing the hardware boundary: a transport
        # exception can occur after the controller has accepted the command.
        self.motion_command_attempts = 1
        base["motion_command_attempts"] = 1
        try:
            result = self.port.position_step(axis=2, step_m=0.01, speed_percent=1, block=1)
        except Exception as exc:
            return dict(base, status="EXECUTION_UNCERTAIN", errors=["MOTION_CALL_EXCEPTION"],
                        exception_type=type(exc).__name__, safety=safety)
        if not _zero_return(result):
            return dict(base, status="EXECUTION_UNCERTAIN", errors=["MOTION_RETURN_NOT_ZERO"],
                        return_code=result if type(result) in (int, str, bool, type(None)) or _num(result) else repr(result),
                        safety=safety)
        try:
            post = copy.deepcopy(self.port.observe_result())
            before = _left(refreshed["prechecks"][-1])
            post_errors = _post_checks(post, before, self.clock())
        except Exception as exc:
            return dict(base, status="EXECUTION_UNCERTAIN", errors=["POST_READ_EXCEPTION"],
                        return_code=result, exception_type=type(exc).__name__, safety=safety)
        if post_errors:
            return dict(base, status="EXECUTION_UNCERTAIN", errors=post_errors,
                        return_code=result, post_state=post, safety=safety)
        return dict(base, status="EXECUTED_VERIFIED", errors=[], return_code=result,
                    post_state=post, safety=safety)
