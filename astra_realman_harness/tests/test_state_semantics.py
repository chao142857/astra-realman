import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import copy
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
from io_utils import ROOT, read_json
import realman_state as rm
from observation import offline_observation
from camera_session import CameraSession
from protocol import fixture_proposal, parse, validate
from safety import assess
from transforms import rpy_to_quaternion

def sample(command, raw):
    return {"transport": rm.TRANSPORT, "raw_response": raw, "received_at": time.time(), "command": command}
def bundle(arm="right", err=0):
    s=sample("get_current_arm_state", {"state":"current_arm_state","arm_state":{
        "joint":[5799,20420,46038,-5023,95438,7645],
        "pose":[-331408,-19535,411631,-3101,324,-47],"err":[err]}})
    w=rm.decode_frame(sample("get_current_work_frame",{
        "state":"current_work_frame","frame_name":"World","pose":[0]*6}),arm,"work")
    t=rm.decode_frame(sample("get_current_tool_frame",{
        "state":"current_tool_frame","tool_name":"Arm_Tip","pose":[0]*6}),arm,"tool")
    return rm.normalize_state(s,w,t,True)

class StateTests(unittest.TestCase):
    def test_raw_integer_scaling_once(self):
        s=bundle()
        self.assertEqual(s["joints_deg"],[5.799,20.42,46.038,-5.023,95.438,7.645])
        p=s["canonical"]["pose"]
        self.assertEqual(p["position_m"],[-.331408,-.019535,.411631])
        self.assertEqual(p["rpy_rad"],[-3.101,.324,-.047])
        self.assertEqual(p["conversion_count"],1)
        self.assertEqual(s["canonical"]["joint"]["conversion_count"],1)
        self.assertEqual(p["orientation_metadata"]["rotation_convention"],"ZYX intrinsic")
    def test_float_or_boolean_cannot_be_converted_again(self):
        for raw in ([1.,2.,3.,4.,5.,6.],[False,0,0,0,0,0],[1]*5):
            self.assertFalse(rm.decode_pose(raw,rm.TRANSPORT)["units_confirmed"])
            s=rm.normalize_state(sample("get_current_arm_state",{"arm_state":{"joint":raw,"pose":raw,"err":[0]}}))
            self.assertIsNone(s["joints_deg"])
            self.assertFalse(s["state_units_confirmed"])
    def test_wrong_transport_never_scales(self):
        self.assertFalse(rm.decode_pose([0]*6,"existing_wrapper_mm_rad")["units_confirmed"])
    def test_no_world_or_tcp_alias_invented(self):
        s=bundle()
        self.assertEqual(s["canonical"]["pose"]["frame"],"realman:right:work:World")
        self.assertEqual(s["canonical"]["tool_frame"]["name"],"Arm_Tip")
        self.assertNotIn("tcp",s["poses"])
        self.assertNotIn("quaternion_wxyz",s["canonical"]["pose"])
        self.assertEqual(s["canonical"]["pose"]["frame_binding_status"],"UNCONFIRMED")
    def test_only_three_read_commands_allowed(self):
        self.assertEqual(set(rm.COMMANDS),{"get_current_arm_state","get_current_work_frame","get_current_tool_frame"})
        with patch("realman_state.socket.create_connection",side_effect=AssertionError("no connection")):
            with self.assertRaises(ValueError): rm.read_query("127.0.0.1",1,"clear_system_err")
            with self.assertRaises(ValueError): rm.read_query("127.0.0.1",1,"movej")
    def test_frame_change_detected_without_fallback(self):
        def fake(host,port,command,timeout):
            raw = ({"state":"current_arm_state","arm_state":{"joint":[0]*6,"pose":[0]*6,"err":[0]}}
                   if command=="get_current_arm_state" else
                   {"state":command[4:],"pose":[0]*6,
                    "frame_name" if "work" in command else "tool_name":"World" if "work" in command else "Arm_Tip"})
            if command=="get_current_work_frame":
                fake.n+=1
                if fake.n==2: raw["pose"][0]=1
            return sample(command,raw)
        fake.n=0
        with patch("realman_state.read_query",side_effect=fake) as q:
            s=rm.query_snapshot("localhost",1,"right")
        self.assertFalse(s["frame_snapshot_stable"])
        self.assertEqual(q.call_count,5)
    def test_error_read_is_not_error_clear(self):
        s=bundle(err=4105)
        self.assertEqual(s["system_error_raw"],[4105])
        self.assertEqual(s["controller_errors"],[4105])
        self.assertFalse(s["error_clear_attempted"])
    def test_raw_scalar_system_error(self):
        s=sample("get_current_arm_state",{"arm_state":{"joint":[0]*6,"pose":[0]*6,"err":4105}})
        result=rm.normalize_state(s)
        self.assertEqual(result["system_error_raw"],4105)
        self.assertEqual(result["controller_errors"],[4105])
    def test_zyx_rpy_math(self):
        q=rpy_to_quaternion([0,0,3.141592653589793])
        self.assertAlmostEqual(q[0],0)
        self.assertAlmostEqual(q[3],1)
        self.assertIsNone(rpy_to_quaternion([0,float("nan"),0]))

