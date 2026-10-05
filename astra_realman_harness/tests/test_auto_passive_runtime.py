"""Offline loop regression tests; SDK/cameras/model are fully replaced before import."""
import contextlib, io, json, runpy, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from execution_telemetry import pose_telemetry
from pick_task import pose_preview

class PassiveRuntimeTests(unittest.TestCase):
    def run_loop(self, actions, *, command_return=0, robot_error=0, resume=False, ik_return=0, gripper_ok=True, state_error_after_motion=0, initial_pose=None):
        with tempfile.TemporaryDirectory(prefix="offline-runtime-",dir=ROOT/"logs") as tmp:
            root=Path(tmp);(root/"logs").mkdir();calls=[];grips=[];self.events=[]
            events=self.events
            def new_run(path):path.mkdir(parents=True,exist_ok=False);return path
            def write_json(path,value):path.write_text(json.dumps(value))
            def read_json(path):
                if path.exists():return json.loads(path.read_text())
                if path.name=="lab.json":return {"devices":{"cameras":[]},"frames":{}}
                if path.name=="decision_backend.json":return {}
                if path.name=="pick_simulation_scale.json":return json.loads((ROOT/"config/pick_simulation_scale.json").read_text())
                return {"status":"EXECUTED"}
            gripper={"sys_state":0,"dof_err":[0],"pos":[1000],"speed":[0],"force":[0]}
            class Robot:
                def rm_get_rm_plus_state_info(self):return (0,gripper.copy())
                def rm_get_teach_frame(self):return (0,0)
                def rm_algo_inverse_kinematics(self,params):raise AssertionError("IK MUST NEVER BE CALLED")
                def rm_set_pos_step(self,*args):raise AssertionError("OLD CARTESIAN STEP EXECUTOR FORBIDDEN")
                def rm_movel(self,*args):raise AssertionError("OLD STRAIGHT-LINE EXECUTOR FORBIDDEN")
                def rm_movej_p(self,*args):calls.append(args);events.append("arm");return command_return
            class SDK:
                def __init__(self,*args):
                    self.connected={"left":Robot(),"right":Robot()}
                    self.sdk=types.SimpleNamespace(rm_inverse_kinematics_params_t=lambda **kw:kw)
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def connect(self,*args):return {"connected":True}
                def snapshot(self,arm):
                    code=state_error_after_motion if calls and state_error_after_motion else robot_error
                    return {"canonical":{"timestamp":time.time(),"joint_deg":[0]*6,"system_error":{"codes":[code],"has_error":bool(code)},"ee_pose":initial_pose or {"xyz_m":[0,0,0],"rpy_rad":[0,0,0]}}}
            class Cameras:
                def __init__(self,*args):pass
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def snapshot(self,path):return ([{"captured_at":time.time()} for _ in range(4)],[],{"capture_span_ms":0})
            queue=list(actions)
            class Backend:
                def __init__(self,*args,**kwargs):pass
                def decide(self,observation,path):
                    events.append("inference")
                    a=queue.pop(0);(path/"last_message.json").write_text(json.dumps(a))
                    return types.SimpleNamespace(proposal=a,metadata={"inference_latency_s":0})
            class Gripper:
                def __init__(self):self.last_result=None
                def set_gripper(self,arm,mode):
                    grips.append((arm,mode));events.append("gripper");self.last_result={"command_return":{"command":"hand_follow_pos","set_state":gripper_ok}};return self.last_result
                def close(self):pass
            def review(a,obs,**kwargs):
                return {"errors":[],"action":a,"target_pose":pose_preview(obs["canonical_states"]["left"]["ee_pose"],a)}
            def module(name,**items):m=types.ModuleType(name);m.__dict__.update(items);return m
            mocks={"io_utils":module("io_utils",ROOT=root,read_json=read_json,write_json=write_json,new_run=new_run),
                "realman_api2_readonly":module("realman_api2_readonly",SDKReadOnly=SDK),
                "camera_session":module("camera_session",CameraSession=Cameras),
                "lab_gripper_adapter":module("lab_gripper_adapter",LabGripperAdapter=Gripper),
                "pick_task":module("pick_task",TASK="Use the left arm to pick up the tennis ball.",PickBackend=Backend,review_pick=review)}
            argv=["run_auto_pick.py"]
            if resume:
                prior=new_run(root/"logs/prior-step-06")
                write_json(prior/"summary.json",{"step":6,"status":"STOPPED","executed_command":{"return":1},"parsed_action":action(.018),"stop_reason":"ARM_COMMAND_RETURN:1"})
                write_json(prior/"dispatch.claim.json",{})
                argv += ["--continue-after-step",str(prior)]
            with patch.dict(sys.modules,mocks),patch.object(sys,"argv",argv),patch("time.sleep"),patch("signal.signal"),contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(ROOT/"scripts/run_auto_pick.py"),run_name="__main__")
            run=next((root/"logs").glob("auto-pick-*"))
            summary=read_json(run/"summary.json")
            steps=[read_json(p) for p in sorted(run.glob("step-*/summary.json"))]
            return summary,steps,calls,grips
    def test_large_tracking_residual_does_not_stop(self):
        summary,steps,calls,_=self.run_loop([action(.04),action(done=True)])
        self.assertEqual(summary["stop_reason"],"MODEL_DONE")
        self.assertEqual(steps[0]["status"],"EXECUTED")
        self.assertEqual(steps[0]["pose_telemetry"]["translation_residual_m"],[-.04,0,0])
        self.assertEqual(len(calls),1)
    def test_three_noops_do_not_stop(self):
        summary,steps,calls,_=self.run_loop([action() for _ in range(4)]+[action(done=True)])
        self.assertEqual(summary["stop_reason"],"MODEL_DONE");self.assertEqual(len(steps),5);self.assertEqual(calls,[])
    def test_failed_grasp_outcome_does_not_stop(self):
        summary,steps,_,grips=self.run_loop([action(gripper="close"),action(done=True)])
        self.assertEqual(summary["stop_reason"],"MODEL_DONE");self.assertEqual(grips,[("left","close")])
        self.assertEqual(steps[0]["gripper_after"]["position"],1000)
    def test_failed_command_stops_without_retry(self):
        summary,steps,calls,_=self.run_loop([action(.04),action(.04)],command_return=1)
        self.assertEqual(summary["stop_reason"],"ARM_COMMAND_RETURN:1");self.assertEqual(len(calls),1)
        self.assertIsNotNone(steps[0]["after_pose"])
    def test_nonzero_robot_error_prevents_dispatch(self):
        summary,steps,calls,_=self.run_loop([action(.04)],robot_error=4099)
        self.assertTrue(summary["stop_reason"].startswith("ROBOT_ERROR:"));self.assertEqual(calls,[])
    def test_continue_does_not_replay_failed_step(self):
        summary,steps,calls,_=self.run_loop([action(done=True)],resume=True)
        self.assertEqual(summary["start_step"],7);self.assertEqual(steps[0]["step"],7);self.assertEqual(calls,[])
    def test_raw_large_action_executes_without_ik_or_projection(self):
        a=action(.2)
        summary,steps,calls,_=self.run_loop([a,action(done=True)],ik_return=1)
        self.assertEqual(summary["stop_reason"],"MODEL_DONE")
        self.assertEqual(steps[0]["parsed_action"],a)
        self.assertEqual(calls[0],([.2,0,0,0,0,0],1,0,0,1))
        self.assertNotIn("feasibility",steps[0])
    def test_multiaxis_values_reach_sdk_unchanged(self):
        a=action();a.update(translation_m=[-.14,.065,-.087],rotation_rpy_rad=[.3,-.2,.1])
        _,steps,calls,_=self.run_loop([a,action(done=True)])
        self.assertEqual(steps[0]["parsed_action"],a)
        self.assertEqual(calls[0][0],a["translation_m"]+a["rotation_rpy_rad"])
    def test_already_open_gripper_target_is_satisfied_without_send(self):
        _,steps,calls,grips=self.run_loop([action(gripper="open"),action(done=True)])
        self.assertEqual(grips,[]);self.assertEqual(steps[0]["status"],"NOOP")
        self.assertEqual(steps[0]["actuator_channels"]["gripper"]["status"],"ALREADY_SATISFIED")
    def test_normalized_gripper_proposal_keeps_original_precision(self):
        a=action(gripper=.3509)
        _,steps,_,grips=self.run_loop([a,action(done=True)])
        self.assertEqual(grips,[("left",.3509)])
        self.assertEqual(steps[0]["parsed_action"],a)
    def test_combined_open_satisfied_still_executes_original_motion(self):
        a=action(gripper="open");a["translation_m"]=[-.06,-.01,-.04]
        _,steps,calls,grips=self.run_loop([a,action(done=True)])
        self.assertEqual(calls[0][0][:3],[-.06,-.01,-.04]);self.assertEqual(grips,[])
        self.assertEqual(steps[0]["parsed_action"],a);self.assertEqual(steps[0]["status"],"EXECUTED")
    def test_combined_unmet_target_both_channels_one_inference(self):
        a=action(.06,gripper="close")
        _,steps,calls,grips=self.run_loop([a,action(done=True)])
        self.assertEqual(self.events,["inference","arm","gripper","inference"])
        self.assertEqual(calls,[([.06,0,0,0,0,0],1,0,0,1)]);self.assertEqual(grips,[("left","close")])
        self.assertEqual(steps[0]["arm_command_attempts"],1);self.assertEqual(steps[0]["gripper_command_attempts"],1)
    def test_arm_failure_prevents_second_channel_and_retry(self):
        summary,steps,calls,grips=self.run_loop([action(.06,gripper="close")],command_return=1)
        self.assertEqual(summary["stop_reason"],"ARM_COMMAND_RETURN:1");self.assertEqual(len(calls),1);self.assertEqual(grips,[])
    def test_gripper_failure_preserves_arm_result_without_retry(self):
        summary,steps,calls,grips=self.run_loop([action(.06,gripper="close")],gripper_ok=False)
        self.assertEqual(summary["stop_reason"],"GRIPPER_COMMAND_RETURN")
        self.assertEqual(steps[0]["executed_command"]["arm"]["return"],0)
        self.assertEqual(len(calls),1);self.assertEqual(len(grips),1)
    def test_error_after_arm_stops_before_gripper(self):
        summary,steps,calls,grips=self.run_loop([action(.06,gripper="close")],state_error_after_motion=4099)
        self.assertTrue(summary["stop_reason"].startswith("ROBOT_ERROR:"));self.assertEqual(len(calls),1);self.assertEqual(grips,[])
    def test_nonzero_pose_uses_exact_componentwise_target_movej_p(self):
        a=action();a.update(translation_m=[-.06,-.01,-.04],rotation_rpy_rad=[.3,-.2,.4])
        current={"xyz_m":[-.4,.03,.31],"rpy_rad":[3.1,.2,-.8]}
        _,steps,calls,_=self.run_loop([a,action(done=True)],initial_pose=current)
        target=[x+y for x,y in zip(current["xyz_m"],a["translation_m"])]+[x+y for x,y in zip(current["rpy_rad"],a["rotation_rpy_rad"])]
        self.assertEqual(calls[0],(target,1,0,0,1));self.assertGreater(calls[0][0][3],3.14159)
        self.assertEqual(steps[0]["executed_command"]["arm"]["request"]["function"],"rm_movej_p")
        self.assertEqual(steps[0]["parsed_action"],a)
    def test_maximum_50_steps_still_stops(self):
        summary,steps,calls,_=self.run_loop([action() for _ in range(50)])
        self.assertEqual(summary["stop_reason"],"MAX_50_STEPS");self.assertEqual(len(steps),50)
    def test_telemetry_has_no_acceptance_verdict(self):
        before={"xyz_m":[0,0,0],"rpy_rad":[0,0,0]}
        actual={"xyz_m":[-.04,0,0],"rpy_rad":[1,0,0]}
        result=pose_telemetry(before,before,actual)
        self.assertNotIn("errors",result);self.assertNotIn("status",result);self.assertTrue(result["passive_only"])

def action(dx=0,gripper="hold",done=False):
    return {"action_type":"cartesian_delta","arm":"left","frame":"realman:left:work:World","tool_frame":"realman:left:tool:Arm_Tip","translation_m":[dx,0,0],"rotation_rpy_rad":[0,0,0],"gripper":gripper,"done":done}

if __name__=="__main__":unittest.main()
