"""No hardware, SDK load, or network in these kinematic verifier regressions."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from io_utils import ROOT
from supervised_kinematics import verify,ALGORITHM_CALLS,SAMPLE_COUNT,STEP_M

def fixture():
    dh={"d":[.24,0,0,.21,0,.184,0,0],"a":[0,0,.256,0,0,0,0,0],
        "alpha":[0,90,0,90,-90,90,0,0],"offset":[0,90,90,0,0,0,0,0]}
    limits=[[-178.,178.],[-130.,130.],[-135.,135.],[-178.,178.],[-128.,128.],[-360.,360.]]
    ee={"xyz_m":[.3,0,.4],"rpy_rad":[0.,0.,0.],"units":{"xyz":"m","rpy":"rad"},"unit_scale_applied":1}
    state={"schema_version":"astra.realman.canonical_state.v1","arm":"left","joint_deg":[0.]*6,
        "ee_pose":ee,"source":{"kind":"realman_api2_sdk","joint_unit":"deg"},
        "raw_sdk_state":{"joint":[0.]*6,"pose":ee["xyz_m"]+ee["rpy_rad"]},
        "frame_snapshot_stable":True}
    for kind,name in (("work","World"),("tool","Arm_Tip")):
        state[kind+"_frame"]={"id":"realman:left:%s:%s"%(kind,name),"name":name,"read_status":"VERIFIED"}
        state["raw_"+kind+"_frame"]={"name":name,"pose":[0.]*6}
    return {"model_enum":0,"force_type_enum":3,"controller_dh":dh,"joint_limits_deg":limits,
            "canonical_left":state,"input_evidence":"measured.json","binding_evidence":"operator-evidence.json",
            "readbacks":{"rm_get_DH_data":{"return_code":0,"value":copy.deepcopy(dh)},
                         "rm_get_joint_min_pos":{"return_code":0,"value":[p[0] for p in limits]},
                         "rm_get_joint_max_pos":{"return_code":0,"value":[p[1] for p in limits]}}}

class FakeSDK:
    def __init__(self,data):
        self.data=copy.deepcopy(data);self.calls=[];self.fail_ik=False
        self.collide=False;self.singular=False;self.jump=False;self.bad_orientation=False
    def rm_dh_t(self,**kwargs):
        return NS(**kwargs)
    def rm_algo_init_sys_data_by_dh(self,force,dh,dof):
        assert (force,dof)==(3,6)
        self.initialized_dh={k:list(getattr(dh,k)) for k in ("d","a","alpha","offset")}
        self.calls.append("rm_algo_init_sys_data_by_dh")
    def rm_algo_get_dh(self):
        self.calls.append("rm_algo_get_dh")
        return NS(**copy.deepcopy(self.data["controller_dh"]))
    def rm_algo_forward_kinematics(self,handle,q):
        assert handle is None
        self.calls.append("rm_algo_forward_kinematics")
        # 1 degree maps to 1 cm, so fixed 10 mm path requires 1 degree.
        quat=NS(w=1.,x=0.,y=0.,z=0.)
        if self.bad_orientation and abs(q[2])>.001:
            quat=NS(w=.9999995,x=.001,y=0.,z=0.)
        return NS(position=NS(x=.3+q[0]*.01,y=q[1]*.01,z=.4+q[2]*.01),
                  euler=NS(rx=0.,ry=0.,rz=0.),quaternion=quat)
    def rm_inverse_kinematics_params_t(self,q,pose,flag):
        assert flag==0
        return NS(q_in=q,q_pose=pose)
    def rm_algo_inverse_kinematics(self,handle,params,q_out):
        assert handle is None
        self.calls.append("rm_algo_inverse_kinematics")
        if self.fail_ik: return 1
        q_out[0]=(params.q_pose[0]-.3)/.01
        q_out[1]=params.q_pose[1]/.01
        q_out[2]=(params.q_pose[2]-.4)/.01+(1 if self.jump else 0)
        return 0
    def rm_algo_safety_robot_self_collision_detection(self,q):
        self.calls.append("rm_algo_safety_robot_self_collision_detection")
        return 1 if self.collide else 0
    def rm_algo_kin_robot_singularity_analyse(self,q,distance):
        self.calls.append("rm_algo_kin_robot_singularity_analyse")
        distance._obj.value=.2
        return -1 if self.singular else 0

class KinematicTests(unittest.TestCase):
    def run_check(self,data,sdk):
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as folder:
            with patch("supervised_kinematics.load_sdk",side_effect=AssertionError("NO_REAL_SDK")):
                result=verify(data,Path(folder)/"evidence.json",sdk=sdk)
                self.assertTrue((Path(folder)/"evidence.json").is_file())
        self.assertFalse(result["execution_permitted"])
        self.assertEqual(result["hardware_connections_opened"],0)
        self.assertEqual(result["motion_commands_sent"],0)
        return result

    def test_fixed_10mm_path_201_samples_preserves_controller_pose(self):
        data=fixture();sdk=FakeSDK(data);before=copy.deepcopy(data)
        r=self.run_check(data,sdk)
        self.assertEqual(r["errors"],[])
        self.assertEqual(r["outcome"],"PASS_OFFLINE_KINEMATICS")
        self.assertEqual(len(r["path"]["sampled_joint_deg"]),SAMPLE_COUNT)
        self.assertEqual(r["path"]["sampled_joint_deg"][0],data["canonical_left"]["joint_deg"])
        self.assertEqual(r["path"]["start_pose"],{"xyz_m":[.3,0,.4],"rpy_rad":[0.,0.,0.]})
        self.assertAlmostEqual(r["path"]["target_pose"]["xyz_m"][2],.4+STEP_M)
        self.assertEqual(data,before)
        self.assertEqual(r["initialization_source"],"measured_controller_DH")
        self.assertEqual(sdk.initialized_dh,data["controller_dh"])
        self.assertFalse(r["sdk"]["algorithm_initialization"]["parameter_fitting_performed"])
        self.assertEqual(sdk.calls.count("rm_algo_inverse_kinematics"),SAMPLE_COUNT-1)
        self.assertTrue(set(sdk.calls).issubset(ALGORITHM_CALLS))
        for flag in ("kinematics_passed","orientation_preserved","native_self_collision_checks_passed"):
            self.assertTrue(r["path"][flag])

    def test_algorithm_dh_mismatch_rejects_without_fitting_or_setters(self):
        data=fixture();sdk=FakeSDK(data);sdk.data["controller_dh"]["d"][5]=.144
        r=self.run_check(data,sdk)
        self.assertEqual(r["errors"],["ALGORITHM_CONTROLLER_DH_MISMATCH"])
        self.assertEqual(sdk.calls,["rm_algo_init_sys_data_by_dh","rm_algo_get_dh"])

    def test_initial_fk_mismatch_is_rejected(self):
        data=fixture()
        data["canonical_left"]["ee_pose"]["xyz_m"][0]+=.001
        data["canonical_left"]["raw_sdk_state"]["pose"][0]+=.001
        r=self.run_check(data,FakeSDK(data))
        self.assertEqual(r["errors"],["START_FK_POSITION_MISMATCH"])

    def test_ik_collision_singularity_and_discontinuity_fail_closed(self):
        for attribute,error in (("fail_ik","IK_FAILED"),("collide","SELF_COLLISION"),
                                ("singular","SINGULARITY"),("jump","JOINT_DISCONTINUITY"),
                                ("bad_orientation","ORIENTATION_RESIDUAL")):
            with self.subTest(attribute=attribute):
                data=fixture();sdk=FakeSDK(data);setattr(sdk,attribute,True)
                r=self.run_check(data,sdk)
                self.assertEqual(r["outcome"],"REJECT")
                self.assertTrue(r["errors"][0].startswith(error),r["errors"])
                for flag in ("kinematics_passed","orientation_preserved","native_self_collision_checks_passed"):
                    self.assertFalse(r["path"][flag])

    def test_actual_controller_limit_rejects_even_if_algorithm_accepts(self):
        data=fixture();data["joint_limits_deg"][2][1]=.1
        data["readbacks"]["rm_get_joint_max_pos"]["value"][2]=.1
        r=self.run_check(data,FakeSDK(data))
        self.assertTrue(r["errors"][0].startswith("ACTUAL_JOINT_LIMIT"))

    def test_failed_measured_readback_does_not_load_algorithm(self):
        data=fixture();data["readbacks"]["rm_get_DH_data"]["return_code"]=-2
        sdk=FakeSDK(data);r=self.run_check(data,sdk)
        self.assertTrue(r["errors"][0].startswith("MEASURED_READBACK_FAILED"))
        self.assertEqual(sdk.calls,[])

    def test_malformed_nonfinite_or_wrong_unit_input_rejected(self):
        for mutate in (lambda d:d.update(force_type_enum=0),
                       lambda d:d["canonical_left"]["ee_pose"].update(unit_scale_applied=.001),
                       lambda d:d["controller_dh"]["d"].__setitem__(0,float("nan"))):
            data=fixture();mutate(data);sdk=FakeSDK(data)
            r=self.run_check(data,sdk)
            self.assertEqual(r["outcome"],"REJECT")
            self.assertEqual(sdk.calls,[])

if __name__=="__main__":unittest.main(verbosity=2)
