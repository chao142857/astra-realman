"""One authorized low-speed left joint return; no retry or gripper command."""
import fcntl,json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json,new_run,write_json,vector
from realman_api2_readonly import SDKReadOnly

def main():
    source=ROOT/"logs/auto-pick-20261002T130327Z-83fd557f/initial-observation/observation.json"
    initial=read_json(source)["canonical_states"]["left"]
    target=initial["joint_deg"]
    if not vector(target,6) or initial["connection"]["ip"]!="192.168.1.19":raise RuntimeError("INVALID_RECORDED_TARGET")
    run=new_run(ROOT/"logs"/("return-auto-start-"+str(time.time_ns())))
    lock=(ROOT/"logs/auto-pick.lock").open("a+");fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    result={"source":str(source),"target_joint_deg":target,"motion_commands_sent":0,"right_commands_sent":0,"gripper_commands_sent":0,"run":str(run)}
    try:
        with SDKReadOnly(new_run(run/"sdk")) as session:
            for arm,ip in (("left","192.168.1.19"),("right","192.168.1.18")):
                if not session.connect(arm,ip,8080)["connected"]:raise RuntimeError("CONNECT_FAILED:"+arm)
            before={a:session.snapshot(a)["canonical"] for a in ("left","right")}
            result["before"]=before
            if any(not s or s["system_error"]["has_error"] for s in before.values()):raise RuntimeError("ROBOT_ERROR_OR_INVALID_STATE")
            grip=session.connected["left"].rm_get_rm_plus_state_info();result["gripper_before"]=grip
            if grip[0]!=0 or grip[1]["sys_state"]!=0 or any(grip[1]["dof_err"]):raise RuntimeError("GRIPPER_ERROR")
            if (run/"STOP").exists():raise RuntimeError("HUMAN_STOP")
            command={"function":"rm_movej","arm":"left","joint_deg":target,"v":1,"r":0,"connect":0,"block":1}
            claim=ROOT/"logs/return-auto-start-20261002-once.claim.json"
            with claim.open("x") as f:json.dump({"run":str(run),"command":command},f);f.flush();os.fsync(f.fileno())
            result["command"]=command;result["motion_commands_sent"]=1
            write_json(run/"dispatch.json",result)
            print("RETURN_START | left | movej speed=1% | single command",flush=True)
            started=time.monotonic()
            ret=session.connected["left"].rm_movej(target,1,0,0,1)
            result["command_return"]=ret;result["latency_s"]=time.monotonic()-started
            after={a:session.snapshot(a)["canonical"] for a in ("left","right")}
            result["after"]=after;result["gripper_after"]=session.connected["left"].rm_get_rm_plus_state_info()
            result["robot_errors"]={a:s["system_error"]["codes"] if s else None for a,s in after.items()}
            result["actual_joint_deg"]=after["left"]["joint_deg"] if after["left"] else None
            result["max_joint_difference_deg"]=max(abs(a-b) for a,b in zip(result["actual_joint_deg"],target)) if result["actual_joint_deg"] else None
            result["status"]="RETURNED" if ret==0 and all(s and not s["system_error"]["has_error"] for s in after.values()) else "STOPPED"
    except Exception as exc:result.update(status="STOPPED",error=str(exc))
    finally:
        write_json(run/"summary.json",result);fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    print(json.dumps({k:v for k,v in result.items() if k not in ("before","after","gripper_before","gripper_after")}),flush=True)
if __name__=="__main__":main()
