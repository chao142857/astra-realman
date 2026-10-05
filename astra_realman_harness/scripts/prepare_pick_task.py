#!/usr/bin/env python3
"""One normal pick decision. No hardware execution path and no decision loop."""
import json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json,write_json,new_run
from decision_observation import capture_decision
from pick_task import TASK,PickBackend,review_pick

def main():
    run=new_run(ROOT/"logs"/("pick-task-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-"+uuid.uuid4().hex[:8]))
    summary={"run":str(run),"task":TASK,"status":"REJECT","motion_commands_sent":0,
             "execution_permitted":False,"required_input":"EXECUTE"}
    try:
        previous=read_json(ROOT/"logs/supervised-step-20261002T203531-b1cddd33/summary.json")
        last=read_json(ROOT/"logs/model-step-review-20261002T124210Z-698db83a/summary.json")
        history={"last_executed_action":previous["action"],
                 "last_execution_result":{"actual_xyz_delta_m":previous["measured_delta_m"],
                                          "status":previous["status"]},
                 "last_proposal":last["proposal"],
                 "last_proposal_result":{"status":last["status"],"executed":False}}
        config=read_json(ROOT/"config/lab.json")
        config["safety"]["allowed_arms"]=["left"]
        observation=capture_decision(config,new_run(run/"input"),TASK,history)
        write_json(run/"observation.json",observation)
        print(json.dumps({"stage":"captured","run":str(run),"images":len(observation["cameras"]),
              "capture_span_ms":observation["capture_span_ms"],"failures":observation["capture_failures"],
              "motion_commands_sent":0}),flush=True)
        if observation["capture_failures"] or len(observation["cameras"])!=4:
            raise ValueError("OBSERVATION_FAILED")
        for state in observation["canonical_states"].values():
            if state["system_error"]["has_error"]:
                raise ValueError("ROBOT_ERROR")
        decision=new_run(run/"decision")
        reply=PickBackend(read_json(ROOT/"config/decision_backend.json")).decide(observation,decision)
        write_json(run/"proposal.json",reply.proposal)
        review=review_pick(reply.proposal,observation)
        write_json(run/"review.json",review)
        summary.update(status=review["status"],proposal=reply.proposal,
            raw_proposal=(decision/"last_message.json").read_text(),review=review,
            inference_latency_s=reply.metadata["inference_latency_s"],
            capture_span_ms=observation["capture_span_ms"],image_count=4)
        write_json(run/"pending-proposal.json",{
            "action":reply.proposal,"review":str(run/"review.json"),"observation":str(run/"observation.json"),
            "authorization_received":False,"required_input":"EXECUTE",
            "proposal_sha256":__import__("hashlib").sha256(json.dumps(reply.proposal,sort_keys=True).encode()).hexdigest(),
            "execution_permitted":False,"motion_commands_sent":0})
    except Exception as exc:
        summary.update(error_type=type(exc).__name__,error=str(exc))
    write_json(run/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if summary["status"] in ("AWAITING_EXECUTE","PASS_NOOP") else 2

if __name__=="__main__":
    raise SystemExit(main())
