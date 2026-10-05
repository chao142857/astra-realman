import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from io_utils import ROOT
from realman_api2_readonly import canonical_state,sdk_pose,sdk_errors,SDKReadOnly,ALLOWED
from legacy_state_compare import compare,StateReadSocket,read_legacy

def state_sample():
    now=time.time()
    state={"joint":[5.8,20.4,46.0,-5.0,95.4,7.6],"pose":[-.331,-.019,.411,-3.1,.324,-.047],
           "err":{"err_len":1,"err":["4105"]}}
    work={"name":"World","pose":[0.]*6,"payload":0.,"x":0.,"y":0.,"z":0.}
    tool={**work,"name":"Arm_Tip"}
    values={"state":state,"work_before":work,"work_after":work,"tool_before":tool,"tool_after":tool}
    return {"calls":{k:{"return_code":0,"raw_return":[0,copy.deepcopy(v)],"finished_at":now} for k,v in values.items()}}

class CanonicalTests(unittest.TestCase):
    def test_sdk_values_preserved_without_rescaling(self):
        s=state_sample();raw=copy.deepcopy(s);c=canonical_state("right",s)
        self.assertEqual(c["joint_deg"],s["calls"]["state"]["raw_return"][1]["joint"])
        self.assertEqual(c["ee_pose"]["xyz_m"],[-.331,-.019,.411])
        self.assertEqual(c["ee_pose"]["rpy_rad"],[-3.1,.324,-.047])
        self.assertEqual(c["ee_pose"]["unit_scale_applied"],1)
        self.assertEqual(s,raw)
    def test_sdk_frame_values_are_not_scaled(self):
        s=state_sample()
        s["calls"]["tool_before"]["raw_return"][1]["pose"]=[.1,.2,.3,.4,.5,.6]
        c=canonical_state("left",s)
        self.assertEqual(c["tool_frame"]["pose"]["xyz_m"],[.1,.2,.3])
        self.assertFalse(c["frame_snapshot_stable"])
    def test_frame_meaning_not_invented_from_zero_offsets(self):
        c=canonical_state("left",state_sample())
        self.assertIsNone(c["ee_pose"]["reference_frame"])
        self.assertIsNone(c["ee_pose"]["target_frame"])
        self.assertEqual(c["ee_pose"]["frame_semantics_status"],"UNKNOWN")
        self.assertFalse(c["execution_permitted"])
    def test_recorded_active_ids_do_not_claim_ee_binding_or_grasp_tcp(self):
        for arm in ("left", "right"):
            with self.subTest(arm=arm):
                c=canonical_state(arm,state_sample())
                self.assertEqual(c["work_frame"]["id"],"realman:%s:work:World"%arm)
                self.assertEqual(c["tool_frame"]["id"],"realman:%s:tool:Arm_Tip"%arm)
                self.assertEqual(c["ee_pose"]["active_work_frame_id"],c["work_frame"]["id"])
                self.assertEqual(c["ee_pose"]["active_tool_frame_id"],c["tool_frame"]["id"])
                self.assertIsNone(c["ee_pose"]["reference_frame_id"])
                self.assertIsNone(c["ee_pose"]["target_frame_id"])
                self.assertEqual(c["ee_pose"]["frame_semantics_status"],"UNKNOWN")
                for frame in (c["work_frame"],c["tool_frame"]):
                    self.assertEqual(frame["read_status"],"VERIFIED")
                    self.assertEqual(frame["physical_grasp_calibration"],"UNCONFIRMED")
                self.assertEqual(c["work_frame"]["relative_to"],"controller_base")
                self.assertEqual(c["tool_frame"]["relative_to"],"controller_flange")
                self.assertIsNone(c["connection"])

    def test_raw_returns_and_connection_are_independent_snapshots(self):
        s=state_sample()
        conn={"arm":"left","ip":"192.168.1.19","sdk_handle_id":7,
              "source":{"arguments":{"ip":"192.168.1.19","port":8080}}}
        c=canonical_state("left",s,connection=conn)
        original=copy.deepcopy(c)
        for key,label in (("raw_sdk_state","state"),("raw_work_frame","work_before"),
                          ("raw_tool_frame","tool_before")):
            self.assertEqual(c[key],s["calls"][label]["raw_return"][1])
        s["calls"]["state"]["raw_return"][1]["joint"][0]=999
        s["calls"]["state"]["raw_return"][1]["pose"][0]=999
        s["calls"]["state"]["raw_return"][1]["err"]["err"][0]="999"
        s["calls"]["work_before"]["raw_return"][1]["pose"][0]=999
        s["calls"]["tool_before"]["raw_return"][1]["pose"][0]=999
        conn["source"]["arguments"]["ip"]="changed"
        self.assertEqual(c,original)
        raw_joint=c["raw_sdk_state"]["joint"][0]
        c["joint_deg"][0]=123
        c["ee_pose"]["xyz_m"][0]=123
        c["work_frame"]["pose"]["xyz_m"][0]=123
        c["tool_frame"]["pose"]["xyz_m"][0]=123
        self.assertEqual(c["raw_sdk_state"]["joint"][0],raw_joint)
        self.assertEqual(c["raw_sdk_state"]["pose"][0],-.331)
        self.assertEqual(c["raw_work_frame"]["pose"][0],0.)
        self.assertEqual(c["raw_tool_frame"]["pose"][0],0.)
        c["raw_sdk_state"]["err"]["err"][0]="123"
        self.assertEqual(c["system_error"]["raw"]["err"],["4105"])

    def test_definition_fingerprint_tracks_same_name_frame_edits(self):
        s=state_sample()
        baseline=canonical_state("left",s)
        reordered=copy.deepcopy(s)
        for label in ("work_before","work_after","tool_before","tool_after"):
            v=reordered["calls"][label]["raw_return"][1]
            reordered["calls"][label]["raw_return"][1]=dict(reversed(list(v.items())))
        self.assertEqual(canonical_state("left",reordered)["work_frame"]["definition_fingerprint"],
                         baseline["work_frame"]["definition_fingerprint"])
        changed=copy.deepcopy(s)
        for label in ("work_before","work_after"):
            changed["calls"][label]["raw_return"][1]["pose"][0]=.025
        updated=canonical_state("left",changed)
        self.assertEqual(updated["work_frame"]["id"],baseline["work_frame"]["id"])
        self.assertNotEqual(updated["work_frame"]["definition_fingerprint"],
                            baseline["work_frame"]["definition_fingerprint"])
        self.assertEqual(updated["tool_frame"]["definition_fingerprint"],
                         baseline["tool_frame"]["definition_fingerprint"])
        self.assertEqual(updated["work_frame"]["pose"]["xyz_m"],[.025,0.,0.])
        self.assertIsNone(updated["ee_pose"]["reference_frame_id"])
        self.assertTrue(updated["frame_snapshot_stable"])
        for frame in ("work_frame","tool_frame"):
            self.assertRegex(updated[frame]["definition_fingerprint"],r"^[0-9a-f]{64}$")

    def test_sdk_small_values_are_preserved_in_all_canonical_and_raw_fields(self):
        s=state_sample()
        joints=[.001,-.002,.003,-.004,.005,-.006]
        pose=[.000001,-.000002,.000003,.001,-.002,.003]
        s["calls"]["state"]["raw_return"][1].update(joint=joints[:],pose=pose[:])
        for label in ("work_before","work_after","tool_before","tool_after"):
            s["calls"][label]["raw_return"][1]["pose"]=pose[:]
        c=canonical_state("left",s)
        self.assertEqual(c["joint_deg"],joints)
        self.assertEqual(c["source"]["joint_unit"],"deg")
        self.assertEqual(c["raw_sdk_state"]["pose"],pose)
        for p in (c["ee_pose"],c["work_frame"]["pose"],c["tool_frame"]["pose"]):
            self.assertEqual(p["xyz_m"]+p["rpy_rad"],pose)
            self.assertEqual(p["units"],{"xyz":"m","rpy":"rad"})
            self.assertEqual(p["unit_scale_applied"],1)

    def test_failed_sdk_code_does_not_produce_zero_state(self):
        for code in (-3,1,False,None):
            s=state_sample();s["calls"]["state"]["return_code"]=code
            with self.assertRaises(ValueError): canonical_state("left",s)
    def test_invalid_units_data_rejected(self):
        for pose in ([0]*5,[0,0,0,0,0,float("nan")],[False]*6):
            with self.assertRaises(ValueError): sdk_pose(pose)
    def test_error_structure_normalized_preserving_raw(self):
        raw={"err_len":2,"err":["0","4105"]}
        e=sdk_errors(raw)
        self.assertEqual(e["codes"],[0,4105]);self.assertTrue(e["has_error"]);self.assertEqual(e["raw"],raw)
        self.assertFalse(sdk_errors({"err_len":0,"err":[]})["has_error"])
    def test_malformed_error_cannot_be_treated_as_clear(self):
        for raw in ({},{"err_len":1,"err":[]},{"err_len":1,"err":["bad"]},{"err_len":True,"err":["0"]}):
            with self.assertRaises(ValueError): sdk_errors(raw)

