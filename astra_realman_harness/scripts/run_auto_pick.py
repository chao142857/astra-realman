#!/usr/bin/env python3
"""Bounded autonomous interaction loop; tracking telemetry never gates execution."""
import argparse,copy,fcntl,json,math,os,signal,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json,write_json,new_run
from realman_api2_readonly import SDKReadOnly
from camera_session import CameraSession
from lab_gripper_adapter import LabGripperAdapter
from pick_task import TASK,PickBackend,review_pick
from execution_telemetry import pose_telemetry

ACTION_CONFIG=read_json(ROOT/"config/pick_simulation_scale.json")
LIMITS={"translation_limit_m":ACTION_CONFIG["translation_axis_limit_m"],
        "translation_norm_limit_m":ACTION_CONFIG["translation_norm_limit_m"],
        "rotation_limit_rad":ACTION_CONFIG["rotation_axis_limit_rad"]}
SCHEMA=ROOT/"schema/pick_simulation_scale.schema.json"

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    parser.add_argument("--initial-state-evidence",type=Path,help="Completed joint return evidence for a new experiment.")
    group.add_argument("--resume-step",type=Path)
    group.add_argument("--continue-after-step",type=Path,help="Continue after an already attempted step; never replay it. Fresh healthy state is mandatory.")
    args=parser.parse_args()
    resume=None
    resume_source=args.resume_step or args.continue_after_step
    if resume_source:
        source=resume_source.resolve()
        if ROOT/"logs" not in source.parents:
            raise ValueError("RESUME_OUTSIDE_LOGS")
        resume=read_json(source/"summary.json")
        if args.continue_after_step:
            if resume.get("status")!="STOPPED" or not (source/"dispatch.claim.json").exists() or not resume.get("executed_command"):
                raise ValueError("CONTINUATION_REQUIRES_RECORDED_ATTEMPT")
        elif resume.get("status") not in ("EXECUTED_VERIFIED","EXECUTED","NOOP"):
            raise ValueError("RESUME_STEP_NOT_VERIFIED")
    start_index=resume["step"]+1 if resume else 1
    run=new_run(ROOT/"logs"/("auto-pick-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-"+uuid.uuid4().hex[:8]))
    stop=run/"STOP"
    interrupted=[False]
    def on_interrupt(*_):interrupted[0]=True
    signal.signal(signal.SIGINT,on_interrupt);signal.signal(signal.SIGTERM,on_interrupt)
    lock=(ROOT/"logs/auto-pick.lock").open("a+")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    summary={"run":str(run),"task":TASK,"status":"RUNNING","steps":0,"arm_command_attempts":0,
             "gripper_command_attempts":0,"stable_pick_verified":False,"no_automatic_motion_retries":True,
             "start_step":start_index,"resume_step":str(resume_source) if resume_source else None}
    step_result=None
    current=None
    def stopping():return interrupted[0] or stop.exists()
    def claim(step,command):
        if stopping():raise RuntimeError("HUMAN_STOP")
        with (step/"dispatch.claim.json").open("x") as f:
            json.dump({"command":command,"authorization":"User authorized autonomous bounded left pick",
                       "timestamp":time.time(),"retry_allowed":False},f)
            f.flush();os.fsync(f.fileno())
        fd=os.open(str(step),os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    config=read_json(ROOT/"config/lab.json")
    workspace={
        "status":"ONE_RUN_OPERATOR_CLEARANCE",
        "arm":"left","frame_id":"realman:left:work:World",
        "scope":"current left-arm work area and local region between gripper and tennis ball",
        "user_confirmation":"左臂当前工作区域、夹爪到网球之间的局部区域无人员、无障碍物，可用于本次低速小步抓取测试。",
        "supervision":"operator continuously beside emergency stop/power-off",
        "controller_limits":"controller existing joint/workspace limits; no configuration changes",
        "bounded_to_run":str(run),
        "geometric_bounds_fabricated":False,
    }
    write_json(run/"policy.json",{"action_profile":ACTION_CONFIG,"max_translation_axis_m":None,"max_translation_norm_m":None,"max_rotation_axis_rad":None,
        "proposals_per_observation":1,"max_commands_per_actuator_channel":1,"channel_order":"arm_then_gripper",
        "workspace":workspace,"max_observation_age_s":ACTION_CONFIG["max_observation_age_s"],"max_steps":50,"noop_stop_count":None,
        "gripper_backend":"existing RealMan_Control.RmArm.set_gripper_position","right_motion_allowed":False,
        "operator_execute_required":False,
        "tracking_telemetry_only":True,
        "action_passthrough":True,"ik_projection":False,"automatic_recovery":False,
        "task_decision_source":"Astra only",
        "grasp_outcome_telemetry_only":True,
        "commanded_axis_direction_check":False})
    write_json(run/"control.json",{"stop_file":str(stop),"run":str(run)})
    try:
        with CameraSession(config["devices"]["cameras"]) as cameras, SDKReadOnly(new_run(run/"sdk")) as session:
            for arm,ip in (("left","192.168.1.19"),("right","192.168.1.18")):
                if not session.connect(arm,ip,8080)["connected"]:raise RuntimeError("STATE_CONNECTION_FAILED:"+arm)
            def states_at(path):
                values={}
                for arm in ("right","left"):
                    values[arm]=session.snapshot(arm)["canonical"]
                    if not values[arm]:raise RuntimeError("CANONICAL_FAILED:"+arm)
                raw=session.connected["left"].rm_get_rm_plus_state_info()
                write_json(path,{"arms":values,"left_gripper_raw_return":raw,"timestamp":time.time()})
                for arm,state in values.items():
                    if state["system_error"]["has_error"]:raise RuntimeError("ROBOT_ERROR:"+arm+":"+str(state["system_error"]["codes"]))
                if raw[0]!=0:raise RuntimeError("GRIPPER_READ_FAILED:"+str(raw[0]))
                g=raw[1]
                if g["sys_state"]!=0 or g["dof_err"][0]!=0:raise RuntimeError("GRIPPER_ERROR")
                values["left"]["gripper_state"]={"position":g["pos"][0],"position_range":[0,1000],
                    "open_position":1000,"closed_position":0,"raw":g,"manufacturer":"ZX","dof":1}
                return values
            def capture(path,history):
                new_run(path)
                started=time.time()
                images,failures,metrics=cameras.snapshot(path)
                states=states_at(path/"state-readback.json")
                stamps=[s["timestamp"] for s in states.values()]+[i["captured_at"] for i in images]
                obs={"schema_version":"astra.decision.observation.v1","observation_id":"pick-"+uuid.uuid4().hex,
                     "task":TASK,"canonical_states":states,"cameras":images,"camera_capture":metrics,
                     "capture_span_ms":metrics["capture_span_ms"],"capture_failures":failures,
                     "capture_started_at":started,"capture_finished_at":time.time(),"captured_at":min(stamps),
                     "frames":config["frames"],"allowed_proposal_arms":["left"],"previous":history}
                write_json(path/"observation.json",obs)
                if failures or len(images)!=4:raise RuntimeError("CAMERA_CAPTURE_FAILED")
                if metrics["capture_span_ms"]>1000:raise RuntimeError("CAMERA_CAPTURE_SPAN")
                return obs
            def workspace_errors(review):
                # This experiment uses direct operator clearance plus controller enforcement.
                # No inferred or fabricated workspace box; existing controller limits unchanged.
                if (workspace["bounded_to_run"]!=str(run) or
                    review["target_pose"]["frame"]!=workspace["frame_id"] or
                    review["action"]["arm"]!="left"):
                    return ["OPERATOR_CLEARANCE_SCOPE_MISMATCH"]
                return []
            backend=PickBackend(read_json(ROOT/"config/decision_backend.json"),
                **LIMITS,schema=SCHEMA,automatic=True)
            if resume:
                history={"last_action":resume["parsed_action"],
                    "last_result":{"status":resume["status"],"command":resume.get("executed_command"),
                                   "actual_xyz_delta_m":resume.get("actual_xyz_delta_m"),
                                   "after_pose":resume.get("after_pose"),"gripper_after":resume.get("gripper_after"),
                                   "robot_errors":resume.get("robot_errors"),"stop_reason":resume.get("stop_reason")}}
                write_json(run/"resume.json",{"source":str(resume_source),"previous_step":resume["step"],
                    "next_step":start_index,"replay_previous_action":False})
            else:
                history=None
                if args.initial_state_evidence:
                    evidence=read_json(args.initial_state_evidence)
                    if evidence.get("status")!="RETURNED" or evidence.get("command_return")!=0:
                        raise RuntimeError("INITIAL_RETURN_NOT_SUCCESSFUL")
                    write_json(run/"initial-state-evidence.json",{"source":str(args.initial_state_evidence),"result":evidence})
            current=capture(run/"initial-observation",history)
            for index in range(start_index,51):
                if stopping():raise RuntimeError("HUMAN_STOP")
                step=new_run(run/("step-%02d"%index))
                step_result={"step":index,"status":"STARTED","arm_command_attempts":0,
                    "gripper_command_attempts":0,"executed_command":None,"execution_latency_s":0,
                    "input_observation":current,"before_pose":current["canonical_states"]["left"]["ee_pose"],
                    "gripper_before":current["canonical_states"]["left"]["gripper_state"],
                    "after_pose":None,"gripper_after":None,"robot_errors":None}
                summary["steps"]=index
                print("STEP %d"%index,flush=True)
                raw_printed=False
                try:
                    write_json(step/"observation.json",current)
                    decision=new_run(step/"decision")
                    reply=backend.decide(current,decision)
                    action=reply.proposal
                    print("ASTRA RAW: "+(decision/"last_message.json").read_text().strip(),flush=True)
                    raw_printed=True
                    step_result.update(raw_output=(decision/"last_message.json").read_text(),parsed_action=action,
                                       inference_latency_s=reply.metadata["inference_latency_s"])
                    write_json(step/"proposal.json",action)
                    if stopping():raise RuntimeError("HUMAN_STOP")
                    if time.time()-current["captured_at"]>ACTION_CONFIG["max_observation_age_s"]:raise RuntimeError("OBSERVATION_EXPIRED")
                    fresh=states_at(step/"pre-execution-readback.json")
                    old=current["canonical_states"]["left"]
                    write_json(step/"pre-dispatch-pose-telemetry.json",pose_telemetry(
                        old["ee_pose"],old["ee_pose"],fresh["left"]["ee_pose"]))
                    checked=copy.deepcopy(current);checked["canonical_states"]=fresh
                    review=review_pick(action,checked,**LIMITS)
                    has_arm_motion=any(action["translation_m"]+action["rotation_rpy_rad"])
                    if has_arm_motion:review["errors"]+=workspace_errors(review)
                    review["status"]="REJECT" if review["errors"] else "PASS"
                    review["operator_execute_required"]=False
                    review["execution_permitted"]=not review["errors"]
                    review["local_workspace"]=workspace
                    review["required_before_execution"]=["fresh state/error/frame validation","one proposal; at most one command per actuator channel; no retries"]
                    step_result["safety"]=review
                    step_result["before_pose"]=fresh["left"]["ee_pose"]
                    step_result["gripper_before"]=fresh["left"]["gripper_state"]
                    write_json(step/"safety.json",review)
                    if review["errors"]:
                        step_result["status"]="SAFETY_REJECT"
                        summary.update(status="STOPPED",stop_reason="SAFETY_REJECT",errors=review["errors"])
                        break
                    if action["done"]:
                        step_result["status"]="MODEL_DONE"
                        summary.update(status="STOPPED",stop_reason="MODEL_DONE",stable_pick_verified=False)
                        break
                    g_before=fresh["left"]["gripper_state"]
                    target_grip=(int(action["gripper"]*1000) if type(action["gripper"]) in (int,float)
                                 else {"open":1000,"close":0}.get(action["gripper"]))
                    grip_satisfied=(target_grip is not None and g_before["position"]==target_grip and g_before["raw"]["speed"][0]==0)
                    needs_grip=target_grip is not None and not grip_satisfied
                    noop=not has_arm_motion and not needs_grip
                    step_result["actuator_channels"]={
                        "arm":{"status":"PENDING" if has_arm_motion else "NO_MOTION_REQUESTED"},
                        "gripper":{"status":"HOLD" if target_grip is None else "ALREADY_SATISFIED" if grip_satisfied else "PENDING",
                                   "requested":action["gripper"],"wire_target":target_grip}}
                    started=time.monotonic()
                    if noop:
                        step_result["status"]="NOOP"
                    else:
                        command=None
                        if has_arm_motion:
                            target=review["target_pose"]
                            command={"function":"rm_movej_p","pose":target["xyz_m"]+target["rpy_rad"],
                                     "speed_percent":1,"r":0,"connect":0,"block":1}
                        claim(step,{"proposal":action,"arm":command,
                                    "gripper":{"target":target_grip,"requested":action["gripper"]} if needs_grip else None})
                        step_result["executed_command"]={"arm":None,"gripper":None}
                        if stopping():raise RuntimeError("HUMAN_STOP")
                        if time.time()-fresh["left"]["timestamp"]>3:raise RuntimeError("STATE_EXPIRED_AT_DISPATCH")
                        if has_arm_motion:
                            step_result["arm_command_attempts"]=1;summary["arm_command_attempts"]+=1
                            ret=session.connected["left"].rm_movej_p(command["pose"],1,0,0,1)
                            step_result["executed_command"]["arm"]={"request":command,"return":ret}
                            step_result["execution_latency_s"]=time.monotonic()-started
                            step_result["actuator_channels"]["arm"]["status"]="COMMAND_RETURNED" if ret==0 else "COMMAND_FAILED"
                            write_json(step/"arm-command-result.json",step_result["executed_command"]["arm"])
                            if type(ret)is not int or ret!=0:raise RuntimeError("ARM_COMMAND_RETURN:"+str(ret))
                        if needs_grip:
                            # Deterministic serialization within this proposal; never ask Astra between channels.
                            channel_state=states_at(step/"before-gripper-readback.json") if has_arm_motion else fresh
                            g=channel_state["left"]["gripper_state"]
                            if g["position"]==target_grip and g["raw"]["speed"][0]==0:
                                step_result["actuator_channels"]["gripper"]["status"]="ALREADY_SATISFIED"
                            else:
                                if stopping():raise RuntimeError("HUMAN_STOP")
                                adapter=LabGripperAdapter()
                                try:
                                    if stopping():raise RuntimeError("HUMAN_STOP")
                                    if time.time()-channel_state["left"]["timestamp"]>3:raise RuntimeError("STATE_EXPIRED_AT_DISPATCH")
                                    step_result["gripper_command_attempts"]=1;summary["gripper_command_attempts"]+=1
                                    response=adapter.set_gripper("left",action["gripper"])
                                    step_result["executed_command"]["gripper"]=response
                                    step_result["execution_latency_s"]=time.monotonic()-started
                                    if response.get("command_return")!={"command":"hand_follow_pos","set_state":True}:
                                        step_result["actuator_channels"]["gripper"]["status"]="COMMAND_FAILED"
                                        raise RuntimeError("GRIPPER_COMMAND_RETURN")
                                    step_result["actuator_channels"]["gripper"]["status"]="COMMAND_RETURNED"
                                finally:
                                    if adapter.last_result is not None:step_result["executed_command"]["gripper"]=adapter.last_result
                                    adapter.close()
                                time.sleep(2)
                        step_result["status"]="COMMAND_RETURNED"
                    step_result["execution_latency_s"]=time.monotonic()-started
                    history={"last_action":action,"last_result":{"status":step_result["status"],
                             "command":step_result["executed_command"]}}
                    after=capture(step/"after",history)
                    a=after["canonical_states"]["left"]
                    step_result.update(after_pose=a["ee_pose"],gripper_after=a["gripper_state"],
                        robot_errors={arm:s["system_error"]["codes"] for arm,s in after["canonical_states"].items()},
                        actual_xyz_delta_m=[b-v for v,b in zip(fresh["left"]["ee_pose"]["xyz_m"],a["ee_pose"]["xyz_m"])])
                    telemetry=pose_telemetry(fresh["left"]["ee_pose"],review["target_pose"],a["ee_pose"])
                    step_result["pose_telemetry"]=telemetry
                    write_json(step/"pose-telemetry.json",telemetry)
                    step_result["status"]="NOOP" if noop else "EXECUTED"
                    after["previous"]={"last_action":action,
                        "last_result":{"status":step_result["status"],"actual_xyz_delta_m":step_result["actual_xyz_delta_m"],
                                       "gripper_position":a["gripper_state"]["position"],
                                       "robot_errors":step_result["robot_errors"]}}
                    write_json(step/"after/verified-observation.json",after)
                    current=after
                except Exception as exc:
                    step_result.update(status="STOPPED",stop_reason=str(exc),exception_type=type(exc).__name__)
                    # Failure is terminal. A read-only snapshot records possible partial motion.
                    if step_result["arm_command_attempts"] or step_result["gripper_command_attempts"]:
                        failure={"timestamp":time.time(),"arms":{},"read_errors":[]}
                        for arm in ("right","left"):
                            try:failure["arms"][arm]=session.snapshot(arm)
                            except Exception as read_exc:failure["read_errors"].append(arm+":"+str(read_exc))
                        try:failure["left_gripper_raw"]=session.connected["left"].rm_get_rm_plus_state_info()
                        except Exception as read_exc:failure["read_errors"].append("gripper:"+str(read_exc))
                        state=failure["arms"].get("left",{}).get("canonical")
                        if state:
                            step_result["after_pose"]=state["ee_pose"]
                            if step_result.get("safety",{}).get("target_pose"):
                                failure["pose_telemetry"]=pose_telemetry(step_result["before_pose"],step_result["safety"]["target_pose"],state["ee_pose"])
                        step_result["robot_errors"]={arm:item["canonical"]["system_error"]["codes"] for arm,item in failure["arms"].items() if item.get("canonical")}
                        write_json(step/"failure-state.json",failure)
                    raise
                finally:
                    if not raw_printed:
                        raw_file=step/"decision/last_message.json"
                        raw=raw_file.read_text() if raw_file.exists() else None
                        step_result["raw_output"]=raw
                        print("ASTRA RAW: "+(raw.strip() if raw is not None else "null"),flush=True)
                    print("EXECUTED: "+json.dumps(step_result["executed_command"],ensure_ascii=False),flush=True)
                    print("ROBOT RESULT: "+json.dumps({"status":step_result["status"],
                        "robot_errors":step_result["robot_errors"],
                        "gripper_position":(step_result.get("gripper_after") or {}).get("position"),
                        "stop_reason":step_result.get("stop_reason")},ensure_ascii=False),flush=True)
                    write_json(step/"summary.json",step_result)
            else:summary.update(status="STOPPED",stop_reason="MAX_50_STEPS")
    except Exception as exc:
        summary.update(status="STOPPED",stop_reason=str(exc),exception_type=type(exc).__name__)
        if step_result is None:
            print("ROBOT RESULT: "+json.dumps({"status":"STOPPED","stop_reason":str(exc),"run":str(run)},ensure_ascii=False),flush=True)
    finally:
        write_json(run/"summary.json",summary)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=="__main__":main()
