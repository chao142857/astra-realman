"""Offline tests for the explicitly selected supervised profile; no SDK or network."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from io_utils import ROOT
from decision_protocol import parse_action, validate_action
from decision_backends import (
    CodexBackend, BackendFailure, build_context, build_prompt, codex_command,
    parse_codex_result, SCHEMA, SUPERVISED_SCHEMA, SUPERVISED_PROFILE)
from test_decision_backend import synthetic_observation, action

def delta_action(delta=.003):
    result=action()
    result["translation_m"]=[0,0,delta]
    return result

class SupervisedBackendTests(unittest.TestCase):
    def test_three_mm_only_with_explicit_limit(self):
        a=delta_action()
        self.assertEqual(parse_action(json.dumps(a),translation_limit_m=.003),a)
        with self.assertRaises(ValueError):
            parse_action(json.dumps(a))
    def test_per_axis_bound_inclusive(self):
        a=delta_action();a["translation_m"]=[-.003,.003,.003]
        self.assertEqual(validate_action(a,translation_limit_m=.003),[])
        for d in (.0030000001,-.0030000001):
            self.assertIn("TRANSLATION_AXIS_LIMIT",
                          validate_action(delta_action(d),translation_limit_m=.003))
    def test_rotation_gripper_nan_boolean_rejected(self):
        for field,value in (("rotation_rpy_rad",[0,.00001,0]),
                            ("gripper","close"),("translation_m",[True,0,0]),
                            ("translation_m",[float("nan"),0,0])):
            a=delta_action();a[field]=value
            with self.assertRaises(ValueError):
                parse_action(json.dumps(a),translation_limit_m=.003)
    def test_policy_limit_cannot_be_arbitrary(self):
        for limit in (.004,1,True,float("nan")):
            self.assertEqual(validate_action(delta_action(),translation_limit_m=limit),
                             ["ACTION_TRANSLATION_POLICY"])
    def test_defaults_unchanged_and_profile_explicit(self):
        self.assertEqual(CodexBackend("fixture").translation_limit_m,.002)
        self.assertEqual(CodexBackend("fixture").schema,SCHEMA)
        b=CodexBackend("fixture",profile=SUPERVISED_PROFILE)
        self.assertEqual(b.translation_limit_m,.003)
        self.assertEqual(b.schema,SUPERVISED_SCHEMA)
        with self.assertRaises(BackendFailure):
            CodexBackend("fixture",profile="allow_any_motion")
    def test_profile_schema_left_only_and_three_mm(self):
        schema=json.loads(SUPERVISED_SCHEMA.read_text())
        self.assertEqual(schema["properties"]["arm"]["enum"],["left"])
        self.assertEqual(schema["properties"]["translation_m"]["items"]["maximum"],.003)
        self.assertEqual(schema["properties"]["translation_m"]["items"]["minimum"],-.003)
        self.assertIn("tool_frame",schema["required"])
        self.assertFalse(schema["additionalProperties"])
    def test_command_uses_profile_schema_preserves_blocking(self):
        run=ROOT/"logs"/"OFFLINE_COMMAND_ONLY"
        command=codex_command("/OFFLINE/codex","fixture",[],run,schema=SUPERVISED_SCHEMA)
        self.assertEqual(command[command.index("--output-schema")+1],str(SUPERVISED_SCHEMA))
        self.assertEqual(command[command.index("--sandbox")+1],"read-only")
        self.assertIn("--ephemeral",command)
        for feature in ("shell_tool","unified_exec","multi_agent","apps","plugins","browser_use"):
            self.assertIn(feature,command)
        default=codex_command("/OFFLINE/codex","fixture",[],run)
        self.assertEqual(default[default.index("--output-schema")+1],str(SCHEMA))
    def artifact_parse(self,a,profile=SUPERVISED_PROFILE,limit=.003):
        with tempfile.TemporaryDirectory(dir=ROOT/"logs",prefix="offline-supervised-backend-") as d:
            run=Path(d)
            raw=json.dumps(a)
            (run/"events.jsonl").write_text(json.dumps({"type":"turn.started"})+"\n"+
                json.dumps({"type":"item.completed","item":{"type":"agent_message","text":raw}})+"\n"+
                json.dumps({"type":"turn.completed"})+"\n")
            (run/"last_message.json").write_text(raw)
            return parse_codex_result(run,0,translation_limit_m=limit,profile=profile)[0]
    def test_profile_actual_event_parser_accepts_three_mm(self):
        self.assertEqual(self.artifact_parse(delta_action()),delta_action())
    def test_profile_runtime_parser_rejects_right(self):
        a=delta_action()
        a.update(arm="right",frame="realman:right:work:World",tool_frame="realman:right:tool:Arm_Tip")
        with self.assertRaisesRegex(ValueError,"SUPERVISED_LEFT_ONLY"):
            self.artifact_parse(a)
    def test_profile_runtime_parser_rejects_over_limit_and_rotation(self):
        with self.assertRaises(ValueError):self.artifact_parse(delta_action(.0031))
        a=delta_action();a["rotation_rpy_rad"]=[0,.1,0]
        with self.assertRaises(ValueError):self.artifact_parse(a)
    def test_default_artifact_parser_remains_two_mm(self):
        with self.assertRaises(ValueError):
            self.artifact_parse(delta_action(),profile=None,limit=.002)
    def test_profile_limit_mismatch_rejected(self):
        with self.assertRaisesRegex(BackendFailure,"CODEX_PROFILE_LIMIT_MISMATCH"):
            self.artifact_parse(delta_action(),limit=.002)
    def test_prompt_not_forcing_motion_or_fabricating_axes(self):
        context={"decision_profile":SUPERVISED_PROFILE}
        prompt=build_prompt(context)
        for text in ("0.003 m","EXECUTE","nonzero answer is NOT mandatory",
                     "never guess axis signs","NO execution","gripper must be hold"):
            self.assertIn(text,prompt)
        old=build_prompt({})
        self.assertIn("0.002 m",old)

if __name__=="__main__":
    unittest.main()