class RealSafetyTests(unittest.TestCase):
    def setUp(self):
        self.obs=offline_observation("test")
        self.obs["source"]["kind"]="real_capture"
        self.obs["robot"]["arms"]={a:bundle(a) for a in ("left","right")}
        self.obs["capture_span_ms"]=0
        self.obs["camera_capture"]={"timestamp_semantics_confirmed":True,"expected_serials":["SYNTHETIC"]}
        self.p=fixture_proposal(self.obs,time.time())
        self.policy=read_json(ROOT/"config/lab.json")["safety"]
        self.policy["allowed_arms"]=["left","right"]  # Explicit isolated dual-arm test policy.
    def result(self):
        return assess(self.p,self.obs,self.policy,time.time())
    def test_named_fixture_is_explicit_and_preserves_rpy(self):
        self.assertEqual(validate(self.p),[])
        a=self.p["actions"][0]
        self.assertEqual(a["frame"],"realman:right:work:World")
        self.assertEqual(a["tool_frame"],"realman:right:tool:Arm_Tip")
        preview=self.result()["actions_checked"][0]["transform_preview"]
        self.assertAlmostEqual(preview["target_position_m"][2],.416631)
        self.assertEqual(preview["rpy_rad"],[-3.101,.324,-.047])
        self.assertFalse(preview["execution_permitted"])
    def test_other_arm_fault_blocks_even_observe(self):
        self.obs["robot"]["arms"]["left"]["controller_errors"]=[4105]
        self.p["actions"]=[{"arm":"right","type":"observe","frame":"right_base"}]
        r=self.result()
        self.assertIn("ARM_left:CONTROLLER_ERROR_PRESENT",r["errors"])
        self.assertEqual(r["decision"],"REJECTED")
    def test_state_units_must_be_confirmed(self):
        self.obs["robot"]["arms"]["left"]["state_units_confirmed"]=False
        self.assertIn("ARM_left:STATE_UNITS_UNCONFIRMED",self.result()["errors"])
    def test_pose_frame_binding_not_guessed(self):
        r=self.result()
        self.assertIn("ARM_right:STATE_FRAME_BINDING_UNCONFIRMED",r["errors"])
        self.assertFalse(r["execution_permitted"])
    def test_different_named_tool_rejected(self):
        self.p["actions"][0]["tool_frame"]="realman:right:tool:Other"
        self.assertTrue(any("CURRENT_TOOL_FRAME_MISMATCH" in e for e in self.result()["errors"]))
    def test_wrong_arm_named_frame_fails_parse(self):
        self.p["actions"][0]["frame"]="realman:left:work:World"
        with self.assertRaises(ValueError): parse(json.dumps(self.p))
    def test_no_frame_means_no_fixture_guess(self):
        self.obs["robot"]["arms"]["right"]["canonical"]["tool_frame"]=None
        with self.assertRaises(ValueError): fixture_proposal(self.obs,time.time())
    def test_incomparable_clock_is_rejected(self):
        self.obs["camera_capture"]["timestamp_semantics_confirmed"]=False
        self.assertIn("CAMERA_TIMESTAMP_SEMANTICS_UNCONFIRMED",self.result()["errors"])
    def test_span_is_recomputed_not_trusted(self):
        self.obs["capture_span_ms"]=123
        self.assertIn("CAMERA_SPAN_INCONSISTENT",self.result()["errors"])
    def test_camera_skew_and_missing_camera_rejected(self):
        self.obs["cameras"].append({**self.obs["cameras"][0],"serial":"second","captured_at":time.time()-2})
        r=self.result()
        self.assertIn("CAMERA_TIME_SKEW",r["errors"])
        self.assertIn("CAMERA_SET_INCOMPLETE",r["errors"])


