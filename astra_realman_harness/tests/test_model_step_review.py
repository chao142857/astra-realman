import copy
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from model_step_review import review_proposal, FRAME_FINGERPRINTS, EVIDENCE_LOG, WORK_ID, TOOL_ID

def fixture():
    states = {}
    for arm, ip in (("left", "192.168.1.19"), ("right", "192.168.1.18")):
        xyz, rpy, joints = [-.356, .073, .353], [-3.043, .214, .076], [0., 20., 30., 0., 90., 0.]
        s = {"arm":arm, "joint_deg":joints, "ee_pose":{"xyz_m":xyz,"rpy_rad":rpy,
             "units":{"xyz":"m","rpy":"rad"},"unit_scale_applied":1,"frame_semantics_status":"UNKNOWN"},
             "source":{"joint_unit":"deg"},"system_error":{"codes":[0],"has_error":False},
             "raw_sdk_state":{"joint":joints[:],"pose":xyz+rpy},"timestamp":100.1,
             "connection":{"arm":arm,"ip":ip,"port":8080,"sdk_handle_id":1,"connection_verified":True},
             "frame_snapshot_stable":True}
        for kind, name in (("work","World"),("tool","Arm_Tip")):
            key=kind+"_frame"
            s[key]={"id":f"realman:{arm}:{kind}:{name}","name":name,"read_status":"VERIFIED",
                    "pose":{"xyz_m":[0,0,0],"rpy_rad":[0,0,0],"units":{"xyz":"m","rpy":"rad"}},
                    "definition_fingerprint":FRAME_FINGERPRINTS[key]}
            s["raw_"+key]={"name":name,"pose":[0]*6}
        states[arm]=s
    o={"canonical_states":states,"capture_started_at":100.,"capture_finished_at":100.3,"captured_at":100.1,
       "cameras":[{"serial":str(i),"image_path":f"/tmp/{i}.png","captured_at":100.2} for i in range(4)],
       "capture_failures":[],"capture_span_ms":0.,
       "camera_capture":{"expected_serials":[str(i) for i in range(4)],"timestamp_semantics_confirmed":True},
       "decision_safety_context":{"relative_work_motion":{"status":"VERIFIED_BY_REAL_SINGLE_STEP","source":EVIDENCE_LOG+"/summary.json",
        "arm":"left","work_frame_id":WORK_ID,"tool_frame_id":TOOL_ID,
        "work_frame":copy.deepcopy(states["left"]["work_frame"]),
        "tool_frame":copy.deepcopy(states["left"]["tool_frame"])}}}
    a={"action_type":"cartesian_delta","arm":"left","frame":WORK_ID,"tool_frame":TOOL_ID,
       "translation_m":[.003,0,0],"rotation_rpy_rad":[0,0,0],"gripper":"hold","done":False}
    return a,o

class ReviewTests(unittest.TestCase):
    def assess(self,a,o):
        return review_proposal(a,o,now=145,generated_at=144)
    def test_valid_pending_no_execution_and_target(self):
        a,o=fixture(); r=self.assess(a,o)
        self.assertEqual(r["status"],"AWAITING_EXECUTE")
        self.assertFalse(r["execution_permitted"]); self.assertEqual(r["motion_commands_sent"],0)
        self.assertAlmostEqual(r["target_pose"]["xyz_m"][0],-.353)
        self.assertEqual(next(g for g in r["gates"] if g["gate"]=="local_workspace")["status"],
                         "PENDING_OPERATOR_CONFIRMATION")
    def test_noop_is_pass_without_unknown_geometry_block(self):
        a,o=fixture(); a["translation_m"]=[0,0,0]
        self.assertEqual(self.assess(a,o)["status"],"PASS_NOOP")
    def test_native_unknown_generic_semantics_does_not_block_relative_evidence(self):
        a,o=fixture(); self.assertEqual(self.assess(a,o)["errors"],[])
    def test_model_latency_45_seconds_allowed_for_review_only(self):
        a,o=fixture(); self.assertTrue(self.assess(a,o)["fresh_state_required_before_execution"])
        self.assertEqual(self.assess(a,o)["status"],"AWAITING_EXECUTE")
    def test_too_old_and_future_capture_reject(self):
        a,o=fixture()
        self.assertEqual(review_proposal(a,o,281,280)["status"],"REJECT")
        self.assertEqual(review_proposal(a,o,99,99)["status"],"REJECT")
    def test_invalid_actions_reject(self):
        for key,value in (("translation_m",[.0030001,0,0]),("translation_m",[float("nan"),0,0]),
                          ("rotation_rpy_rad",[0,0,.001]),("gripper","close"),("arm","right"),
                          ("frame","realman:left:work:Other"),("tool_frame","realman:left:tool:Other")):
            with self.subTest(key=key,value=value):
                a,o=fixture(); a[key]=value; self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_action_list_rejects(self):
        a,o=fixture(); self.assertEqual(self.assess([a],o)["status"],"REJECT")
    def test_fault_either_arm_rejects_even_noop(self):
        for arm in ("left","right"):
            a,o=fixture(); a["translation_m"]=[0,0,0]
            o["canonical_states"][arm]["system_error"]={"codes":[4105],"has_error":True}
            self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_bad_native_units_rejects(self):
        a,o=fixture(); o["canonical_states"]["left"]["ee_pose"]["unit_scale_applied"]=.001
        self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_canonical_raw_mismatch_rejects(self):
        a,o=fixture(); o["canonical_states"]["left"]["raw_sdk_state"]["pose"][0]+=.001
        self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_changed_frame_or_tool_rejects(self):
        for kind in ("work","tool"):
            a,o=fixture(); o["canonical_states"]["left"][kind+"_frame"]["pose"]["xyz_m"][2]=.001
            self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_raw_frame_name_mismatch_rejects(self):
        a,o=fixture(); o["canonical_states"]["left"]["raw_work_frame"]["name"]="New"
        self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_lost_or_changed_relative_verification_rejects(self):
        a,o=fixture(); o["decision_safety_context"]["relative_work_motion"]["status"]="UNKNOWN"
        self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_teach_frame_requires_fresh_recheck_upon_execute(self):
        a,o=fixture(); r=self.assess(a,o)
        gate=next(g for g in r["gates"] if g["gate"]=="current_teach_frame_is_work")
        self.assertEqual(gate["status"],"PENDING_FRESH_RECHECK")
        self.assertFalse(r["execution_permitted"])
    def test_capture_missing_or_failure_rejects(self):
        a,o=fixture(); o["cameras"].pop(); self.assertEqual(self.assess(a,o)["status"],"REJECT")
        a,o=fixture(); o["capture_failures"]=["missing"]; self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_bad_timestamp_record_rejects(self):
        a,o=fixture(); o["capture_span_ms"]=100
        self.assertEqual(self.assess(a,o)["status"],"REJECT")
    def test_input_not_mutated(self):
        a,o=fixture(); before=copy.deepcopy((a,o)); self.assess(a,o); self.assertEqual((a,o),before)

if __name__=="__main__":
    unittest.main()
