#!/usr/bin/env python3
"""One approved laboratory-driver gripper open smoke test. No arm motion."""
import json,os,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,new_run,write_json
from realman_api2_readonly import SDKReadOnly
from lab_gripper_adapter import LabGripperAdapter

CLAIM=ROOT/"logs/lab-gripper-open-smoke-20261002.claim.json"

def main():
    if CLAIM.exists():raise SystemExit("SMOKE_ALREADY_CONSUMED_NO_RETRY")
    run=new_run(ROOT/"logs"/("lab-gripper-smoke-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-"+uuid.uuid4().hex[:8]))
    result={"run":str(run),"arm_motion_commands":0,"gripper_command_attempts":0,"status":"REJECT","automatic_retry":False}
    adapter=None
    try:
        adapter=LabGripperAdapter()
        with SDKReadOnly(new_run(run/"sdk")) as session:
            for arm,host in (("left","192.168.1.19"),("right","192.168.1.18")):
                if not session.connect(arm,host,8080)["connected"]:
                    raise RuntimeError("STATE_CONNECTION_FAILED:"+arm)
            def read_state(label):
                states={}
                for arm in ("left","right"):
                    states[arm]=session.snapshot(arm)["canonical"]
                    if not states[arm]:raise RuntimeError("STATE_READ_FAILED:"+arm)
                raw=session.connected["left"].rm_get_rm_plus_state_info()
                data={"arms":states,"gripper_return":raw,"timestamp":time.time()}
                write_json(run/(label+".json"),data)
                if raw[0]!=0:raise RuntimeError("GRIPPER_READ_FAILED:"+str(raw[0]))
                return data
            before=read_state("before")
            result["before_gripper_feedback"]=before["gripper_return"][1]
            result["before_errors"]={a:s["system_error"]["codes"] for a,s in before["arms"].items()}
            if any(s["system_error"]["has_error"] for s in before["arms"].values()):
                raise RuntimeError("ARM_ERROR")
            grip=before["gripper_return"][1]
            if grip["sys_state"]!=0 or grip["dof_err"][0]!=0 or grip["speed"][0]!=0:
                raise RuntimeError("GRIPPER_ERROR_OR_MOVING")
            fd=os.open(str(CLAIM),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,"w") as f:
                json.dump({"run":str(run),"authorization":"User explicitly requested one existing-driver open smoke",
                           "action":{"arm":"left","gripper":"open","target":1000}},f)
                f.flush();os.fsync(f.fileno())
            fd=os.open(str(CLAIM.parent),os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
            if any(time.time()-s["timestamp"]>3 for s in before["arms"].values()):
                raise RuntimeError("FRESH_STATE_EXPIRED")
            command_error=None
            try:
                result["command"]=adapter.set_gripper("left","open")
            except Exception as exc:
                command_error=str(exc)
                result["command"]=adapter.last_result
                result["command_exception"]=command_error
            result["gripper_command_attempts"]=adapter.last_result["send_attempts"]
            write_json(run/"command.json",result["command"])
            time.sleep(2.0) # Existing laboratory test/control settling interval; no repeat command.
            after=read_state("after")
            result["after_gripper_feedback"]=after["gripper_return"][1]
            result["after_errors"]={a:s["system_error"]["codes"] for a,s in after["arms"].items()}
            result["left_xyz_delta_m"]=[b-a for a,b in zip(before["arms"]["left"]["ee_pose"]["xyz_m"],
                                                            after["arms"]["left"]["ee_pose"]["xyz_m"])]
            result["left_rpy_delta_rad"]=[b-a for a,b in zip(before["arms"]["left"]["ee_pose"]["rpy_rad"],
                                                              after["arms"]["left"]["ee_pose"]["rpy_rad"])]
            grip_after=after["gripper_return"][1]
            healthy=(not any(s["system_error"]["has_error"] for s in after["arms"].values())
                     and grip_after["sys_state"]==0 and grip_after["dof_err"][0]==0)
            result["opened_by_feedback"]=(grip_after["pos"][0]==1000 and grip_after["speed"][0]==0 and healthy)
            reply=result["command"].get("command_return",{})
            rejected=any(value is False for value in reply.values())
            unchanged=(all(abs(v)<=.0002 for v in result["left_xyz_delta_m"]) and
                       all(abs(v)<=.002 for v in result["left_rpy_delta_rad"]))
            result["status"]="SUCCESS" if result["opened_by_feedback"] and not command_error and not rejected and unchanged else "STOPPED_NOT_VERIFIED"
    except Exception as exc:
        result.update(error_type=type(exc).__name__,error=str(exc))
        if adapter and adapter.last_result:
            result["command"]=adapter.last_result
            result["gripper_command_attempts"]=adapter.last_result["send_attempts"]
            if result["gripper_command_attempts"]:result["status"]="EXECUTION_UNCERTAIN"
    finally:
        if adapter:adapter.close()
    write_json(run/"summary.json",result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result["status"]=="SUCCESS" else 2

if __name__=="__main__":raise SystemExit(main())
