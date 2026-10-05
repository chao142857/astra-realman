"""Default: read-only preflight. --execute-once is one fixed operator-authorized step."""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, new_run, write_json
from realman_api2_readonly import SDKReadOnly
from supervised_step import EXACT_ACTION, validate_step, OneShotExecutor
from supervised_live import SupervisedPort, CLAIM

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-once", action="store_true")
    args = parser.parse_args()
    if args.execute_once and CLAIM.exists():
        raise SystemExit("REJECT: persistent one-shot claim already exists; never retry.")
    run = new_run(ROOT / "logs" / ("supervised-step-" + time.strftime("%Y%m%dT%H%M%S") +
                                  "-" + uuid.uuid4().hex[:8]))
    summary = {"run": str(run), "action": EXACT_ACTION, "mode": "execute_once" if args.execute_once else "preflight",
               "status": "REJECT", "motion_command_attempts": 0, "gripper_commands_sent": 0}
    port = None
    try:
        with SDKReadOnly(run) as session:
            for arm, host in (("left", "192.168.1.19"), ("right", "192.168.1.18")):
                if not session.connect(arm, host, 8080)["connected"]:
                    raise RuntimeError("READ_ONLY_CONNECT_FAILED:" + arm)
            port = SupervisedPort(session, run, execute=args.execute_once)
            evidence = port.prepare()
            safety = validate_step(EXACT_ACTION, evidence, time.time())
            write_json(run / "preflight-safety.json", safety)
            summary["safety"] = safety
            summary["status"] = safety["outcome"]
            if args.execute_once and safety["outcome"] == "PASS_EXECUTABLE":
                result = OneShotExecutor(port).execute(EXACT_ACTION, evidence)
                write_json(run / "executor-result.json", result)
                summary["status"] = result["status"]
                summary["executor"] = result
            summary["motion_command_attempts"] = port.hardware_calls_attempted
            if port.before_dispatch is not None:
                summary["before"] = port.before_dispatch
            if port.after_snapshot is not None:
                summary["after"] = port.after_snapshot["arms"]["left"]
                if port.before_dispatch is not None:
                    old = port.before_dispatch["ee_pose"]["xyz_m"]
                    new = summary["after"]["ee_pose"]["xyz_m"]
                    summary["measured_delta_m"] = [b-a for a,b in zip(old,new)]
    except BaseException as exc:
        summary.update(status="EXECUTION_UNCERTAIN" if port and port.hardware_calls_attempted else "REJECT",
                       exception_type=type(exc).__name__, exception=str(exc),
                       motion_command_attempts=port.hardware_calls_attempted if port else 0)
    write_json(run / "summary.json", summary)
    print(json.dumps({key: summary[key] for key in (
        "run", "mode", "status", "motion_command_attempts", "gripper_commands_sent",
        "measured_delta_m", "exception") if key in summary}, ensure_ascii=False))
    return 0 if summary["status"] in ("PASS_EXECUTABLE", "EXECUTED_VERIFIED") else 2

if __name__ == "__main__":
    raise SystemExit(main())
