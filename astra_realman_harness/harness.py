#!/usr/bin/env python3
"""No motion executor exists in this program."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import argparse
import hashlib
import json
import time
from io_utils import ROOT, read_json, new_run, write_json
from observation import offline_observation, capture
from protocol import parse, fixture_proposal
from safety import assess, check_policy
from providers import call_api

def main(argv=None):
    p = argparse.ArgumentParser(description="Astra → RealMan DRY-RUN ONLY; no motion backend")
    sub = p.add_subparsers(dest="command",required=True)
    for name in ("capture","offline-observation","dry-run"):
        q = sub.add_parser(name)
        q.add_argument("--config",type=Path,default=ROOT/"config/lab.json")
        q.add_argument("--out",type=Path,required=True,help="new directory under harness root")
        if name != "dry-run":
            q.add_argument("--task",required=True)
        if name == "capture":
            q.add_argument("--cameras",nargs="*",default=[])
            q.add_argument("--arms",nargs="*",choices=["left","right"],default=[])
        if name == "dry-run":
            q.add_argument("--observation",type=Path,required=True)
            q.add_argument("--provider",choices=["fixture","replay","api"],required=True)
            q.add_argument("--proposal",type=Path)
    args = p.parse_args(argv)
    config = read_json(args.config)
    check_policy(config["safety"])
    run = new_run(args.out)
    if args.command == "offline-observation":
        obs = offline_observation(args.task)
        write_json(run/"observation.json",obs)
        print(json.dumps({"observation":str(run/"observation.json"),
                          "source":"offline_fixture","motion_commands_sent":0}))
        return 0
    if args.command == "capture":
        if not args.cameras and not args.arms:
            raise ValueError("CAPTURE_REQUIRES_EXPLICIT_DEVICES")
        obs = capture(config,run,args.task,args.cameras,args.arms)
        print(json.dumps({"observation":str(run/"observation.json"),
                          "images":len(obs["cameras"]),"failures":obs["capture_failures"],
                          "capture_span_ms":obs.get("capture_span_ms"),
                          "motion_commands_sent":0},ensure_ascii=False))
        return 0 if not obs["capture_failures"] else 2
    event = {"mode":"dry_run_only","provider":args.provider,"started_at":time.time(),
             "api_call_attempted":False,"api_response_received":False,
             "motion_commands_sent":0,"execution_permitted":False}
    try:
        observation = read_json(args.observation)
        write_json(run/"observation.json",observation)
        write_json(run/"safety_policy.json",config["safety"])
        schema = read_json(ROOT/"schema/action.schema.json")
        event["action_schema_sha256"] = hashlib.sha256((ROOT/"schema/action.schema.json").read_bytes()).hexdigest()
        if args.provider == "fixture":
            fixture_arm = config.get("fixture_arm", "right")
            if fixture_arm not in config["safety"]["allowed_arms"]:
                raise ValueError("FIXTURE_ARM_NOT_ALLOWED")
            raw = json.dumps(fixture_proposal(observation,time.time(), arm=fixture_arm),allow_nan=False)
            event["model_called"] = False
        elif args.provider == "replay":
            if not args.proposal:
                raise ValueError("REPLAY_REQUIRES_PROPOSAL")
            if args.proposal.stat().st_size > 1024*1024:
                raise ValueError("PROPOSAL_TOO_LARGE")
            raw = args.proposal.read_text(encoding="utf-8")
            event["model_called"] = False
        else:
            event["api_call_attempted"] = True
            raw = call_api(config["api"],observation,schema)
            event["api_response_received"] = True
            event["model_called"] = True
        write_json(run/"provider_response.json",{"provider":args.provider,"response_text":raw})
        proposal = parse(raw)
        write_json(run/"proposal.json",proposal)
        result = assess(proposal,observation,config["safety"],time.time())
        event["decision"] = result["decision"]
        write_json(run/"validation.json",result)
        print(json.dumps({"run":str(run),"provider":args.provider,**result},ensure_ascii=False))
        return 0 if result["decision"] == "VALID_DRY_RUN_ONLY" else 2
    except Exception as exc:
        event["decision"] = "ERROR"
        # Avoid logging API headers, credentials, or raw network exception text.
        event["error_type"] = type(exc).__name__
        event["error"] = (str(exc)[:500] if isinstance(exc,ValueError) else "SEE_ERROR_TYPE")
        write_json(run/"validation.json",{"decision":"ERROR","error":event["error"],
                                         "execution_permitted":False,"motion_commands_sent":0})
        print(json.dumps({"run":str(run),"error":event["error"],"motion_commands_sent":0}))
        return 2
    finally:
        event["finished_at"] = time.time()
        write_json(run/"event.json",event)

if __name__ == "__main__":
    sys.exit(main())
