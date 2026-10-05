#!/usr/bin/env python3
"""Three observations on ONE persistent four-camera session. No API/motion."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
import uuid
from io_utils import ROOT, new_run, read_json, write_json
from observation import capture
from camera_session import CameraSession
import harness

def main():
    base = new_run(ROOT/"logs"/("real-"+time.strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8]))
    cfg = read_json(ROOT/"config/lab.json")
    serials = [c["serial"] for c in cfg["devices"]["cameras"]]
    enabled_arms = list(cfg["safety"]["allowed_arms"])
    reports = []
    with CameraSession(cfg["devices"]["cameras"]) as session:
        for i in range(3):
            folder = base if i == 0 else new_run(base/("sample-%02d" % (i+1)))
            run = new_run(folder/"input")
            obs = capture(cfg, run, "Read-only state semantics and +5 mm work-Z fixture; no execution.",
                          serials, enabled_arms, camera_session=session)
            dry_exit = harness.main(["dry-run", "--observation", str(run/"observation.json"),
                                     "--provider", "fixture", "--out", str(folder/"dryrun")])
            validation = read_json(folder/"dryrun/validation.json")
            reports.append({
                "observation": str(run/"observation.json"), "dry_run_exit": dry_exit,
                "camera_count": len(obs["cameras"]), "camera_capture": obs["camera_capture"],
                "capture_span_ms": obs["capture_span_ms"], "capture_failures": obs["capture_failures"],
                "robot_states": {a: {"available": s["available"], "err": s.get("controller_errors"),
                                     "canonical": s.get("canonical")} for a,s in obs["robot"]["arms"].items()},
                "decision": validation["decision"], "safety_errors": validation.get("errors", []),
            })
    report = {
        "observation_source": "REAL_CAMERA_AND_PASSIVE_ROBOT_STATE",
        "proposal_source": "SYNTHETIC_FIXTURE_NOT_ASTRA", "samples": reports,
        "enabled_arms": enabled_arms, "fixture_arm": cfg["fixture_arm"],
        "pipeline_start_count": dict(session.starts), "camera_session_id": session.session_id,
        "external_api_called": False, "motion_commands_sent": 0, "error_clear_attempted": False,
        "expected_motion_rejection": all(r["decision"] == "REJECTED" for r in reports),
    }
    write_json(base/"summary.json", report)
    print("SUMMARY", base/"summary.json")
    print("CAPTURE_SPANS_MS", [r["capture_span_ms"] for r in reports])
    print("PIPELINE_START_COUNT", session.starts)
    return 0 if report["expected_motion_rejection"] and all(not r["capture_failures"] for r in reports) else 2

if __name__ == "__main__":
    sys.exit(main())
