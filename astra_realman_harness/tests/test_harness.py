import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer,BaseHTTPRequestHandler
import socketserver
from unittest.mock import patch
from io_utils import ROOT,read_json,strict_json,output_path
from observation import offline_observation,query_state
from protocol import fixture_proposal,parse
from safety import assess
from providers import call_api,make_request
import harness

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.obs=offline_observation("test cube transfer")
        self.now=time.time()
        self.p=fixture_proposal(self.obs,self.now)
        self.policy=read_json(ROOT/"fixtures/synthetic_policy.json")["safety"]
    def result(self):
        return assess(self.p,self.obs,self.policy,self.now)
    def rejected(self,part):
        r=self.result()
        self.assertEqual(r["decision"],"REJECTED")
        self.assertTrue(any(part in e for e in r["errors"]),r)
        self.assertFalse(r["execution_permitted"])
    def test_valid_fixture_is_never_execution_authorization(self):
        r=self.result()
        self.assertEqual(r["decision"],"VALID_DRY_RUN_ONLY")
        self.assertFalse(r["execution_permitted"])
        self.assertEqual(r["hardware_commands_sent"],0)
    def test_lab_uncalibrated_motion_is_blocked(self):
        self.policy=read_json(ROOT/"config/lab.json")["safety"]
        self.policy["allowed_arms"]=["right"]  # Test this synthetic right fixture against unchanged lab geometry.
        for expected in ("TCP_UNCONFIRMED","WORKSPACE_UNCONFIRMED","BASE_FRAME_UNCONFIRMED"):
            self.rejected(expected)
    def test_fixture_policy_rejects_real_source(self):
        self.obs["source"]["kind"]="real_capture"
        self.rejected("SYNTHETIC_POLICY_FORBIDDEN")
    def test_missing_frame(self):
        del self.p["actions"][0]["frame"]
        self.rejected("FIELDS")
    def test_implicit_world_frame(self):
        self.p["actions"][0]["frame"]="world"
        self.rejected("FRAME")
    def test_opposite_arm_frame(self):
        self.p["actions"][0]["frame"]="left_base"
        self.rejected("FRAME")
    def test_arm_not_enabled(self):
        self.p["actions"][0].update(arm="left",frame="left_base")
        self.rejected("ARM_NOT_ALLOWED")
    def test_model_cannot_override_policy(self):
        self.p["safety"]={"allow_execution":True}
        self.rejected("PROPOSAL_FIELDS")
    def test_model_cannot_override_calibration(self):
        self.p["actions"][0]["tcp_confirmed"]=True
        self.rejected("FIELDS")
    def test_observation_binding(self):
        self.p["observation_id"]="another"
        self.rejected("OBSERVATION_ID_MISMATCH")
    def test_stale_observation(self):
        self.obs["captured_at"]-=100
        self.rejected("STALE_OBSERVATION")
    def test_future_observation(self):
        self.obs["captured_at"]+=10
        self.rejected("FUTURE_OBSERVATION")
    def test_stale_robot_state(self):
        self.obs["robot"]["arms"]["right"]["captured_at"]-=100
        self.rejected("STATE_STALE")
    def test_stale_camera(self):
        self.obs["cameras"][0]["captured_at"]-=100
        self.rejected("CAMERA_TIME")
    def test_stereo_temporal_skew(self):
        self.obs["cameras"].append({**self.obs["cameras"][0],"captured_at":self.now-5})
        self.rejected("CAMERA_TIME_SKEW")
    def test_expiry(self):
        self.p["expires_at"]=self.now-1
        self.rejected("EXPIRED")
    def test_ttl(self):
        self.p["expires_at"]=self.now+10000
        self.rejected("TTL_TOO_LONG")
    def test_future_proposal(self):
        self.p["created_at"]=self.now+10
        self.rejected("FUTURE_PROPOSAL")
    def test_boolean_as_numeric(self):
        self.p["actions"][0]["delta_m"]=[True,0,0]
        self.rejected("DELTA")
    def test_nonfinite_proposal(self):
        for val in (float("nan"),float("inf"),-float("inf")):
            self.p["actions"][0]["delta_m"]=[val,0,0]
            self.rejected("DELTA")
    def test_duplicate_and_nonfinite_json(self):
        for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(ValueError): strict_json(text)
    def test_markdown_not_accepted(self):
        with self.assertRaises(ValueError):
            parse(chr(96)*3+"json\n"+json.dumps(self.p)+"\n"+chr(96)*3)
    def test_delta_limit(self):
        self.p["actions"][0]["delta_m"]=[0,0,0.011]
        self.rejected("TRANSLATION_LIMIT")
    def test_norm_not_individual_axis_limit(self):
        self.p["actions"][0]["delta_m"]=[0.009,0.009,0]
        self.rejected("TRANSLATION_LIMIT")
    def test_workspace_endpoint(self):
        self.obs["robot"]["arms"]["right"]["poses"]["tcp"]["position_m"]=[0.3,0,0.499]
        self.rejected("WORKSPACE_LIMIT")
    def test_speed_limit(self):
        self.p["actions"][0]["speed_m_s"]=1
        self.rejected("SPEED_LIMIT")
    def test_chunk_rejected_by_first_step_policy(self):
        self.p["actions"]*=2
        self.rejected("TOO_MANY_ACTIONS")
    def test_invalid_quaternion(self):
        self.p["actions"]=[{"type":"move_pose","arm":"right","frame":"right_base","target":"tcp",
                           "position_m":[0.3,0,0.3],"quaternion_wxyz":[0,0,0,0],"speed_m_s":0.005}]
        self.rejected("QUATERNION")
    def test_orientation_limit(self):
        self.p["actions"]=[{"type":"move_pose","arm":"right","frame":"right_base","target":"tcp",
                           "position_m":[0.3,0,0.3],"quaternion_wxyz":[0,0,0,1],"speed_m_s":0.005}]
        self.rejected("ROTATION_LIMIT")
    def test_gripper_range_and_step(self):
        self.p["actions"]=[{"type":"gripper","arm":"right","frame":"right_gripper","opening_fraction":1.5}]
        self.rejected("GRIPPER_RANGE")
        self.p["actions"][0]["opening_fraction"]=1.0
        self.rejected("GRIPPER_STEP_LIMIT")
    def test_policy_cannot_enable_unvalidated_multi_step(self):
        self.policy["max_actions"]=3
        with self.assertRaises(ValueError): self.result()
    def test_bad_trusted_policy_fails_closed(self):
        self.policy["max_speed_m_s"]=float("nan")
        with self.assertRaises(ValueError): self.result()
    def test_controller_fault_is_independent_rejection(self):
        self.obs["robot"]["arms"]["right"]["controller_errors"]=[4105]
        self.rejected("CONTROLLER_ERROR_PRESENT")
    def test_unknown_controller_fault_is_rejected(self):
        del self.obs["robot"]["arms"]["right"]["controller_errors"]
        self.rejected("CONTROLLER_STATUS_UNAVAILABLE")
    def test_no_execution_config_mode(self):
        self.policy["mode"]="execute"
        with self.assertRaises(ValueError): self.result()
    def test_no_execute_cli(self):
        with self.assertRaises(SystemExit): harness.main(["execute-once"])
    def test_output_cannot_escape_harness(self):
        with self.assertRaises(ValueError): output_path("/home/tongji/aloha/test.json")
    def test_lab_configs_keep_transforms_unknown(self):
        c=read_json(ROOT/"config/lab.json")
        self.assertIsNone(c["frames"]["world_transform"])
        self.assertIsNone(c["frames"]["cross_arm_transform"])
        self.assertTrue(all(a["workspace_m"] is None for a in c["safety"]["arms"].values()))