class LifecycleTests(unittest.TestCase):
    def test_only_whitelisted_api_calls_and_cleanup(self):
        seen=[]
        class Robot:
            def rm_get_current_arm_state(self):
                seen.append("state");return 0,state_sample()["calls"]["state"]["raw_return"][1]
            def rm_get_current_work_frame(self):
                seen.append("work");return 0,state_sample()["calls"]["work_before"]["raw_return"][1]
            def rm_get_current_tool_frame(self):
                seen.append("tool");return 0,state_sample()["calls"]["tool_before"]["raw_return"][1]
        def record(name,value):
            def call(*args): seen.append(name);return value
            return call
        sdk=NS(rm_thread_mode_e=NS(RM_DUAL_MODE_E=1),rm_init=record("init",0),
               rm_create_robot_arm=record("connect",NS(contents=NS(id=1))),
               rm_delete_robot_arm=record("delete",0),rm_destroy=record("destroy",0),RoboticArm=Robot)
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            with SDKReadOnly(Path(d),sdk=sdk) as adapter:
                self.assertTrue(adapter.connect("left","127.0.0.1",1)["connected"])
                snap=adapter.snapshot("left")
                self.assertIsNotNone(snap["canonical"])
                with self.assertRaises(ValueError):
                    adapter._call("rm_movej",lambda:seen.append("FORBIDDEN"))
            self.assertEqual(seen,["init","connect","work","tool","state","work","tool","delete","destroy"])
            self.assertTrue(all(e["function"] in ALLOWED for e in adapter.events))
    def test_two_mock_connections_preserve_ip_and_process_local_handle_identity(self):
        calls=[]
        handles={"192.168.1.19":19,"192.168.1.18":18}
        class Robot:
            def rm_get_current_arm_state(self):
                return 0,state_sample()["calls"]["state"]["raw_return"][1]
            def rm_get_current_work_frame(self):
                return 0,state_sample()["calls"]["work_before"]["raw_return"][1]
            def rm_get_current_tool_frame(self):
                return 0,state_sample()["calls"]["tool_before"]["raw_return"][1]
        def connect(ip,port):
            calls.append(("connect",ip,port))
            return NS(contents=NS(id=handles[ip]))
        def delete(handle):
            calls.append(("delete",handle.contents.id))
            return 0
        sdk=NS(rm_thread_mode_e=NS(RM_DUAL_MODE_E=1),rm_init=lambda mode:0,
               rm_create_robot_arm=connect,rm_delete_robot_arm=delete,
               rm_destroy=lambda:0,RoboticArm=Robot)
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            with patch("realman_api2_readonly.load_sdk",side_effect=AssertionError("REAL_SDK_FORBIDDEN")):
                with SDKReadOnly(Path(d),sdk=sdk) as adapter:
                    snapshots={}
                    for arm,ip in (("left","192.168.1.19"),("right","192.168.1.18")):
                        result=adapter.connect(arm,ip,8080)
                        snapshots[arm]=adapter.snapshot(arm)
                        c=snapshots[arm]["canonical"]
                        connection=c["connection"]
                        self.assertEqual(connection["arm"],arm)
                        self.assertEqual(connection["ip"],ip)
                        self.assertEqual(connection["port"],8080)
                        self.assertEqual(connection["controller_id"],"realman:%s:8080"%ip)
                        self.assertEqual(connection["sdk_handle_id"],result["handle_id"])
                        self.assertEqual(connection["sdk_handle_id"],handles[ip])
                        self.assertIn("process",connection["handle_scope"])
                        self.assertIn("not a hardware serial number",connection["handle_scope"])
                        self.assertTrue(connection["connection_verified"])
                        self.assertEqual(connection["source"]["arguments"],{"ip":ip,"port":8080})
                        self.assertEqual(connection["source"]["function"],"rm_create_robot_arm")
                        self.assertIsNone(c["ee_pose"]["reference_frame_id"])
                    adapter.connection_info["left"]["source"]["arguments"]["ip"]="changed"
                    self.assertEqual(snapshots["left"]["canonical"]["connection"]["source"]["arguments"]["ip"],
                                     "192.168.1.19")
            self.assertEqual(calls,[("connect","192.168.1.19",8080),("connect","192.168.1.18",8080),
                                   ("delete",19),("delete",18)])
            self.assertTrue(all(e["function"] in ALLOWED for e in adapter.events))

    def test_init_failure_is_logged_and_cleaned(self):
        seen=[]
        sdk=NS(rm_thread_mode_e=NS(RM_DUAL_MODE_E=1),rm_init=lambda mode:-2,
               rm_destroy=lambda:seen.append("destroy") or 0)
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            adapter=SDKReadOnly(Path(d),sdk=sdk)
            with self.assertRaises(RuntimeError): adapter.__enter__()
            self.assertEqual(adapter.events[0]["return_code"],-2)
            self.assertEqual(seen,["destroy"])
            self.assertEqual(len(list(Path(d).glob("*result.json"))),2)

