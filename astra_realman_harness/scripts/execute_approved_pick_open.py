#!/usr/bin/env python3
"""Consume this approved open proposal once, observe, then propose once; never execute next proposal."""
import copy,hashlib,json,os,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json,write_json,new_run
from realman_api2_readonly import SDKReadOnly
from camera_session import CameraSession
from pick_task import TASK,PickBackend,parse_pick,review_pick

APPROVED=ROOT/"logs/pick-task-20261002T124727Z-c1699dfa"
EXACT={"action_type":"cartesian_delta","arm":"left","frame":"realman:left:work:World",
       "tool_frame":"realman:left:tool:Arm_Tip","translation_m":[0,0,0],
       "rotation_rpy_rad":[0,0,0],"gripper":"open","done":False}

def reserve(run, action):
    path=APPROVED/"execution.claim.json"
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w") as f:
        json.dump({"authorization":"execute","action":action,"run":str(run),
                   "timestamp":time.time(),"replay_allowed":False},f)
        f.flush();os.fsync(f.fileno())
    fd=os.open(str(APPROVED),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def main():
    if (APPROVED/"execution.claim.json").exists():
        raise SystemExit("APPROVAL_ALREADY_CONSUMED_NO_RETRY")
    run=new_run(ROOT/"logs"/("pick-execution-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-"+uuid.uuid4().hex[:8]))
    summary={"run":str(run),"approved_run":str(APPROVED),"arm_motion_commands":0,
             "gripper_command_attempts":0,"status":"REJECT","next_action_executed":False}
    sequence=0
    try:
        pending=read_json(APPROVED/"pending-proposal.json")
        action=parse_pick(json.dumps(pending["action"],allow_nan=False))
        if action!=EXACT:
            raise ValueError("ONLY_EXACT_APPROVED_OPEN_SUPPORTED")
        if hashlib.sha256(json.dumps(action,sort_keys=True).encode()).hexdigest()!=pending["proposal_sha256"]:
            raise ValueError("PROPOSAL_HASH_CHANGED")
        if read_json(APPROVED/"review.json")["status"]!="AWAITING_EXECUTE":
            raise ValueError("PROPOSAL_NOT_AWAITING_EXECUTE")
        old=read_json(APPROVED/"observation.json")["canonical_states"]["left"]
        config=read_json(ROOT/"config/lab.json")
        with CameraSession(config["devices"]["cameras"]) as cameras, SDKReadOnly(new_run(run/"sdk")) as session:
            for arm,host in (("left","192.168.1.19"),("right","192.168.1.18")):
                if not session.connect(arm,host,8080)["connected"]:
                    raise RuntimeError("CONNECT_FAILED:"+arm)
            robot=session.connected["left"]
            def read_plus(name):
                nonlocal sequence
                sequence+=1
                started=time.time()
                raw=getattr(robot,name)()
                write_json(run/("plus-%03d-%s.json"%(sequence,name)),
                           {"function":name,"raw_return":raw,"started_at":started,"finished_at":time.time()})
                if type(raw[0]) is not int or raw[0]!=0:
                    raise RuntimeError("SDK_READ_FAILED:"+name+":"+str(raw[0]))
                return raw[1]
            base=read_plus("rm_get_rm_plus_base_info")
            if (base["manu"]!="ZX" or base["type"]!=1 or base["dof"]!=1 or
                base["pos_low"][0]!=0 or base["pos_up"][0]!=1000):
                raise RuntimeError("GRIPPER_OPEN_MAPPING_MISMATCH")
            def grip_state():
                state=read_plus("rm_get_rm_plus_state_info")
                if state["sys_state"]!=0 or state["dof_err"][0]!=0:
                    raise RuntimeError("GRIPPER_ERROR")
                return state
            def capture(label,history):
                capture_run=new_run(run/label)
                started=time.time()
                states={}
                for arm in ("right","left"):
                    sample=session.snapshot(arm)
                    if not sample["canonical"]:
                        raise RuntimeError("CANONICAL_READ_FAILED:"+arm)
                    states[arm]=sample["canonical"]
                gripper=grip_state()
                states["left"]["gripper_state"]={"manufacturer":"ZX","dof":1,"raw":gripper,
                    "position":gripper["pos"][0],"position_range":[0,1000],
                    "open_position":1000,"closed_position":0}
                images,failures,metrics=cameras.snapshot(capture_run)
                obs={"schema_version":"astra.decision.observation.v1","observation_id":"pick-"+uuid.uuid4().hex,
                     "task":TASK,"capture_started_at":started,"capture_finished_at":time.time(),
                     "captured_at":min([s["timestamp"] for s in states.values()]+[c["captured_at"] for c in images]),
                     "canonical_states":states,"cameras":images,"camera_capture":metrics,
                     "capture_span_ms":metrics["capture_span_ms"],"capture_failures":failures,
                     "frames":config["frames"],"allowed_proposal_arms":["left"],"previous":history,
                     "source":{"kind":"real_capture","physical":True},
                     "motion_commands_sent":summary["gripper_command_attempts"]}
                write_json(capture_run/"observation.json",obs)
                if failures or len(images)!=4:raise RuntimeError("FOUR_CAMERA_CAPTURE_FAILED")
                return obs
            pre=capture("before",{"approved_action":action})
            check=review_pick(action,pre)
            write_json(run/"pre-execution-review.json",check)
            if check["errors"]:raise RuntimeError("SAFETY_REJECT:"+",".join(check["errors"]))
            fresh=pre["canonical_states"]["left"]
            for name,tol in (("xyz_m",.0002),("rpy_rad",.002)):
                if any(abs(a-b)>tol for a,b in zip(fresh["ee_pose"][name],old["ee_pose"][name])):
                    raise RuntimeError("APPROVED_POSE_CHANGED")
            if abs(fresh["gripper_state"]["raw"]["speed"][0])>0:
                raise RuntimeError("GRIPPER_ALREADY_MOVING")
            reserve(run,action)
            write_json(run/"dispatch-intent.json",{
                "function":"rm_set_hand_follow_pos","ip":"192.168.1.19","hand_pos":[1000,0,0,0,0,0],
                "device_dof":1,"block":True,"authorized_gripper_action":"open",
                "mapping_source":"/home/tongji/aloha/RealMan_Control/CHANGE.md",
                "protocol_source":"/home/tongji/aloha/RealMan_Control/realman_arm.py",
                "note":"SDK six-element array; live device has one DOF. No range/speed/mode setters."})
            if any(time.time()-s["timestamp"]>3 for s in pre["canonical_states"].values()):
                raise RuntimeError("STATE_STALE_BEFORE_DISPATCH")
            summary["gripper_command_attempts"]=1
            started=time.time()
            ret=robot.rm_set_hand_follow_pos([1000,0,0,0,0,0],True)
            write_json(run/"dispatch-result.json",{"return_code":ret,"started_at":started,
                      "finished_at":time.time(),"gripper_command_attempts":1,"retry_allowed":False})
            if type(ret)is not int or ret!=0:
                raise RuntimeError("GRIPPER_SDK_RETURN:"+str(ret))
            deadline=time.monotonic()+8
            reached=False
            while time.monotonic()<deadline:
                feedback=grip_state()
                if abs(feedback["pos"][0]-1000)<=1 and feedback["speed"][0]==0:
                    reached=True;break
                time.sleep(.2) # Read-only arrival monitoring; never resends the command.
            if not reached:raise RuntimeError("GRIPPER_OPEN_NOT_VERIFIED")
            post=capture("after",{"last_action":action,"result":{"gripper_position":feedback["pos"][0],
                         "status":"EXECUTED_VERIFIED","arm_motion_commands":0,"gripper_commands":1}})
            validation=review_pick(action,post)
            if validation["errors"]:raise RuntimeError("POST_SAFETY:"+",".join(validation["errors"]))
            after=post["canonical_states"]["left"]
            delta=[b-a for a,b in zip(fresh["ee_pose"]["xyz_m"],after["ee_pose"]["xyz_m"])]
            rpy_delta=[b-a for a,b in zip(fresh["ee_pose"]["rpy_rad"],after["ee_pose"]["rpy_rad"])]
            if any(abs(v)>.0002 for v in delta) or any(abs(v)>.002 for v in rpy_delta):
                raise RuntimeError("UNEXPECTED_ARM_POSE_CHANGE")
            summary.update(status="EXECUTED_VERIFIED",gripper_before=fresh["gripper_state"]["position"],
                gripper_after=feedback["pos"][0],xyz_delta_m=delta,rpy_delta_rad=rpy_delta,
                left_error=after["system_error"]["codes"],
                right_error=post["canonical_states"]["right"]["system_error"]["codes"],
                post_image_count=4,post_capture_span_ms=post["capture_span_ms"],sdk_return=ret)
            write_json(run/"execution-summary.json",summary)
            print(json.dumps(summary,ensure_ascii=False),flush=True)
            decision=new_run(run/"next-decision")
            reply=PickBackend(read_json(ROOT/"config/decision_backend.json")).decide(post,decision)
            review=review_pick(reply.proposal,post)
            write_json(run/"next-proposal.json",reply.proposal)
            write_json(run/"next-review.json",review)
            write_json(run/"pending-proposal.json",{
                "action":reply.proposal,"review":str(run/"next-review.json"),
                "observation":str(run/"after/observation.json"),"required_input":"EXECUTE",
                "authorization_received":False,"execution_permitted":False,
                "proposal_sha256":hashlib.sha256(json.dumps(reply.proposal,sort_keys=True).encode()).hexdigest()})
            summary.update(next_status=review["status"],next_proposal=reply.proposal,
                next_review=review,raw_next_proposal=(decision/"last_message.json").read_text(),
                inference_latency_s=reply.metadata["inference_latency_s"])
    except Exception as exc:
        summary.update(error_type=type(exc).__name__,error=str(exc))
        if summary["status"]!="EXECUTED_VERIFIED":
            summary["status"]="EXECUTION_UNCERTAIN" if summary["gripper_command_attempts"] else "REJECT"
    write_json(run/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if summary["status"]=="EXECUTED_VERIFIED" else 2

if __name__=="__main__":raise SystemExit(main())
