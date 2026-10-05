"""Offline adversarial tests. No SDK, camera, network, SSH or real Codex invocation."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, read_json
from decision_protocol import parse_action, validate_action
from decision_frame_adapter import adapt_observation, TRANSFORM_CONTRACT
from decision_safety import assess_decision
from decision_executor import DryRunExecutor
from decision_backends import (AstraBackend, CodexBackend, BackendFailure,
                               build_context, codex_command, check_events, redact)
from observation import png_rgb

def action():
    return {"action_type": "cartesian_delta", "arm": "left",
            "frame": "realman:left:work:World", "tool_frame": "realman:left:tool:Arm_Tip",
            "translation_m": [0, 0, .002], "rotation_rpy_rad": [0, 0, 0],
            "gripper": "hold", "done": False}

def noop():
    result = action()
    result["translation_m"] = [0, 0, 0]
    return result

def synthetic_frame(arm, kind, name):
    return {"name": name, "id": "realman:%s:%s:%s" % (arm, kind, name),
            "pose": {"xyz_m": [0, 0, 0], "rpy_rad": [0, 0, 0],
                     "units": {"xyz": "m", "rpy": "rad"}},
            "read_status": "VERIFIED", "definition_status": "DOCUMENTED",
            "definition_fingerprint": hashlib.sha256(
                ("OFFLINE_SYNTHETIC:%s:%s:%s" % (arm, kind, name)).encode()).hexdigest()}

def synthetic_observation(now=None):
    now = time.time() if now is None else now
    states = {}
    for index, arm in enumerate(("left", "right")):
        work = synthetic_frame(arm, "work", "World")
        tool = synthetic_frame(arm, "tool", "Arm_Tip")
        states[arm] = {
            "arm": arm, "joint_deg": [1, 2, 3, 4, 5, 6],
            "ee_pose": {"xyz_m": [.3, 0, .3], "rpy_rad": [0, 0, 0],
                        "units": {"xyz": "m", "rpy": "rad"}, "unit_scale_applied": 1,
                        "reference_frame_id": work["id"], "target_frame_id": tool["id"],
                        "frame_semantics_status": "CONFIRMED",
                        "binding_evidence": "OFFLINE_SYNTHETIC_ONLY"},
            "work_frame": work, "tool_frame": tool,
            "connection": {"arm": arm, "ip": "192.0.2.%d" % (10 + index),
                           "port": 8080, "sdk_handle_id": index + 1,
                           "connection_verified": True},
            "timestamp": now, "system_error": {"codes": [0], "has_error": False},
            "frame_snapshot_stable": True, "source": {"joint_unit": "deg"}}
    return {"schema_version": "astra.decision.observation.v1", "observation_id": "UNIT_SYNTHETIC",
            "captured_at": now, "task": "SYNTHETIC OFFLINE TEST",
            "canonical_states": states, "allowed_proposal_arms": ["left"],
            "source": {"kind": "offline_fixture", "physical": False}, "frames": {},
            "cameras": [{"serial": str(i), "captured_at": now} for i in range(4)],
            "camera_capture": {"expected_serials": [str(i) for i in range(4)],
                               "timestamp_semantics_confirmed": True},
            "capture_span_ms": 0, "capture_failures": [], "previous": None}

def verified_fixture():
    return {"status": "VERIFIED", "evidence": "OFFLINE_SYNTHETIC_ONLY"}

def test_policy():
    # Only this in-memory fixture is modified; real lab confirmation remains untouched.
    p = copy.deepcopy(read_json(ROOT / "config/shadow_phase1.json"))
    p["fixture_only"] = True
    states = synthetic_observation(1000)["canonical_states"]
    for arm, state in states.items():
        p["arm_identities"][arm] = {
            "host": state["connection"]["ip"], "port": 8080,
            "software_endpoint_mapping": verified_fixture(),
            "physical_side_identity": verified_fixture()}
        p["local_workspaces"][arm] = dict(
            verified_fixture(), frame_id=state["work_frame"]["id"],
            tool_frame_id=state["tool_frame"]["id"],
            frame_fingerprint=state["work_frame"]["definition_fingerprint"],
            tool_fingerprint=state["tool_frame"]["definition_fingerprint"],
            bounds_m={"min": [.29, -.01, .29], "max": [.31, .01, .31]},
            human_confirmed=True, swept_tool_clearance_verified=True,
            scope="local_free_space_translation_only")
    p["full_gripper_geometry"] = {"status": "UNCONFIRMED", "evidence": None}
    p["camera_extrinsics"] = {"status": "UNCONFIRMED", "evidence": None}
    return p

def execution_ready_fixture():
    return {key: verified_fixture() for key in
            ("trajectory_validation", "operator_authorization", "hardware_executor")}

class DecisionSchemaTests(unittest.TestCase):
    def test_exact_contract_and_boundary(self):
        self.assertEqual(parse_action(json.dumps(action())), action())
        a = action(); a["translation_m"] = [-.002, .002, .002]
        self.assertEqual(validate_action(a), [])
    def test_bound_not_clamped(self):
        for delta in (.002000000001, -.002000000001):
            a = action(); a["translation_m"][2] = delta
            self.assertIn("TRANSLATION_AXIS_LIMIT", validate_action(a))
    def test_rotation_is_disabled(self):
        a = action(); a["rotation_rpy_rad"][0] = .000001
        self.assertIn("ROTATION_DISABLED", validate_action(a))
    def test_gripper_open_and_close_rejected(self):
        for val in ("open", "close"):
            a = action(); a["gripper"] = val
            self.assertIn("GRIPPER_DISABLED", validate_action(a))
    def test_missing_extra_duplicate_and_nl_rejected(self):
        for raw in ('Move left by two mm', '```json\n' + json.dumps(action()) + '\n```',
                    '{"arm":"left","arm":"right"}', json.dumps(dict(action(), command="movej"))):
            with self.assertRaises(ValueError): parse_action(raw)
        a = action(); del a["tool_frame"]
        with self.assertRaises(ValueError): parse_action(json.dumps(a))
    def test_booleans_nan_and_infinity_rejected(self):
        for value in (True, float("nan"), float("inf")):
            a = action(); a["translation_m"][0] = value
            with self.assertRaises(ValueError): parse_action(json.dumps(a))
    def test_explicit_work_and_tool_frames_required(self):
        for key, bad in (("frame", ""), ("frame", "world"), ("frame", "left_base"),
                         ("frame", "realman:left:tool:Arm_Tip"),
                         ("tool_frame", ""), ("tool_frame", "realman:left:work:World")):
            a = action(); a[key] = bad
            self.assertTrue(validate_action(a))
    def test_schema_document_matches_public_contract(self):
        s = read_json(ROOT / "schema/decision_action.schema.json")
        self.assertEqual(set(s["required"]), set(action()))
        self.assertFalse(s["additionalProperties"])

class DecisionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.obs = synthetic_observation(self.now)
        self.policy = test_policy()
        self.readiness = execution_ready_fixture()
    def assess(self, a=None, now=None, generated_at=None):
        return assess_decision(action() if a is None else a, self.obs, self.policy,
                               self.now if now is None else now,
                               generated_at=self.now if generated_at is None else generated_at,
                               execution_readiness=self.readiness)
    def gate(self, result, name):
        return next(g for g in result["gates"] if g["gate"] == name)
    def assert_rejected(self, result, code=None):
        self.assertEqual(result["outcome"], "REJECT", result)
        self.assertFalse(result["execution_permitted"])
        if code is not None: self.assertIn(code, result["errors"])
    def test_synthetic_all_runtime_conditions_pass_executable_but_no_actuation(self):
        result = self.assess()
        self.assertEqual(result["outcome"], "PASS_EXECUTABLE", result)
        self.assertTrue(result["non_zero"])
        self.assertFalse(result["execution_permitted"])
        self.assertFalse(any(g["blocking"] for g in result["gates"]))
        self.assertEqual(result["transform_preview"]["target_xyz_m"], [.3, 0, .302])
        sent = DryRunExecutor().submit(action(), result)
        self.assertEqual(sent["hardware_commands_sent"], 0)
        self.assertEqual(sent["motion_commands_sent"], 0)
    def test_readiness_cannot_be_granted_from_policy(self):
        self.policy["execution_readiness"] = execution_ready_fixture()
        result = assess_decision(action(), self.obs, self.policy, self.now, generated_at=self.now)
        self.assert_rejected(result, "HARDWARE_EXECUTOR_NOT_VERIFIED")
        self.assertIn("OPERATOR_AUTHORIZATION_NOT_VERIFIED", result["errors"])
        self.assertIn("TRAJECTORY_VALIDATION_NOT_VERIFIED", result["errors"])
    def test_each_missing_runtime_condition_rejects_nonzero(self):
        for name, code in (("hardware_executor", "HARDWARE_EXECUTOR_NOT_VERIFIED"),
                           ("operator_authorization", "OPERATOR_AUTHORIZATION_NOT_VERIFIED"),
                           ("trajectory_validation", "TRAJECTORY_VALIDATION_NOT_VERIFIED")):
            with self.subTest(name=name):
                self.readiness = execution_ready_fixture(); self.readiness[name] = {"status": "VERIFIED"}
                self.assert_rejected(self.assess(), code)
    def test_noop_unknown_execution_conditions_and_stale_is_pass_noop(self):
        self.policy["arm_identities"]["left"]["physical_side_identity"] = {"status": "UNKNOWN"}
        self.policy["local_workspaces"]["left"] = {"status": "UNCONFIRMED"}
        target = self.obs["canonical_states"]["left"]
        target["ee_pose"].update(frame_semantics_status="UNKNOWN", reference_frame_id=None,
                                  target_frame_id=None, binding_evidence=None)
        target["frame_snapshot_stable"] = False
        target["work_frame"]["definition_status"] = "UNKNOWN"
        target["tool_frame"]["definition_status"] = "UNKNOWN"
        self.readiness = {}
        result = self.assess(noop(), now=self.now + 100)
        self.assertEqual(result["outcome"], "PASS_NOOP", result)
        self.assertTrue(result["is_noop"])
        self.assertFalse(result["non_zero"])
        self.assertIn("STALE_OBSERVATION", result["warnings"])
        self.assertEqual(self.gate(result, "ee_pose_frame_binding")["status"], "NOT_APPLICABLE")
        self.assertEqual(DryRunExecutor().submit(noop(), result)["status"], "NOOP_LOGGED")
    def test_noop_controller_error_is_rejected(self):
        self.obs["canonical_states"]["right"]["system_error"] = {"codes": [4105], "has_error": True}
        self.assert_rejected(self.assess(noop()), "ARM_right:CONTROLLER_ERROR_OR_UNKNOWN")
    def test_noop_units_are_still_required(self):
        self.obs["canonical_states"]["left"]["ee_pose"]["unit_scale_applied"] = .001
        self.assert_rejected(self.assess(noop()), "ARM_left:STATE_UNITS_UNCONFIRMED")
    def test_noop_camera_skew_is_still_rejected(self):
        self.obs["cameras"][0]["captured_at"] -= 2
        self.obs["capture_span_ms"] = 2000
        self.assert_rejected(self.assess(noop()), "CAMERA_TIMING_UNCONFIRMED_OR_SKEW")
    def test_two_mm_per_axis_inclusive_boundary(self):
        a = action(); a["translation_m"] = [-.002, .002, .002]
        self.assertEqual(self.assess(a)["outcome"], "PASS_EXECUTABLE")
        a["translation_m"][0] = -.002000001
        self.assert_rejected(self.assess(a), "TRANSLATION_AXIS_LIMIT")
    def test_actual_sdk_unknown_binding_remains_unknown(self):
        self.obs["canonical_states"]["left"]["ee_pose"].update(
            frame_semantics_status="UNKNOWN", reference_frame_id=None, target_frame_id=None)
        converted = adapt_observation(self.obs)
        self.assertEqual(converted["robot"]["arms"]["left"]["poses"], {})
        result = self.assess()
        self.assert_rejected(result, "EE_POSE_FRAME_BINDING_UNCONFIRMED")
        self.assertEqual(result["transform_preview"]["status"], "UNAVAILABLE")
    def test_binding_requires_evidence_and_both_matching_ids(self):
        for key, value in (("binding_evidence", None), ("reference_frame_id", "wrong"),
                           ("target_frame_id", "wrong")):
            with self.subTest(key=key):
                self.obs = synthetic_observation(self.now)
                self.obs["canonical_states"]["left"]["ee_pose"][key] = value
                self.assert_rejected(self.assess(), "EE_POSE_FRAME_BINDING_UNCONFIRMED")
    def test_work_or_tool_identity_mismatch_rejects_even_noop(self):
        for base in (action(), noop()):
            for key, value in (("frame", "realman:right:work:World"),
                               ("tool_frame", "realman:left:tool:Other")):
                a = dict(base); a[key] = value
                self.assert_rejected(self.assess(a), "ACTION_FRAME_OR_TOOL_MISMATCH")
    def test_right_proposal_stays_disabled(self):
        a = action(); a.update(arm="right", frame="realman:right:work:World",
                               tool_frame="realman:right:tool:Arm_Tip")
        self.assert_rejected(self.assess(a), "ARM_NOT_ALLOWED")
    def test_unknown_physical_identity_not_upgraded_from_ip(self):
        self.policy["arm_identities"]["left"]["physical_side_identity"] = {"status": "UNKNOWN"}
        result = self.assess()
        self.assertEqual(self.gate(result, "controller_connection_mapping")["status"], "PASS")
        self.assert_rejected(result, "PHYSICAL_ARM_IDENTITY_UNCONFIRMED")
    def test_connection_endpoint_and_handle_must_match(self):
        for key, value in (("ip", "192.0.2.99"), ("port", 8090),
                           ("sdk_handle_id", None), ("connection_verified", False)):
            self.obs = synthetic_observation(self.now)
            self.obs["canonical_states"]["left"]["connection"][key] = value
            self.assert_rejected(self.assess(), "CONTROLLER_CONNECTION_MAPPING_UNCONFIRMED")
    def test_missing_workspace_rejects(self):
        self.policy["local_workspaces"]["left"] = {"status": "UNCONFIRMED"}
        self.assert_rejected(self.assess(), "LOCAL_WORKSPACE_UNCONFIRMED")
    def test_workspace_confirmation_and_fingerprints_required(self):
        for key, value in (("human_confirmed", False), ("swept_tool_clearance_verified", False),
                           ("frame_id", "wrong"), ("tool_frame_id", "wrong"),
                           ("frame_fingerprint", "wrong"), ("tool_fingerprint", "wrong"),
                           ("evidence", None)):
            self.policy = test_policy()
            self.policy["local_workspaces"]["left"][key] = value
            self.assert_rejected(self.assess(), "LOCAL_WORKSPACE_UNCONFIRMED")
    def test_workspace_checks_current_and_proposed_endpoint(self):
        for z in (.309, .289):
            self.obs["canonical_states"]["left"]["ee_pose"]["xyz_m"][2] = z
            self.assert_rejected(self.assess(), "WORKSPACE_SEGMENT_NOT_VERIFIED")
    def test_active_work_and_tool_definitions_required_for_motion(self):
        for field, code in (("work_frame", "ACTIVE_WORK_DEFINITION_UNCONFIRMED"),
                            ("tool_frame", "ACTIVE_TOOL_DEFINITION_UNCONFIRMED")):
            self.obs = synthetic_observation(self.now)
            self.obs["canonical_states"]["left"][field]["read_status"] = "UNKNOWN"
            self.assert_rejected(self.assess(), code)
    def test_no_camera_transform_extrinsics_only_grounding_warning(self):
        self.assertFalse(TRANSFORM_CONTRACT["camera_to_robot_transform_used"])
        result = self.assess()
        self.assertEqual(result["outcome"], "PASS_EXECUTABLE")
        self.assertIn("CAMERA_EXTRINSICS_UNCONFIRMED_GROUNDING_WARNING", result["warnings"])
        self.assertEqual(self.gate(result, "camera_transform_dependency")["status"], "PASS")
    def test_transform_dependency_requires_verified_extrinsics(self):
        with patch.dict(TRANSFORM_CONTRACT, {"camera_to_robot_transform_used": True}):
            self.assert_rejected(self.assess(), "CAMERA_TRANSFORM_REQUIRES_VERIFIED_EXTRINSICS")
            self.assert_rejected(self.assess(noop()), "CAMERA_TRANSFORM_REQUIRES_VERIFIED_EXTRINSICS")
            self.policy["camera_extrinsics"] = verified_fixture()
            self.assertEqual(self.assess()["outcome"], "PASS_EXECUTABLE")
    def test_full_gripper_geometry_warning_only_with_local_swept_clearance(self):
        result = self.assess()
        self.assertEqual(self.gate(result, "tool_geometry_for_phase")["status"], "WARNING")
        self.policy["phase"] = "approach"
        self.assert_rejected(self.assess(), "FULL_GRIPPER_GEOMETRY_UNCONFIRMED")
    def test_stale_state_and_observation_rejected_for_nonzero(self):
        self.obs["captured_at"] -= 40
        self.obs["canonical_states"]["right"]["timestamp"] -= 40
        result = self.assess()
        self.assert_rejected(result, "STALE_OBSERVATION")
        self.assertIn("ARM_right:STATE_STALE_OR_FUTURE", result["errors"])
    def test_inference_duration_never_refreshes_observation(self):
        before = copy.deepcopy(self.obs)
        finished = self.now + 40.777528745
        result = self.assess(now=finished, generated_at=finished)
        self.assert_rejected(result, "STALE_OBSERVATION")
        self.assertIn("ARM_left:STATE_STALE_OR_FUTURE", result["errors"])
        self.assertIn("ARM_right:STATE_STALE_OR_FUTURE", result["errors"])
        self.assertEqual(self.obs, before)
    def test_missing_stale_and_future_generated_at_reject_nonzero(self):
        for stamp in (None, self.now - 31, self.now + 2):
            result = assess_decision(action(), self.obs, self.policy, self.now,
                                     generated_at=stamp, execution_readiness=self.readiness)
            self.assert_rejected(result, "STALE_OR_FUTURE_PROPOSAL")
    def test_done_never_bypasses_motion_gates(self):
        a = action(); a["done"] = True
        self.policy["local_workspaces"]["left"] = {}
        self.assert_rejected(self.assess(a), "LOCAL_WORKSPACE_UNCONFIRMED")
    def test_camera_set_failure_or_false_metrics_rejected(self):
        mutations = [
            lambda o: o["cameras"].pop(),
            lambda o: o["cameras"][0].update(serial="1"),
            lambda o: o.update(capture_failures=["camera unavailable"]),
            lambda o: o.update(capture_span_ms=10),
            lambda o: o["camera_capture"].update(timestamp_semantics_confirmed=False)]
        for change in mutations:
            self.obs = synthetic_observation(self.now); change(self.obs)
            self.assert_rejected(self.assess(noop()))
    def test_synthetic_policy_cannot_validate_physical_observation(self):
        for physical in (True, None):
            self.obs["source"] = {"physical": physical}
            self.assert_rejected(self.assess(), "SYNTHETIC_POLICY_FORBIDDEN_FOR_REAL_OBSERVATION")
            self.assert_rejected(self.assess(noop()), "SYNTHETIC_POLICY_FORBIDDEN_FOR_REAL_OBSERVATION")
    def test_bad_schema_rejected_without_natural_language_or_legacy_adaptation(self):
        for a in ("move up", {}, dict(action(), command="movej"), list(action())):
            self.assert_rejected(self.assess(a), "ACTION_SCHEMA_FIELDS")
    def test_malformed_observation_and_policy_fail_closed(self):
        for obs in (None, [], {}, {"source": []}, dict(self.obs, canonical_states=[]),
                    dict(self.obs, cameras=[{"serial": []}] * 4)):
            result = assess_decision(action(), obs, self.policy, self.now,
                                     generated_at=self.now, execution_readiness=self.readiness)
            self.assert_rejected(result)
        for policy in (None, [], {}, dict(self.policy, max_translation_axis_m=.005),
                       dict(self.policy, arm_identities=[])):
            result = assess_decision(action(), self.obs, policy, self.now,
                                     generated_at=self.now, execution_readiness=self.readiness)
            self.assert_rejected(result)
    def test_executor_cannot_actuate_for_any_outcome_or_forged_permission(self):
        for label in ("PASS_NOOP", "PASS_EXECUTABLE", "REJECT", "unknown", None):
            result = DryRunExecutor().submit(action(), {"outcome": label, "execution_permitted": True})
            self.assertFalse(result["execution_permitted"])
            self.assertEqual(result["hardware_commands_sent"], 0)
            self.assertEqual(result["motion_commands_sent"], 0)
        self.assertEqual(DryRunExecutor().execution_readiness()["hardware_executor"]["status"],
                         "NOT_IMPLEMENTED")

    def test_frame_ids_match_arm_names_and_state_identity(self):
        for mutate in (
            lambda state: state.update(arm="right"),
            lambda state: state["work_frame"].update(name="Other"),
            lambda state: state["tool_frame"].update(name="Other")):
            self.obs = synthetic_observation(self.now)
            mutate(self.obs["canonical_states"]["left"])
            self.assert_rejected(self.assess(), "ACTION_FRAME_OR_TOOL_MISMATCH")

    def test_boolean_scale_is_not_a_verified_unit(self):
        self.obs["canonical_states"]["left"]["ee_pose"]["unit_scale_applied"] = True
        self.assert_rejected(self.assess(noop()), "ARM_left:STATE_UNITS_UNCONFIRMED")

    def test_camera_freshness_independent_of_robot_and_envelope_timestamp(self):
        for c in self.obs["cameras"]: c["captured_at"] -= 40
        result = self.assess()
        self.assert_rejected(result)
        self.assertTrue(self.gate(result, "camera_freshness")["blocking"])
        self.assertEqual(self.assess(noop())["outcome"], "PASS_NOOP")

    def test_proposal_cannot_predate_its_observation(self):
        result = self.assess(generated_at=self.now - 2)
        self.assert_rejected(result)
        self.assertTrue(self.gate(result, "proposal_observation_order")["blocking"])

    def test_cross_arm_frame_ids_are_schema_invalid(self):
        a = action(); a["frame"] = "realman:right:work:World"
        self.assertIn("ACTION_FRAME_ARM_MISMATCH", validate_action(a))
        a = action(); a["tool_frame"] = "realman:right:tool:Arm_Tip"
        self.assertIn("ACTION_TOOL_FRAME_ARM_MISMATCH", validate_action(a))

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="unit-decision-",dir=ROOT/"logs")
        self.root=Path(self.temp.name); self.obs=synthetic_observation()
        for c in self.obs["cameras"]:
            path=self.root/(c["serial"]+".png")
            c["sha256"]=png_rgb(path,1,1,b"\0\0\0",3)
            c["image_path"]=str(path); c["shape"]=[1,1,3]
    def tearDown(self): self.temp.cleanup()
    def backend_run(self):
        run=self.root/"run"; run.mkdir(); return run
    def test_context_has_all_inputs_and_history(self):
        self.obs["previous"]={"proposal":action(),"result":{"status":"LOGGED_ONLY"}}
        c=build_context(self.obs)
        self.assertEqual(len(c["images_in_attachment_order"]),4)
        self.assertEqual(set(c["canonical_states"]),{"left","right"})
        self.assertIsNotNone(c["previous"])
    def test_missing_corrupt_and_mismatched_images(self):
        bad=copy.deepcopy(self.obs); bad["cameras"].pop()
        with self.assertRaises(BackendFailure): build_context(bad)
        self.obs["cameras"][0]["sha256"]="bad"
        with self.assertRaises(BackendFailure): build_context(self.obs)
    def test_codex_flags_disable_control(self):
        context=build_context(self.obs)
        c=codex_command("/test/codex","unit-model",context["images_in_attachment_order"],self.root)
        self.assertIn("--ephemeral",c); self.assertIn("--ignore-user-config",c)
        self.assertEqual(c[c.index("--sandbox")+1],"read-only")
        self.assertEqual(c.count("--image"),4)
        self.assertIn("shell_tool",c); self.assertIn("hooks",c)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox",c)
    def test_astra_placeholder_never_falls_back(self):
        with self.assertRaisesRegex(BackendFailure,"ASTRA_BACKEND_UNAVAILABLE"):
            AstraBackend().decide(self.obs,self.root)
    def test_codex_success_uses_structured_final_only(self):
        def fake(cmd,**kw):
            raw=json.dumps(action())
            Path(cmd[cmd.index("--output-last-message")+1]).write_text(raw)
            event=json.dumps({"type":"item.completed","item":{"type":"agent_message","text":raw}})
            return subprocess.CompletedProcess(cmd,0,event+'\n{"type":"turn.completed"}\n',"")
        result=CodexBackend("unit-model",runner=fake).decide(self.obs,self.backend_run())
        self.assertEqual(result.proposal,action())
        self.assertTrue(result.metadata["image_attachment_run_completed"])
    def test_nonzero_timeout_and_empty_are_rejected(self):
        cases=[
            ("CODEX_EXIT_NONZERO",lambda cmd,**kw: subprocess.CompletedProcess(cmd,1,"","bad")),
            ("CODEX_TIMEOUT",None),
            ("CODEX_NO_UNIQUE_COMPLETED_PROPOSAL",lambda cmd,**kw:subprocess.CompletedProcess(cmd,0,"",""))]
        for i,(code,runner) in enumerate(cases):
            if runner is None:
                def runner(cmd,**kw): raise subprocess.TimeoutExpired(cmd,1)
            run=self.root/("fail"+str(i)); run.mkdir()
            with self.assertRaisesRegex(BackendFailure,code):
                CodexBackend("unit-model",runner=runner).decide(self.obs,run)
            self.assertEqual(read_json(run/"backend_result.json")["error"],code)
    def test_tool_event_rejected(self):
        with self.assertRaisesRegex(BackendFailure,"TOOL_EVENT"):
            check_events('{"type":"item.started","item":{"type":"command_execution","command":"anything"}}')
    def test_multiple_final_messages_rejected(self):
        line=json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"{}"}})
        with self.assertRaises(BackendFailure):
            check_events(line+'\n'+line+'\n{"type":"turn.completed"}')
    def test_redaction(self):
        self.assertNotIn("sk-secret",redact("sk-secret"))

    def test_known_cli_notice_requires_completed_turn(self):
        notice="Model metadata for `gpt-6.1-sol` not found. Defaulting to fallback metadata; this can degrade performance and cause issues."
        warning=json.dumps({"type":"item.completed","item":{"type":"error","message":notice}})
        final=json.dumps({"type":"item.completed","item":{"type":"agent_message","text":json.dumps(action())}})
        warnings=[]
        self.assertEqual(json.loads(check_events(warning+'\n'+final+'\n{"type":"turn.completed"}',warnings)),action())
        self.assertEqual(warnings,[notice])
        with self.assertRaises(BackendFailure): check_events(warning)
    def test_other_error_is_never_silenced(self):
        with self.assertRaisesRegex(BackendFailure,"CODEX_DIAGNOSTIC_ERROR"):
            check_events('{"type":"item.completed","item":{"type":"error","message":"authentication failed"}}')

    def test_code_mode_disabled_notice_is_nonfatal_only_at_startup(self):
        notice=("Code Mode is unavailable because code-mode host is disabled. "
                "Code mode will fail closed; enable `features.code_mode_host` "
                "and install `codex-code-mode-host`.")
        warning=json.dumps({"type":"item.completed","item":{"type":"error","message":notice}})
        final=json.dumps({"type":"item.completed","item":{"type":"agent_message","text":json.dumps(action())}})
        stream=warning+'\n{"type":"turn.started"}\n'+final+'\n{"type":"turn.completed"}'
        warnings=[]
        self.assertEqual(json.loads(check_events(stream,warnings)),action())
        self.assertEqual(warnings,[notice])
        for bad in (warning,
                    '{"type":"turn.started"}\n'+warning+'\n'+final+'\n{"type":"turn.completed"}',
                    final+'\n{"type":"turn.completed"}\n'+warning,
                    warning+'\n'+final+'\n{"type":"turn.failed"}',
                    warning+'\n'+final+'\n{"type":"error"}',
                    warning+'\n{"type":"item.started","item":{"type":"command_execution"}}'):
            with self.subTest(stream=bad):
                with self.assertRaises(BackendFailure): check_events(bad)
        changed_notice=warning.replace("disabled.", "unavailable.")
        with self.assertRaisesRegex(BackendFailure,"CODEX_DIAGNOSTIC_ERROR"):
            check_events(changed_notice+'\n'+final+'\n{"type":"turn.completed"}')

    def test_disabled_host_notice_does_not_bypass_process_or_schema_checks(self):
        notice=("Code Mode is unavailable because code-mode host is disabled. "
                "Code mode will fail closed; enable `features.code_mode_host` "
                "and install `codex-code-mode-host`.")
        warning=json.dumps({"type":"item.completed","item":{"type":"error","message":notice}})
        for i,mode in enumerate(("success","nonzero","bad_schema","mismatch")):
            run=self.root/("notice-"+str(i)); run.mkdir()
            def fake(cmd,**kw):
                value=action()
                if mode=="bad_schema": value["gripper"]="open"
                raw=json.dumps(value)
                stored=json.dumps(dict(value,done=True)) if mode=="mismatch" else raw
                Path(cmd[cmd.index("--output-last-message")+1]).write_text(stored)
                final=json.dumps({"type":"item.completed","item":{"type":"agent_message","text":raw}})
                return subprocess.CompletedProcess(cmd,1 if mode=="nonzero" else 0,
                    warning+'\n{"type":"turn.started"}\n'+final+'\n{"type":"turn.completed"}',"")
            if mode=="success":
                reply=CodexBackend("gpt-6-astra",runner=fake).decide(self.obs,run)
                self.assertEqual(reply.proposal,action())
                self.assertEqual(reply.metadata["cli_warnings"],[notice])
            else:
                expected={"nonzero":"CODEX_EXIT_NONZERO","bad_schema":"ACTION_SCHEMA_REJECT",
                          "mismatch":"CODEX_FINAL_OUTPUT_MISMATCH"}[mode]
                with self.assertRaisesRegex(BackendFailure,expected):
                    CodexBackend("gpt-6-astra",runner=fake).decide(self.obs,run)

    def test_authorization_redaction_preserves_other_lines(self):
        source="Authorization: Bearer UNIT_TEST_SECRET\nnext line\nauthorization=another-test-secret"
        sanitized=redact(source)
        self.assertNotIn("UNIT_TEST_SECRET",sanitized)
        self.assertNotIn("another-test-secret",sanitized)
        self.assertIn("next line",sanitized)