class ComparisonTests(unittest.TestCase):
    def test_original_pose_reader_reused_without_constructor(self):
        raw={"state":"current_arm_state","arm_state":{"joint":[5800,20400,46000,-5000,95400,7600],
             "pose":[-331000,-19000,411000,-3100,324,-47],"err":[0]}}
        import json
        read={"raw_response":raw,"raw_text":json.dumps(raw),"received_at":time.time()}
        with patch("legacy_state_compare.read_query",return_value=read) as q:
            s=read_legacy("localhost",1)
            q.assert_called_once_with("localhost",1,"get_current_arm_state")
        for actual,expected in zip(s["joint_deg"],[5.8,20.4,46.,-5.,95.4,7.6]):
            self.assertAlmostEqual(actual,expected)
        self.assertEqual(s["ee_pose"]["xyz_m"],[-.331,-.019,.411])
        self.assertFalse(s["provenance"]["constructor_called"])
        self.assertFalse(s["provenance"]["gripper_getter_called"])
    def test_transport_refuses_non_read_payload(self):
        with patch("legacy_state_compare.read_query",side_effect=AssertionError("NO_NETWORK")):
            with self.assertRaises(ValueError): StateReadSocket("localhost",1).send(b'{"command":"movej"}\r\n')
    def test_comparison_flags_scale_error_and_drift(self):
        c=canonical_state("left",state_sample())
        leg={"joint_deg":list(c["joint_deg"]),"ee_pose":copy.deepcopy(c["ee_pose"]),"timestamp":c["timestamp"]}
        self.assertEqual(compare(c,leg,leg)["status"],"CONSISTENT")
        bad=copy.deepcopy(c);bad["ee_pose"]["xyz_m"]=[x/1000 for x in bad["ee_pose"]["xyz_m"]]
        self.assertEqual(compare(bad,leg,leg)["status"],"MISMATCH_OR_NOT_STATIC")
        after=copy.deepcopy(leg);after["joint_deg"][0]+=1
        self.assertFalse(compare(c,leg,after)["static_within_diagnostic_tolerance"])

if __name__=="__main__": unittest.main(verbosity=2)
