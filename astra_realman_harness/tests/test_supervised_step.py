"""Offline adversarial tests. FakePort has no SDK, socket, or hardware access."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from supervised_step import (
    BINDING_KIND, EXACT_ACTION, HUMAN_EVIDENCE, MAX_PATH_JOINT_DELTA_DEG,
    OneShotExecutor, SCHEMA_VERSION, TOOL_ID, WORK_ID, validate_step,
)

NOW = 1000.0

def canonical(arm, timestamp=NOW-0.3):
    raw_error = {"err_len": 1, "err": [0]}
    raw = {"joint": [-10.0, 28.0, 47.0, -2.0, 92.0, -14.0],
           "pose": [-0.356, 0.073, 0.343, -3.043, 0.214, 0.076],
           "err": raw_error}
    state = {
        "schema_version": "astra.realman.canonical_state.v1", "arm": arm,
        "joint_deg": list(raw["joint"]), "raw_sdk_state": copy.deepcopy(raw),
        "system_error": {"codes": [0], "has_error": False, "raw": copy.deepcopy(raw_error)},
        "timestamp": timestamp, "frame_snapshot_stable": True,
        "source": {"kind": "realman_api2_sdk", "joint_unit": "deg",
                   "normalization": "identity; no /1000 or /1e6 on SDK values"},
        "connection": {"arm": arm, "ip": "192.168.1.19" if arm == "left" else "192.168.1.18",
                       "port": 8080, "sdk_handle_id": 1 if arm == "left" else 2,
                       "connection_verified": True},
        "ee_pose": {"xyz_m": raw["pose"][:3], "rpy_rad": raw["pose"][3:],
                    "units": {"xyz": "m", "rpy": "rad"}, "unit_scale_applied": 1,
                    "frame_semantics_status": "UNKNOWN"}
    }
    for kind, name in (("work", "World"), ("tool", "Arm_Tip")):
        raw_frame = {"name": name, "pose": [0.0]*6}
        state["raw_" + kind + "_frame"] = raw_frame
        state[kind + "_frame"] = {
            "id": "realman:" + arm + ":" + kind + ":" + name, "name": name,
            "read_status": "VERIFIED", "definition_status": "DOCUMENTED",
            "relative_to": "controller_base" if kind == "work" else "controller_flange",
            "definition_fingerprint": hashlib.sha256(json.dumps(raw_frame, sort_keys=True, allow_nan=False).encode()).hexdigest(),
            "pose": {"xyz_m": [0.0]*3, "rpy_rad": [0.0]*3,
                     "units": {"xyz": "m", "rpy": "rad"}, "unit_scale_applied": 1}}
    return state

def snapshot(stamp):
    return {
        "timestamp": stamp, "teach_state": 0,
        "arms": {"left": canonical("left", stamp-0.01), "right": canonical("right", stamp-0.01)},
        "readbacks": {
            "rm_get_robot_info": {"return_code": 0, "value": {"arm_dof": 6, "arm_model": 0, "force_type": 3, "robot_controller_version": 3}},
            "rm_get_arm_software_info": {"return_code": 0, "value": {"product_version": "RM65-6FB"}},
            "rm_get_teach_frame": {"return_code": 0, "value": 0},
            "rm_get_arm_max_line_speed": {"return_code": 0, "value": 0.25},
            "rm_get_arm_max_line_acc": {"return_code": 0, "value": 1.6},
        }
    }

def evidence():
    one, two = snapshot(NOW-0.5), snapshot(NOW-0.3)
    state = two["arms"]["left"]
    start = copy.deepcopy(state["ee_pose"])
    target = copy.deepcopy(start)
    target["xyz_m"][2] += 0.01
    joints = state["joint_deg"]
    endpoint = [x + .05 for x in joints]
    return {
        "schema_version": SCHEMA_VERSION, "source": "trusted_supervised_runner",
        "human": dict(HUMAN_EVIDENCE),
        "controller": {"ip": "192.168.1.19", "model": "RM65-6FB", "generation": 3, "sdk_handle_id": 1},
        "speed": {"percent": 1, "max_line_m_s": 0.25, "max_acc_m_s2": 1.6},
        "prechecks": [one, two],
        "path": {
            "source": "offline_kinematic_verifier", "evidence_file": "/fixture/offline_path.json",
            "start_joint_deg": list(joints), "sampled_joint_deg": [list(joints), endpoint],
            "joint_limits_deg": [[-170, 170]]*6,
            "start_pose": start, "target_pose": target,
            "kinematics_passed": True, "kinematics_evidence": "fixture IK/FK residual report",
            "native_self_collision_checks_passed": True, "self_collision_evidence": "fixture link distance report",
            "orientation_preserved": True, "orientation_evidence": "fixture zero orientation residual",
            "binding_kind": BINDING_KIND, "binding_evidence": "fixture reviewed relative step contract",
        }
    }

def shifted_joints(state, offset):
    state["joint_deg"] = [x + offset for x in state["joint_deg"]]
    state["raw_sdk_state"]["joint"] = list(state["joint_deg"])

def fresh_evidence(original):
    result = copy.deepcopy(original)
    result["prechecks"] = [snapshot(NOW-0.2), snapshot(NOW-0.1)]
    return result

def successful_post(refreshed):
    result = copy.deepcopy(refreshed["prechecks"][-1]["arms"]["left"])
    result["timestamp"] = NOW-0.01
    result["ee_pose"]["xyz_m"][2] += 0.01
    result["raw_sdk_state"]["pose"] = result["ee_pose"]["xyz_m"] + result["ee_pose"]["rpy_rad"]
    return result

class FakePort:
    def __init__(self, initial):
        self.calls = []
        self.refreshed = fresh_evidence(initial)
        self.post = successful_post(self.refreshed)
        self.return_code = 0
        self.raise_refresh = False
        self.raise_motion = False
        self.raise_post = False

    def refresh(self):
        self.calls.append(("refresh", None))
        if self.raise_refresh:
            raise TimeoutError("read timeout")
        return self.refreshed

    def position_step(self, **kwargs):
        self.calls.append(("position_step", kwargs))
        if self.raise_motion:
            raise TimeoutError("possibly accepted before disconnect")
        return self.return_code

    def observe_result(self):
        self.calls.append(("observe_result", None))
        if self.raise_post:
            raise TimeoutError("post read timeout")
        return self.post

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.action = copy.deepcopy(EXACT_ACTION)
        self.evidence = evidence()

    def assert_reject(self, evidence_value=None, action_value=None, gate=None):
        result = validate_step(self.action if action_value is None else action_value,
                               self.evidence if evidence_value is None else evidence_value, NOW)
        self.assertEqual(result["outcome"], "REJECT")
        self.assertFalse(result["execution_permitted"])
        self.assertEqual(result["motion_command_attempts"], 0)
        if gate:
            self.assertIn(gate, result["errors"])
        return result

    def test_valid_specific_step(self):
        result = validate_step(self.action, self.evidence, NOW)
        self.assertEqual(result["outcome"], "PASS_EXECUTABLE")
        self.assertTrue(all(x["status"] == "PASS" for x in result["gates"]))
        self.assertEqual(result["motion_command_attempts"], 0)

    def test_noop_is_outside_this_one_step_authorization(self):
        self.action["translation_m"] = [0, 0, 0]
        self.assert_reject(gate="exact_authorized_action")

    def test_right_other_frame_other_direction_extra_fields_rejected(self):
        changes = [
            {"arm": "right"}, {"frame": "realman:left:work:Other"},
            {"tool_frame": "realman:left:tool:Other"}, {"translation_m": [0, 0, -.01]},
            {"translation_m": [.01, 0, 0]}, {"translation_m": [0, 0, .002]},
            {"translation_m": [0, 0, .001]}, {"translation_m": [0, 0, .010001]},
            {"rotation_rpy_rad": [0, .01, 0]}, {"gripper": "close"},
            {"done": True}, {"reason": "looks safe"},
        ]
        for change in changes:
            with self.subTest(change=change):
                action = dict(self.action, **change)
                self.assert_reject(action_value=action)

    def test_nan_inf_bool_action_fields(self):
        for invalid in (math.nan, math.inf, -math.inf, True, False):
            with self.subTest(invalid=invalid):
                action = copy.deepcopy(self.action)
                action["translation_m"][2] = invalid
                self.assert_reject(action_value=action)
        action = dict(self.action, done=0)
        self.assert_reject(action_value=action)

    def test_extreme_integer_is_rejected_without_overflow(self):
        action = copy.deepcopy(self.action)
        action["translation_m"][2] = 10**1000
        self.assert_reject(action_value=action)
        self.evidence["speed"]["max_line_m_s"] = 10**1000
        self.assert_reject(gate="fixed_speed")

    def test_malformed_evidence_fails_closed(self):
        for invalid in (None, [], "", True, {}, {"prechecks": [None, True]},
                        {"prechecks": [[], []]}, {"prechecks": [None]*10}):
            with self.subTest(invalid=invalid):
                result = validate_step(self.action, invalid, NOW)
                self.assertEqual(result["outcome"], "REJECT")

    def test_all_gates_report_even_with_early_failure(self):
        self.action["gripper"] = "open"
        self.evidence["path"]["native_self_collision_checks_passed"] = False
        result = self.assert_reject()
        self.assertIn("action_schema", result["errors"])
        self.assertIn("native_self_collision_checks_passed", result["errors"])
        self.assertGreater(len(result["gates"]), 30)

    def test_user_quotes_and_exact_segment_scope_required(self):
        for key in HUMAN_EVIDENCE:
            changed = copy.deepcopy(self.evidence)
            changed["human"][key] = "model says safe"
            self.assert_reject(evidence_value=changed, gate="specific_operator_evidence")

    def test_unknown_and_model_authored_evidence_rejected(self):
        self.evidence["source"] = "CodexBackend"
        self.assert_reject(gate="trusted_evidence_contract")
        self.evidence["source"] = "trusted_supervised_runner"
        self.evidence["path"]["source"] = "CodexBackend"
        self.assert_reject(gate="path_evidence_source")

    def test_controller_ip_model_generation_handle(self):
        for key, invalid in (("ip", "192.168.1.18"), ("model", "RM75"),
                             ("generation", 2), ("generation", True), ("sdk_handle_id", 0),
                             ("sdk_handle_id", True)):
            changed = copy.deepcopy(self.evidence)
            changed["controller"][key] = invalid
            self.assert_reject(evidence_value=changed, gate="controller_identity")

    def test_raw_controller_metadata_cannot_be_spoofed_by_normalized_constants(self):
        for key, invalid in (("arm_dof", 7), ("arm_model", 1), ("arm_model", False),
                             ("force_type", 0), ("robot_controller_version", 2)):
            changed = copy.deepcopy(self.evidence)
            changed["prechecks"][1]["readbacks"]["rm_get_robot_info"]["value"][key] = invalid
            self.assert_reject(evidence_value=changed, gate="precheck_1_raw_controller_identity")
        self.evidence["prechecks"][0]["readbacks"]["rm_get_arm_software_info"]["value"]["product_version"] = "RM75"
        self.assert_reject(gate="precheck_0_raw_controller_identity")

    def test_wrong_handle_connection_rejected(self):
        self.evidence["prechecks"][1]["arms"]["left"]["connection"]["sdk_handle_id"] = 2
        self.assert_reject(gate="precheck_1_connection")

    def test_speed_and_acc_limits(self):
        for key, invalid in (("percent", 2), ("percent", True), ("max_line_m_s", .250001),
                             ("max_line_m_s", 0), ("max_line_m_s", math.nan),
                             ("max_acc_m_s2", 1.60002), ("max_acc_m_s2", 0)):
            changed = copy.deepcopy(self.evidence)
            changed["speed"][key] = invalid
            self.assert_reject(evidence_value=changed, gate="fixed_speed")

    def test_readback_speed_must_match_trusted_limit(self):
        self.evidence["prechecks"][0]["readbacks"]["rm_get_arm_max_line_speed"]["value"] = .3
        self.assert_reject(gate="precheck_0_speed_readback")

    def test_failed_missing_bool_extra_readback(self):
        for mutation in ("failed", "missing", "bool", "extra"):
            changed = copy.deepcopy(self.evidence)
            reads = changed["prechecks"][0]["readbacks"]
            if mutation == "failed":
                reads["rm_get_robot_info"]["return_code"] = -1
            elif mutation == "missing":
                del reads["rm_get_robot_info"]
            elif mutation == "bool":
                reads["rm_get_robot_info"]["return_code"] = False
            else:
                reads["extra_read"] = {"return_code": 1, "value": 0}
            self.assert_reject(evidence_value=changed, gate="precheck_0_readbacks")

    def test_stale_future_and_unordered_snapshots(self):
        for stamp in (NOW-3.00001, NOW+0.00001, math.nan, True):
            changed = copy.deepcopy(self.evidence)
            changed["prechecks"][0]["timestamp"] = stamp
            self.assert_reject(evidence_value=changed, gate="precheck_0_fresh")
        self.evidence["prechecks"].reverse()
        self.assert_reject(gate="precheck_order")

    def test_stale_either_arm_canonical(self):
        for arm in ("left", "right"):
            changed = copy.deepcopy(self.evidence)
            changed["prechecks"][1]["arms"][arm]["timestamp"] = NOW-4
            self.assert_reject(evidence_value=changed, gate="precheck_1_" + arm + "_state_fresh")

    def test_nonzero_error_either_arm_including_raw_hidden_error(self):
        for arm in ("left", "right"):
            for hidden in (False, True):
                changed = copy.deepcopy(self.evidence)
                state = changed["prechecks"][0]["arms"][arm]
                state["raw_sdk_state"]["err"] = {"err_len": 1, "err": [4105]}
                if not hidden:
                    state["system_error"] = {"codes": [4105], "has_error": True,
                                             "raw": {"err_len": 1, "err": [4105]}}
                self.assert_reject(evidence_value=changed, gate="precheck_0_" + arm + "_error_free")

    def test_missing_or_bool_error_rejected(self):
        for error in ({}, {"codes": [False], "has_error": False, "raw": {"err_len": 1, "err": [False]}}):
            self.evidence["prechecks"][0]["arms"]["right"]["system_error"] = error
            self.assert_reject(gate="precheck_0_right_error_free")

    def test_units_scaling_wrong_raw_or_nan_either_arm(self):
        for arm in ("left", "right"):
            for mutation in ("scale", "units", "raw", "nan", "bool"):
                changed = copy.deepcopy(self.evidence)
                state = changed["prechecks"][1]["arms"][arm]
                if mutation == "scale":
                    state["ee_pose"]["unit_scale_applied"] = .01
                elif mutation == "units":
                    state["source"]["joint_unit"] = "rad"
                elif mutation == "raw":
                    state["raw_sdk_state"]["pose"][0] *= 1e6
                elif mutation == "nan":
                    state["joint_deg"][0] = math.nan
                else:
                    state["joint_deg"][0] = True
                self.assert_reject(evidence_value=changed, gate="precheck_1_" + arm + "_sdk_units")

    def test_teach_frame_wrong_or_bool_rejected(self):
        for value in (1, False, "0", None):
            changed = copy.deepcopy(self.evidence)
            changed["prechecks"][0]["teach_state"] = value
            changed["prechecks"][0]["readbacks"]["rm_get_teach_frame"]["value"] = value
            self.assert_reject(evidence_value=changed, gate="precheck_0_teach_work_mode")

    def test_changed_nonzero_or_fake_frame_definition(self):
        for kind in ("work", "tool"):
            for mutation in ("offset", "fingerprint", "name", "unstable"):
                changed = copy.deepcopy(self.evidence)
                state = changed["prechecks"][1]["arms"]["left"]
                if mutation == "offset":
                    state["raw_" + kind + "_frame"]["pose"][0] = .01
                elif mutation == "fingerprint":
                    state[kind + "_frame"]["definition_fingerprint"] = "a"*64
                elif mutation == "name":
                    state[kind + "_frame"]["id"] += "_other"
                else:
                    state["frame_snapshot_stable"] = False
                self.assert_reject(evidence_value=changed)

    def test_precheck_joint_drift(self):
        shifted_joints(self.evidence["prechecks"][1]["arms"]["left"], .0201)
        self.assert_reject(gate="stationary_prechecks")

    def test_joint_path_bound_five_degrees_and_limits(self):
        self.assertEqual(MAX_PATH_JOINT_DELTA_DEG, 5)
        path = self.evidence["path"]
        path["sampled_joint_deg"] = [
            [x+i*.05 for x in path["start_joint_deg"]] for i in range(101)]
        self.assertEqual(validate_step(self.action, self.evidence, NOW)["outcome"], "PASS_EXECUTABLE")
        path["sampled_joint_deg"][-1][0] += .00001
        self.assert_reject(gate="sampled_joint_path")
        path["sampled_joint_deg"] = [list(path["start_joint_deg"])]*2
        path["joint_limits_deg"][0] = [-9.9, 9.9]
        self.assert_reject(gate="sampled_joint_path")

    def test_adjacent_sample_jump_over_point_zero_five_rejected(self):
        self.evidence["path"]["sampled_joint_deg"][1][0] += .00001
        self.assert_reject(gate="sampled_joint_path")

    def test_shadow_schema_two_mm_limit_unchanged(self):
        from decision_protocol import validate_action
        self.assertEqual(validate_action(self.action), ["TRANSLATION_AXIS_LIMIT"])
        self.assertEqual(validate_step(self.action, self.evidence, NOW)["outcome"], "PASS_EXECUTABLE")
        action = dict(self.action, translation_m=[0,0,.010001])
        self.assert_reject(action_value=action)


    def test_missing_malformed_or_nan_joint_samples(self):
        for invalid in ([], [[0]*6], [[0]*6, [math.nan]*6], [[0]*6, [True]*6]):
            changed = copy.deepcopy(self.evidence)
            changed["path"]["sampled_joint_deg"] = invalid
            self.assert_reject(evidence_value=changed, gate="sampled_joint_path")

    def test_pose_target_not_exact_z_step(self):
        for field, index, change in (("xyz_m", 0, .01), ("xyz_m", 2, .01),
                                     ("rpy_rad", 1, .01)):
            changed = copy.deepcopy(self.evidence)
            changed["path"]["target_pose"][field][index] += change
            self.assert_reject(evidence_value=changed, gate="exact_cartesian_path")

    def test_path_start_must_match_live_pose(self):
        self.evidence["path"]["start_pose"]["xyz_m"][0] += .01
        self.assert_reject(gate="path_start_matches_readback")

    def test_missing_math_or_collision_evidence_cannot_be_boolean_only(self):
        for field in ("kinematics_evidence", "binding_evidence", "orientation_evidence", "self_collision_evidence"):
            changed = copy.deepcopy(self.evidence)
            changed["path"][field] = ""
            self.assert_reject(evidence_value=changed)
        for field in ("kinematics_passed", "orientation_preserved", "native_self_collision_checks_passed"):
            changed = copy.deepcopy(self.evidence)
            changed["path"][field] = 1
            self.assert_reject(evidence_value=changed)

class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.evidence = evidence()
        self.action = copy.deepcopy(EXACT_ACTION)
        self.port = FakePort(self.evidence)
        self.executor = OneShotExecutor(self.port, clock=lambda: NOW)

    def run_once(self):
        return self.executor.execute(self.action, self.evidence)

    def test_success_calls_exact_one_step_and_readonly_refresh_post(self):
        result = self.run_once()
        self.assertEqual(result["status"], "EXECUTED_VERIFIED")
        self.assertEqual(result["motion_command_attempts"], 1)
        self.assertEqual(self.port.calls, [
            ("refresh", None),
            ("position_step", {"axis": 2, "step_m": .01, "speed_percent": 1, "block": 1}),
            ("observe_result", None)])
        self.assertFalse(result["retry_allowed"])
        self.assertFalse(result["execution_permitted"])

    def test_initial_rejection_has_no_port_calls_and_consumes_instance(self):
        self.action["gripper"] = "close"
        first = self.run_once()
        self.assertEqual(first["status"], "REJECT")
        self.assertEqual(first["motion_command_attempts"], 0)
        self.assertEqual(self.port.calls, [])
        self.action = copy.deepcopy(EXACT_ACTION)
        second = self.run_once()
        self.assertIn("ONE_SHOT_ALREADY_CONSUMED", second["errors"])
        self.assertEqual(self.port.calls, [])

    def test_success_cannot_replay(self):
        self.run_once()
        before = list(self.port.calls)
        result = self.run_once()
        self.assertEqual(result["status"], "REJECT")
        self.assertEqual(result["motion_command_attempts"], 1)
        self.assertEqual(self.port.calls, before)

    def test_motion_nonzero_bool_none_return_ambiguous_not_retryable(self):
        for invalid in (-1, 1, False, None, "0", math.nan, math.inf):
            with self.subTest(invalid=invalid):
                port = FakePort(self.evidence)
                port.return_code = invalid
                executor = OneShotExecutor(port, clock=lambda: NOW)
                result = executor.execute(self.action, self.evidence)
                self.assertEqual(result["status"], "EXECUTION_UNCERTAIN")
                self.assertEqual(result["motion_command_attempts"], 1)
                json.dumps(result, allow_nan=False)
                self.assertEqual([x[0] for x in port.calls], ["refresh", "position_step"])
                executor.execute(self.action, self.evidence)
                self.assertEqual(len(port.calls), 2)

    def test_motion_exception_might_have_moved_never_claims_zero(self):
        self.port.raise_motion = True
        result = self.run_once()
        self.assertEqual(result["status"], "EXECUTION_UNCERTAIN")
        self.assertEqual(result["motion_command_attempts"], 1)
        self.assertNotIn("motion_commands_sent", result)
        self.assertEqual([x[0] for x in self.port.calls], ["refresh", "position_step"])
        self.run_once()
        self.assertEqual(len(self.port.calls), 2)

    def test_postread_exception_uncertain_no_correction(self):
        self.port.raise_post = True
        result = self.run_once()
        self.assertEqual(result["status"], "EXECUTION_UNCERTAIN")
        self.assertEqual(result["motion_command_attempts"], 1)
        self.assertEqual(len(self.port.calls), 3)

    def test_postread_unverified_motion_or_error_or_wrong_orientation(self):
        for mutation in ("no_move", "too_far", "lateral", "orientation", "error", "stale", "frame"):
            with self.subTest(mutation=mutation):
                port = FakePort(self.evidence)
                state = port.post
                if mutation == "no_move":
                    state["ee_pose"]["xyz_m"][2] -= .01
                elif mutation == "too_far":
                    state["ee_pose"]["xyz_m"][2] += .01
                elif mutation == "lateral":
                    state["ee_pose"]["xyz_m"][0] += .01
                elif mutation == "orientation":
                    state["ee_pose"]["rpy_rad"][0] += .01
                elif mutation == "error":
                    state["system_error"]["codes"] = [4105]
                elif mutation == "stale":
                    state["timestamp"] = NOW-4
                else:
                    state["work_frame"]["definition_fingerprint"] = "a"*64
                state["raw_sdk_state"]["pose"] = state["ee_pose"]["xyz_m"] + state["ee_pose"]["rpy_rad"]
                executor = OneShotExecutor(port, clock=lambda: NOW)
                result = executor.execute(self.action, self.evidence)
                self.assertEqual(result["status"], "EXECUTION_UNCERTAIN")
                self.assertEqual(result["motion_command_attempts"], 1)
                self.assertEqual(len(port.calls), 3)

    def test_refresh_exception_no_motion(self):
        self.port.raise_refresh = True
        result = self.run_once()
        self.assertEqual(result["status"], "REJECT")
        self.assertEqual(result["motion_command_attempts"], 0)
        self.assertEqual(self.port.calls, [("refresh", None)])

    def test_refresh_old_data_no_motion(self):
        self.port.refreshed = copy.deepcopy(self.evidence)
        result = self.run_once()
        self.assertIn("REFRESH_NOT_NEW", result["errors"])
        self.assertEqual(self.port.calls, [("refresh", None)])

    def test_refresh_new_joint_drift_and_frame_change_reject(self):
        shifted_joints(self.port.refreshed["prechecks"][-1]["arms"]["left"], .0201)
        result = self.run_once()
        self.assertIn("REFRESH_JOINT_DRIFT", result["errors"])
        self.assertEqual(result["motion_command_attempts"], 0)

    def test_refresh_cannot_alter_trusted_path_or_authorization(self):
        for key in ("human", "controller", "speed", "path"):
            port = FakePort(self.evidence)
            port.refreshed[key]["unexpected"] = "new"
            executor = OneShotExecutor(port, clock=lambda: NOW)
            result = executor.execute(self.action, self.evidence)
            self.assertIn("REFRESH_CHANGED_" + key.upper(), result["errors"])
            self.assertEqual(port.calls, [("refresh", None)])

    def test_refresh_current_fault_teach_and_stale_reject(self):
        for mutation in ("fault", "teach", "stale"):
            port = FakePort(self.evidence)
            snapshot = port.refreshed["prechecks"][-1]
            if mutation == "fault":
                snapshot["arms"]["right"]["system_error"]["codes"] = [4105]
            elif mutation == "teach":
                snapshot["teach_state"] = 1
            else:
                snapshot["timestamp"] = NOW-5
            executor = OneShotExecutor(port, clock=lambda: NOW)
            result = executor.execute(self.action, self.evidence)
            self.assertEqual(result["status"], "REJECT")
            self.assertEqual(port.calls, [("refresh", None)])

    def test_callers_input_not_mutated(self):
        before_action, before_evidence = copy.deepcopy(self.action), copy.deepcopy(self.evidence)
        self.run_once()
        self.assertEqual(self.action, before_action)
        self.assertEqual(self.evidence, before_evidence)

if __name__ == "__main__":
    unittest.main()
