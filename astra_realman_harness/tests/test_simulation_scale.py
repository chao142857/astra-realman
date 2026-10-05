"""Offline parser, frame, range, gripper transport, and prompt regression tests."""
import json,math,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pick_task import parse_pick,pose_preview
from lab_gripper_adapter import LabGripperAdapter,_ObservedSocket
PROFILE={"translation_limit_m":None,"rotation_limit_rad":None,"translation_norm_limit_m":None}
def action():return {"action_type":"cartesian_delta","arm":"left","frame":"realman:left:work:World","tool_frame":"realman:left:tool:Arm_Tip","translation_m":[.2,-.1,.08],"rotation_rpy_rad":[.4,0,0],"gripper":"hold","done":False}
class SimulationScaleTests(unittest.TestCase):
    def test_simulation_scale_accepts_large_finite_translation_and_rotation(self):
        a=action();self.assertEqual(parse_pick(json.dumps(a),**PROFILE),a)
    def test_old_bounded_profile_still_rejects_large_action(self):
        with self.assertRaises(ValueError):parse_pick(json.dumps(action()))
    def test_invalid_actions_reject(self):
        for key,value in [("arm","right"),("frame","world"),("tool_frame","pad_center"),("translation_m",[float("nan"),0,0]),("rotation_rpy_rad",[float("inf"),0,0])]:
            a=action();a[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):parse_pick(json.dumps(a),**PROFILE)
    def test_normalized_gripper_range_and_combined_action(self):
        for value in [0,.35,1]:
            a=action();a.update(translation_m=[0,0,0],rotation_rpy_rad=[0,0,0],gripper=value)
            self.assertEqual(parse_pick(json.dumps(a),**PROFILE)["gripper"],value)
        for value in [-.1,1.1,True]:
            a.update(gripper=value)
            with self.assertRaises(ValueError):parse_pick(json.dumps(a),**PROFILE)
        a=action();a['gripper']=.5
        self.assertEqual(parse_pick(json.dumps(a),**PROFILE),a)
    def test_pose_preview_units_and_rotation(self):
        a=action();p=pose_preview({"xyz_m":[.1,.2,.3],"rpy_rad":[0,0,0]},a)
        for got,want in zip(p["xyz_m"],[.3,.1,.38]):self.assertAlmostEqual(got,want)
        self.assertAlmostEqual(p["rpy_rad"][0],.4)
    def test_normalized_gripper_original_function_once(self):
        class Sock:
            def send(self,data):return len(data)
            def recv(self,size):return b'{"command":"hand_follow_pos","set_state":true}'
            def close(self):pass
        class Driver:
            def set_gripper_position(self,opening):
                calls.append(opening)
                self.arm.send(json.dumps({"command":"hand_follow_pos","hand_pos":[int(opening*1000)]}).encode());self.arm.recv(1024)
        calls=[];adapter=LabGripperAdapter.__new__(LabGripperAdapter)
        adapter.driver=Driver();adapter.transport=_ObservedSocket(Sock());adapter.driver.arm=adapter.transport
        adapter.consumed=False;adapter.last_result=None
        r=adapter.set_gripper("left",.3509)
        self.assertEqual(calls,[.3509]);self.assertEqual(r['existing_argument'],.3509);self.assertEqual(r['target'],350)
        with self.assertRaises(RuntimeError):adapter.set_gripper("left",.35)
if __name__=="__main__":unittest.main()
