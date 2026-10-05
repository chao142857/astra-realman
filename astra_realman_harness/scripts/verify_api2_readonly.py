#!/usr/bin/env python3
"""Explicit two-arm API2 compatibility diagnostic; no cameras/API/proposals/motion."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True
import hashlib
import json
import os
import time
import traceback
import uuid
from io_utils import ROOT, new_run, read_json, write_json
from realman_api2_readonly import SDKReadOnly, SDK_PACKAGE, SDK_LIBRARY, SDK_SOURCE
from legacy_state_compare import LEGACY_SOURCE, read_legacy, compare

def main():
    run = new_run(ROOT/"logs"/("api2-readonly-"+time.strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8]))
    os.chdir(run)  # Any library-relative diagnostic output stays in alex.
    cfg = read_json(ROOT/"config/lab.json")
    source_paths = [SDK_SOURCE, SDK_PACKAGE/"rm_ctypes_wrap.py", SDK_LIBRARY, LEGACY_SOURCE,
                    Path("/home/tongji/aloha/shadow_rm_aloha/config/rm_left_arm.yaml"),
                    Path("/home/tongji/aloha/shadow_rm_aloha/config/rm_right_arm.yaml")]
    fingerprints = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    write_json(run/"source_fingerprints.json", fingerprints)
    report = {"scope": "two-arm read-only SDK compatibility diagnostic; left-only proposal policy unchanged",
              "arms": {}, "motion_commands_sent": 0, "api_called": False, "error_clear_attempted": False,
              "sdk_source": str(SDK_SOURCE), "sdk_library": str(SDK_LIBRARY)}
    adapter = SDKReadOnly(run)
    try:
        with adapter:
            for arm in ("left", "right"):
                endpoint = cfg["devices"]["arms"][arm]
                report["arms"][arm] = {"endpoint": endpoint, "samples": []}
                status = adapter.connect(arm, endpoint["host"], endpoint["port"], dof=6)
                report["arms"][arm]["connection"] = status
                write_json(run/(arm+"-connection.json"), status)
                if not status["connected"]:
                    continue
                for i in range(3):
                    sample = {"index": i+1}
                    try:
                        sample["legacy_before"] = read_legacy(endpoint["host"], endpoint["port"])
                        sample["sdk"] = adapter.snapshot(arm)
                        sample["legacy_after"] = read_legacy(endpoint["host"], endpoint["port"])
                        sample["comparison"] = compare(sample["sdk"]["canonical"],
                                                        sample["legacy_before"], sample["legacy_after"])
                    except Exception as exc:
                        sample["diagnostic_error"] = {"type": type(exc).__name__, "message": str(exc),
                                                      "traceback": traceback.format_exc()}
                    write_json(run/(arm+"-sample-%02d.json" % (i+1)), sample)
                    report["arms"][arm]["samples"].append(sample)
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc),
                             "traceback": traceback.format_exc()}
    report["sdk_events"] = adapter.events
    report["sdk_files_unchanged"] = all(hashlib.sha256(p.read_bytes()).hexdigest()==fingerprints[str(p)] for p in source_paths)
    report["compatible_for_tested_reads"] = (
        "failure" not in report and len(report["arms"])==2 and
        all(s["connection"]["connected"] and len(s["samples"])==3 and
            all(x.get("sdk",{}).get("canonical") is not None and
                x.get("comparison",{}).get("status")=="CONSISTENT" for x in s["samples"])
            for s in report["arms"].values()) and
        all(e.get("return_code")==0 for e in adapter.events if e["function"] in ("rm_init","rm_delete_robot_arm","rm_destroy")))
    write_json(run/"summary.json", report)
    print("SUMMARY",run/"summary.json")
    for arm,data in report["arms"].items():
        last=data["samples"][-1] if data["samples"] else {}
        print(json.dumps({"arm":arm,"connected":data["connection"]["connected"],
                          "canonical":last.get("sdk",{}).get("canonical"),
                          "comparison":last.get("comparison"),
                          "failure":last.get("diagnostic_error")},ensure_ascii=False))
    print("COMPATIBLE_FOR_TESTED_READS", report["compatible_for_tested_reads"])
    return 0 if report["compatible_for_tested_reads"] else 2

if __name__=="__main__":
    sys.exit(main())
