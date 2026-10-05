#!/usr/bin/env python3
"""Capture once, request one proposal, print review packet. NO execution option."""
import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, read_json, write_json, new_run
from decision_observation import capture_decision
from decision_backends import CodexBackend, BackendFailure

PREVIOUS_RUN = ROOT/"logs/supervised-step-20261002T203531-b1cddd33"
TASK = (
    "左臂抓取网球：根据本次四路真实图像和当前机器人状态，提出且只提出下一步最小 Cartesian correction。"
    "当前阶段只做人工审核 proposal；禁止执行。arm=left；frame=realman:left:work:World；"
    "tool_frame 使用当前 active tool id。每轴 translation 绝对值<=0.003m；rotation=[0,0,0]；"
    "gripper=hold。World+Z 已由现场人员确认竖直向上，上一轮同一坐标系+10mm实测+9.940mm。"
    "请识别真实网球和左臂工具相对位置；若四视角不能可靠判断所需 robot-axis 方向，返回NOOP，"
    "不猜测X/Y轴正负，不为了生成non-zero而任意移动，不把缺少外参本身当作必须NOOP的理由。"
    "不调用工具、SDK、SSH或任何控制接口。完成抓取前done=false。"
)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model",default="gpt-6-astra")
    args=p.parse_args()
    run=new_run(ROOT/"logs"/("model-step-review-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-"+uuid.uuid4().hex[:8]))
    summary={"run":str(run),"mode":"proposal_only_await_literal_EXECUTE","motion_commands_sent":0,
             "gripper_commands_sent":0,"execution_permitted":False,"status":"REJECT","model":args.model}
    try:
        prior=read_json(PREVIOUS_RUN/"summary.json")
        if prior["status"]!="EXECUTED_VERIFIED":
            raise ValueError("PRIOR_RELATIVE_MOTION_NOT_VERIFIED")
        previous={"source":str(PREVIOUS_RUN/"summary.json"),"status":prior["status"],
                  "action":prior["action"],"actual_delta_m":prior["measured_delta_m"],
                  "before":prior["before"],"after":prior["after"],
                  "motion_command_attempts":prior["motion_command_attempts"],"gripper_commands_sent":0}
        config=read_json(ROOT/"config/lab.json")
        config["safety"]["allowed_arms"]=["left"]
        config["decision_safety_context"]={
            "mode":"supervised_single_model_step_pending_operator_review",
            "translation_axis_limit_m":.003,"rotation_rpy_rad":[0,0,0],"gripper":"hold",
            "physical_arm":{"left_ip":"192.168.1.19","evidence":"19左，用19"},
            "relative_work_motion":{"status":"VERIFIED_BY_REAL_SINGLE_STEP",
                "arm":"left","work_frame_id":"realman:left:work:World",
                "tool_frame_id":"realman:left:tool:Arm_Tip",
                "source":str(PREVIOUS_RUN/"summary.json"),
                "requested_delta_m":[0,0,.01],"measured_delta_m":prior["measured_delta_m"],
                "work_frame":prior["after"]["work_frame"],"tool_frame":prior["after"]["tool_frame"],
                "world_positive_z":"vertically_up","axis_evidence":"worldz是竖直向上",
                "x_y_pixel_to_work_axis_mapping":"UNKNOWN"},
            "local_workspace":{"status":"PENDING_OPERATOR_REVIEW_OF_EXACT_PROPOSAL",
                "geometry_bounds_m":None,
                "prior_evidence":"User stated surroundings empty and cleared prior World+Z segment.",
                "scope":"No generic box is inferred from step size; new exact segment is displayed for operator EXECUTE review."},
            "camera_extrinsics":{"status":"UNKNOWN","used_for_explicit_transform":False},
            "full_tool_geometry":{"status":"UNKNOWN","gripper_motion_allowed":False},
            "execution_authorization":"NONE; literal EXECUTE must be supplied after this proposal is displayed",
            "post_approval_contract":"Re-read state/errors/frame, bind displayed delta to fresh unchanged pose, dispatch once, then state+four-images and stop."}
        input_run=new_run(run/"input")
        observation=capture_decision(config,input_run,TASK,previous)
        write_json(run/"observation.json",observation)
        print(json.dumps({"stage":"observation_captured","run":str(run),
                          "images":len(observation["cameras"]),"capture_span_ms":observation["capture_span_ms"],
                          "capture_failures":observation["capture_failures"],"motion_commands_sent":0},ensure_ascii=False),flush=True)
        if observation["capture_failures"] or len(observation["cameras"])!=4:
            raise ValueError("FRESH_FOUR_VIEW_CAPTURE_FAILED")
        for arm,state in observation["canonical_states"].items():
            if state.get("system_error",{}).get("has_error") is not False:
                raise ValueError("ARM_ERROR_OR_UNKNOWN:"+arm)
        backend_config=read_json(ROOT/"config/decision_backend.json")
        backend=CodexBackend(args.model,executable=backend_config["executable"],
                             provider=backend_config["provider"],timeout_s=backend_config["timeout_s"],
                             profile="supervised_model_step_v1")
        decision_run=new_run(run/"decision")
        reply=backend.decide(observation,decision_run)
        raw=(decision_run/"last_message.json").read_text()
        from model_step_review import review_proposal
        assessment=review_proposal(reply.proposal,observation,time.time(),reply.metadata["finished_at"])
        write_json(run/"proposal.json",reply.proposal)
        write_json(run/"review.json",assessment)
        summary.update(status=assessment["status"],raw_proposal=raw,proposal=reply.proposal,review=assessment,
                       inference_latency_s=reply.metadata["inference_latency_s"],
                       capture_span_ms=observation["capture_span_ms"],image_count=len(observation["cameras"]),
                       observation_id=observation["observation_id"],
                       proposal_sha256=hashlib.sha256(json.dumps(reply.proposal,sort_keys=True,allow_nan=False).encode()).hexdigest(),
                       previous_result=str(PREVIOUS_RUN/"summary.json"))
        write_json(run/"pending-proposal.json",{
            "status":assessment["status"],"action":reply.proposal,
            "proposal_sha256":summary["proposal_sha256"],"observation":str(run/"observation.json"),
            "review":str(run/"review.json"),"decision_metadata":str(decision_run/"backend_result.json"),
            "required_user_input":"EXECUTE","authorization_received":False,
            "action_count":1,"execution_permitted":False,"motion_commands_sent":0})
    except Exception as exc:
        summary.update(status="REJECT",error_type=type(exc).__name__,error=str(exc))
        if isinstance(exc,BackendFailure):
            summary["backend_error"]=exc.code
    write_json(run/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if summary["status"] in ("AWAITING_EXECUTE","PASS_NOOP") else 2

if __name__=="__main__":
    raise SystemExit(main())