class LeftOnlyTests(unittest.TestCase):
    def setUp(self):
        self.cfg=read_json(ROOT/"config/lab.json")
        self.obs=offline_observation("left-only synthetic state test")
        self.obs["source"]["kind"]="real_capture"
        self.obs["robot"]["arms"]={"left":bundle("left")}
        self.obs["capture_span_ms"]=0
        self.obs["camera_capture"]={"timestamp_semantics_confirmed":True,"expected_serials":["SYNTHETIC"]}
    def test_config_and_fixture_select_only_left(self):
        self.assertEqual(self.cfg["safety"]["allowed_arms"],["left"])
        self.assertEqual(self.cfg["fixture_arm"],"left")
        p=fixture_proposal(self.obs,time.time(),arm=self.cfg["fixture_arm"])
        self.assertEqual(p["actions"][0]["arm"],"left")
        self.assertEqual(p["actions"][0]["frame"],"realman:left:work:World")
        self.assertEqual(p["actions"][0]["tool_frame"],"realman:left:tool:Arm_Tip")
        self.assertEqual(validate(p),[])
    def test_inactive_right_error_does_not_change_left_result(self):
        p=fixture_proposal(self.obs,time.time(),arm="left")
        now=time.time()
        a=assess(p,self.obs,self.cfg["safety"],now)
        self.obs["robot"]["arms"]["right"]=bundle("right",4105)
        b=assess(p,self.obs,self.cfg["safety"],now)
        self.assertEqual(a["errors"],b["errors"])
        self.assertFalse(any("ARM_right:" in e for e in b["errors"]))
        self.assertFalse(b["execution_permitted"])
    def test_right_proposal_cannot_bypass_left_only_policy(self):
        self.obs["robot"]["arms"]["right"]=bundle("right")
        p=fixture_proposal(self.obs,time.time(),arm="right")
        r=assess(p,self.obs,self.cfg["safety"],time.time())
        self.assertIn("ACTION_0:ARM_NOT_ALLOWED",r["errors"])
    def test_active_left_error_still_blocks(self):
        self.obs["robot"]["arms"]["left"]["controller_errors"]=[4105]
        p=fixture_proposal(self.obs,time.time(),arm="left")
        r=assess(p,self.obs,self.cfg["safety"],time.time())
        self.assertIn("ARM_left:CONTROLLER_ERROR_PRESENT",r["errors"])
    def test_capture_reads_only_left(self):
        from observation import capture
        class FakeCameras:
            configs=[]
            def snapshot(self,run):
                return [],[],{"capture_span_ms":None}
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            with patch("observation.query_snapshot",return_value=bundle("left")) as q:
                result=capture(self.cfg,Path(d),"test",[],["left"],FakeCameras())
                self.assertEqual(list(result["robot"]["arms"]),["left"])
                q.assert_called_once_with(self.cfg["devices"]["arms"]["left"]["host"],
                                          self.cfg["devices"]["arms"]["left"]["port"],"left")
    def test_inactive_capture_rejected_before_any_device_access(self):
        from observation import capture
        with patch("observation.CameraSession",side_effect=AssertionError("NO_CAMERA")):
            with patch("observation.query_snapshot",side_effect=AssertionError("NO_ROBOT")):
                with self.assertRaises(ValueError):
                    capture(self.cfg,ROOT/"logs","test",[],["right"])

class CameraTests(unittest.TestCase):
    def fake_rs(self):
        calls={"start":0,"stop":0}
        intr=NS(width=1,height=1,fx=1,fy=1,ppx=0,ppy=0,model="test",coeffs=[0]*5)
        class Device:
            def __init__(self,s): self.s=s
            def get_info(self,k): return self.s
        class Config:
            def enable_device(self,s): self.s=s
            def enable_stream(self,*args): pass
        class Frame:
            def __init__(self,n):
                self.n=n
                self.t=time.time()*1000
                self.profile=NS(as_video_stream_profile=lambda:NS(get_intrinsics=lambda:intr))
            def get_timestamp(self): return self.t
            def get_frame_timestamp_domain(self): return "timestamp_domain.global_time"
            def get_frame_number(self): return self.n
            def get_data(self): return b"\x01\x02\x03"
            def get_stride_in_bytes(self): return 3
        class Pipeline:
            def __init__(self,*args): self.n=0
            def start(self,c): calls["start"]+=1
            def stop(self): calls["stop"]+=1
            def wait_for_frames(self,timeout):
                time.sleep(.01);self.n+=1
                return NS(get_color_frame=lambda:Frame(self.n))
        rs=NS(context=lambda:NS(query_devices=lambda:[Device(str(i)) for i in range(4)]),
              pipeline=Pipeline,config=Config,camera_info=NS(serial_number="serial"),
              stream=NS(color="color"),format=NS(rgb8="rgb8"))
        return rs,calls
    def test_pipelines_persist_across_observations(self):
        rs,calls=self.fake_rs()
        configs=[{"serial":str(i),"width":1,"height":1,"fps":30} for i in range(4)]
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            root=Path(d);(root/"a").mkdir();(root/"b").mkdir()
            with CameraSession(configs,rs_module=rs) as session:
                a,fail,m1=session.snapshot(root/"a")
                b,fail2,m2=session.snapshot(root/"b")
                self.assertEqual(fail+fail2,[])
                self.assertEqual(calls["start"],4)
                self.assertEqual(calls["stop"],0)
                self.assertEqual(m1["camera_session_id"],m2["camera_session_id"])
                self.assertEqual(m2["observation_index"],2)
                self.assertTrue(all(y["sequence"]>x["sequence"] for x,y in zip(a,b)))
                self.assertAlmostEqual(m2["capture_span_ms"],(max(x["captured_at"] for x in b)-min(x["captured_at"] for x in b))*1000)
            self.assertEqual(calls["stop"],4)
    def test_missing_device_is_reported(self):
        rs,_=self.fake_rs()
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            with CameraSession([{"serial":"absent"}],rs_module=rs) as session:
                cameras,errors,m=session.snapshot(Path(d))
        self.assertEqual(cameras,[])
        self.assertEqual(errors[0]["message"],"SDK_SERIAL_NOT_FOUND")
        self.assertFalse(m["timestamp_semantics_confirmed"])

if __name__=="__main__": unittest.main(verbosity=2)
