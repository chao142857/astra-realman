#!/usr/bin/env python3
"""Real observation -> DecisionBackend -> ActionProposal -> Safety -> DryRunExecutor."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
import json
import time
import uuid
from io_utils import ROOT, read_json, write_json, new_run
from decision_backends import CodexBackend, AstraBackend, BackendFailure
from decision_observation import capture_decision
from decision_safety import assess_decision, rejected, check_phase_policy
from decision_executor import DryRunExecutor

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__ + "; NO HARDWARE EXECUTOR")
    p.add_argument("--backend", choices=("codex", "astra"), default="codex")
    p.add_argument("--model", help="Exact model supported by the existing upstream; no implicit fallback")
    p.add_argument("--backend-config", type=Path, default=ROOT/"config/decision_backend.json")
    p.add_argument("--config", type=Path, default=ROOT/"config/lab.json")
    p.add_argument("--safety-policy", type=Path, default=ROOT/"config/shadow_phase1.json")
    p.add_argument("--task", required=True)
    p.add_argument("--observation", type=Path, help="Replay a saved real observation; normal freshness checks still apply")
    p.add_argument("--previous-result", type=Path, help="Previous shadow result, including its observation/result provenance")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    out = args.out or ROOT/"logs"/("decision-shadow-"+time.strftime("%Y%m%dT%H%M%S",time.gmtime())+"-"+uuid.uuid4().hex[:8])
    run = new_run(out)
    config, backend_config = read_json(args.config), read_json(args.backend_config)
    action, metadata, observation = None, {}, None
    executor = DryRunExecutor()
    try:
        policy = check_phase_policy(read_json(args.safety_policy))
        config["decision_safety_context"] = policy
        write_json(run/"safety_policy.json", policy)
        if args.backend == "codex" and not args.model:
            raise BackendFailure("CODEX_MODEL_REQUIRED")
        previous = read_json(args.previous_result) if args.previous_result else None
        if args.observation:
            observation = read_json(args.observation)
            if args.task != observation.get("task"):
                raise BackendFailure("REPLAY_TASK_MISMATCH")
            if previous is not None:
                observation["previous"] = previous
        else:
            input_run = new_run(run/"input")
            observation = capture_decision(config, input_run, args.task, previous)
        write_json(run/"observation.json", observation)
        backend = (CodexBackend(model=args.model, executable=backend_config["executable"],
                                provider=backend_config.get("provider"),
                                timeout_s=backend_config["timeout_s"])
                   if args.backend == "codex" else AstraBackend())
        backend_run = new_run(run/"decision")
        reply = backend.decide(observation, backend_run)
        action, metadata = reply.proposal, reply.metadata
        write_json(run/"proposal.json", action)
        validation = assess_decision(action, observation, policy, time.time(),
                                     generated_at=metadata.get("finished_at"),
                                     execution_readiness=executor.execution_readiness())
    except BackendFailure as exc:
        metadata = exc.metadata
        validation = rejected([exc.code])
    except Exception as exc:
        validation = rejected(["SHADOW_PIPELINE_ERROR:"+type(exc).__name__])
    execution = executor.submit(action, validation)
    write_json(run/"validation.json", validation)
    write_json(run/"executor.json", execution)
    summary = {
        "run": str(run), "backend": args.backend, "model": args.model,
        "observation_id": observation.get("observation_id") if observation else None,
        "image_count": len(observation.get("cameras", [])) if observation else 0,
        "capture_span_ms": observation.get("capture_span_ms") if observation else None,
        "inference_latency_s": metadata.get("inference_latency_s"),
        "proposal": action, "safety": validation, "execution": execution,
        "previous": observation.get("previous") if observation else None
    }
    write_json(run/"summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if validation["decision"] in ("PASS_NOOP", "PASS_EXECUTABLE") else 2

if __name__ == "__main__":
    sys.exit(main())
