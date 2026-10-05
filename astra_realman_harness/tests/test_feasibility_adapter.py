import copy,math,sys,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from feasibility_adapter import FeasibilityAdapter,FeasibilityError,scaled_action,SCALES

def action():return {"action_type":"cartesian_delta","arm":"left","frame":"realman:left:work:World","tool_frame":"realman:left:tool:Arm_Tip","translation_m":[1.,.2,-.3],"rotation_rpy_rad":[0,0,.8],"gripper":"hold","done":False}
STATE={"joint_deg":[1,2,3,4,5,6],"ee_pose":{"xyz_m":[0,0,0],"rpy_rad":[0,0,0]}}
class AdapterTests(unittest.TestCase):
    def adapter(self,solve):
        calls=[]
        class Robot:
            def rm_algo_inverse_kinematics(self,params):calls.append(params);return solve(params)
        sdk=types.SimpleNamespace(rm_inverse_kinematics_params_t=lambda **kw:kw)
        return FeasibilityAdapter(sdk,Robot()),calls
    def test_original_feasible_unchanged_single_ik(self):
        adapter,calls=self.adapter(lambda p:(0,[1]*6));a=action();r=adapter.project(a,STATE)
        self.assertEqual(r['selected_action'],a);self.assertEqual(r['selected_scale'],1);self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['q_in'],STATE['joint_deg']);self.assertEqual(calls[0]['flag'],1)
    def test_bracket_selects_largest_tested_without_changing_direction(self):
        adapter,calls=self.adapter(lambda p:((0 if p['q_pose'][0]<=.63 else 1),[1]*6))
        a=action();saved=copy.deepcopy(a);r=adapter.project(a,STATE)
        self.assertEqual(a,saved);self.assertLessEqual(r['selected_scale'],.63);self.assertGreater(r['selected_scale'],.625)
        for x,y in zip(r['selected_action']['translation_m'],a['translation_m']):self.assertAlmostEqual(x,y*r['selected_scale'])
        self.assertAlmostEqual(r['selected_action']['rotation_rpy_rad'][2],.8*r['selected_scale'])
    def test_unreachable_has_no_selected_command(self):
        adapter,calls=self.adapter(lambda p:(1,[0]*6));r=adapter.project(action(),STATE)
        self.assertEqual(r['status'],'INFEASIBLE');self.assertIsNone(r['selected_action']);self.assertEqual(len(calls),len(SCALES))
    def test_api_error_not_treated_as_infeasible(self):
        for code in [-1,-2,5]:
            adapter,calls=self.adapter(lambda p:(code,[0]*6))
            with self.assertRaises(FeasibilityError):adapter.project(action(),STATE)
            self.assertEqual(len(calls),1)
    def test_invalid_success_result_stops(self):
        adapter,calls=self.adapter(lambda p:(0,[float('nan')]*6))
        with self.assertRaises(FeasibilityError):adapter.project(action(),STATE)
    def test_stop_blocks_ik(self):
        adapter,calls=self.adapter(lambda p:(0,[0]*6))
        with self.assertRaises(FeasibilityError):adapter.project(action(),STATE,stopping=lambda:True)
        self.assertEqual(calls,[])
    def test_wrong_arm_or_frame_rejected(self):
        for key,value in [('arm','right'),('frame','camera'),('gripper','close')]:
            adapter,calls=self.adapter(lambda p:(0,[0]*6));a=action();a[key]=value
            with self.assertRaises(FeasibilityError):adapter.project(a,STATE)
            self.assertEqual(calls,[])
    def test_rotation_only_scales_without_translation_limit(self):
        a=action();a['translation_m']=[0,0,0];a['rotation_rpy_rad']=[0,0,1.8]
        self.assertAlmostEqual(scaled_action(a,.5)['rotation_rpy_rad'][2],.9)
if __name__=='__main__':unittest.main()