class TransportTests(unittest.TestCase):
    def test_only_state_query_is_transmitted(self):
        received=[]
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                received.append(self.request.recv(4096))
                self.request.sendall(b'{"state":"current_arm_state","arm_state":{"joint":[1000,2000,3000,4000,5000,6000],"pose":[100000,200000,300000,400,500,600],"err":[0]}}\r\n')
        server=socketserver.TCPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.handle_request);thread.start()
        try:
            result=query_state("127.0.0.1",server.server_address[1])
            self.assertEqual(received,[b'{"command":"get_current_arm_state"}\r\n'])
            self.assertEqual(result["joints_deg"],[1,2,3,4,5,6])
            self.assertEqual(result["canonical"]["pose"]["position_m"],[.1,.2,.3])
            self.assertEqual(result["canonical"]["pose"]["rpy_rad"],[.4,.5,.6])
            self.assertIsNone(result["canonical"]["pose"]["frame"])
        finally:
            thread.join(5);server.server_close()
    def test_api_contract_roundtrip_without_hardware(self):
        obs=offline_observation("test");seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append(request)
                body=json.dumps(fixture_proposal(request["observation"],time.time())).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
            def log_message(self,*args): pass
        server=HTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.handle_request);thread.start()
        try:
            api={"contract":"astra.proposal_http.v1","endpoint":"http://127.0.0.1:%d/propose"%server.server_port}
            raw=call_api(api,obs,read_json(ROOT/"schema/action.schema.json"),allow_test_http=True)
            self.assertEqual(parse(raw)["observation_id"],obs["observation_id"])
            self.assertIn("action_schema",seen[0])
            self.assertNotIn("raw_response",str(seen[0]))
        finally:
            thread.join(5);server.server_close()
    def test_api_unconfigured_and_plain_http_rejected(self):
        obs=offline_observation("test")
        for endpoint in (None,"http://example.com","https://user:pass@example.com"):
            with self.assertRaises(ValueError):
                call_api({"contract":"astra.proposal_http.v1","endpoint":endpoint},obs,{})
    def test_api_image_integrity_before_upload(self):
        obs=offline_observation("test")
        obs["cameras"][0]["image_path"]=str(ROOT/"README.md")
        obs["cameras"][0]["sha256"]="bad"
        with self.assertRaises(ValueError): make_request(obs,{})

class EndToEndTests(unittest.TestCase):
    def test_cli_positive_fixture_and_lab_rejection_no_hardware(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as directory:
            base=Path(directory)
            with patch("socket.create_connection",side_effect=AssertionError("NETWORK_FORBIDDEN")):
                self.assertEqual(harness.main(["offline-observation","--task","fixture","--out",str(base/"obs")]),0)
                common=["--observation",str(base/"obs/observation.json"),"--provider","fixture"]
                self.assertEqual(harness.main(["dry-run",*common,"--config",str(ROOT/"fixtures/synthetic_policy.json"),
                                               "--out",str(base/"pass")]),0)
                self.assertEqual(harness.main(["dry-run",*common,"--out",str(base/"blocked")]),2)
                self.assertFalse(read_json(base/"pass/validation.json")["execution_permitted"])
                self.assertEqual(read_json(base/"blocked/event.json")["motion_commands_sent"],0)

if __name__=="__main__":
    unittest.main(verbosity=2)
