#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import time,uuid
from io_utils import ROOT,new_run,read_json,write_json
import harness

base=new_run(ROOT/"logs"/("offline-"+time.strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8]))
harness.main(["offline-observation","--task","SYNTHETIC cube pick and place test","--out",str(base/"input")])
obs=base/"input/observation.json"
common=["--observation",str(obs),"--provider","fixture"]
positive=harness.main(["dry-run",*common,"--config",str(ROOT/"fixtures/synthetic_policy.json"),"--out",str(base/"synthetic_pass")])
blocked=harness.main(["dry-run",*common,"--out",str(base/"lab_blocked")])
replay=harness.main(["dry-run","--observation",str(obs),"--provider","replay",
                     "--proposal",str(base/"synthetic_pass/proposal.json"),
                     "--config",str(ROOT/"fixtures/synthetic_policy.json"),"--out",str(base/"replay_pass")])
api=harness.main(["dry-run","--observation",str(obs),"--provider","api","--out",str(base/"api_unconfigured")])
report={"source":"OFFLINE_SYNTHETIC_ONLY","synthetic_exit":positive,"uncalibrated_lab_exit":blocked,
        "replay_exit":replay,"unconfigured_api_exit":api,
        "motion_commands_sent":0,"external_api_called":False,
        "expected_results_met":(positive,blocked,replay,api)==(0,2,0,2)}
write_json(base/"summary.json",report)
print("SUMMARY",base/"summary.json")
sys.exit(0 if report["expected_results_met"] else 1)
