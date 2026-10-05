#!/usr/bin/env python3
"""Offline revalidation of a recorded CLI result; never invokes Codex or hardware."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import hashlib
import json
import time
import uuid
from io_utils import ROOT, read_json, write_json, new_run, output_path
from decision_backends import parse_codex_result, build_context, BackendFailure
from decision_safety import assess_decision, rejected
from decision_executor import DryRunExecutor

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-run",type=Path,required=True)
    p.add_argument("--out",type=Path)
    args=p.parse_args()
    source=output_path(args.source_run)
    run=new_run(args.out or ROOT/"logs"/("decision-replay-"+time.strftime("%Y%m%dT%H%M%S",time.gmtime())+"-"+uuid.uuid4().hex[:8]))
    policy=read_json(source/"safety_policy.json")
    observation=read_json(source/"observation.json")
    metadata=read_json(source/"decision/backend_result.json")
    action=None; warnings=[]
    try:
        context=build_context(observation)
        action,warnings=parse_codex_result(source/"decision",metadata.get("return_code"))
        write_json(run/"proposal.json",action)
        result=assess_decision(action,observation,policy,time.time(),metadata["finished_at"])
        # Separately labelled historical diagnostic, never used as authorization.
        historical=assess_decision(action,observation,policy,metadata["finished_at"],metadata["finished_at"])
        write_json(run/"at_original_inference_completion.json",{
            "mode":"RETROSPECTIVE_DIAGNOSTIC_ONLY","evaluated_at":metadata["finished_at"],
            "validation":historical,"execution_permitted":False})
    except (BackendFailure,ValueError) as exc:
        result=rejected([str(exc)])
    execution=DryRunExecutor().submit(action,result)
    write_json(run/"validation.json",result); write_json(run/"executor.json",execution)
    summary={"run":str(run),"mode":"OFFLINE_REVALIDATION_OF_ONE_EXISTING_INFERENCE",
             "source_run":str(source),"model":metadata.get("model_requested"),
             "inference_latency_s":metadata.get("inference_latency_s"),
             "image_count":len(observation["cameras"]),"capture_span_ms":observation["capture_span_ms"],
             "new_model_calls":0,"new_hardware_queries":0,"motion_commands_sent":0,
             "source_original_error":metadata.get("error"),"cli_warnings":warnings,
             "proposal":action,"safety":result,"execution":execution,
             "source_hashes":{name:hashlib.sha256((source/name).read_bytes()).hexdigest()
                              for name in ("observation.json","decision/events.jsonl","decision/last_message.json")}}
    write_json(run/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False))
    return 0 if result["decision"] in ("PASS_NOOP","PASS_EXECUTABLE") else 2

if __name__=="__main__": sys.exit(main())
