#!/usr/bin/env python3
"""FAKE MODEL + FABRICATED DEPTH CONTRACT DEMO; no real inference or scene."""
import argparse
import json
from pathlib import Path
import sys
import shutil
import tempfile
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1];sys.path[:0]=[str(BASE),str(BASE/'tests')]
from scripts.prepare_research_fake_cli import prepare
from sim_skills.full_pnp.infer_process import InferConfig
from research_fixtures import owner
from lwh_integration_fixtures import fused_fixture,action_fixture,fake_world_check

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    # Existing fake infer isolation deliberately forbids the workspace ancestor.
    runtime=tempfile.TemporaryDirectory(prefix='lwh-demo-cli-')
    cli=prepare(Path(runtime.name)/'fake_cli')
    shutil.copytree(Path(runtime.name)/'fake_cli',a.output/'fake_cli_reference')
    o=owner(a.output/'owner',InferConfig(str(cli),fixture=True),cap=2)
    try:
        obs=o.observe();w,_,e=fused_fixture(o,obs);action=action_fixture(o,w,obs)
        if action['status']!='READY':raise RuntimeError('FIXTURE_ACTION_FAILED')
        plan=o.research.supervisor.from_broker(action['request_id'])
        (a.output/'W0.SYNTHETIC.json').write_text(json.dumps(w,indent=2)+'\n')
        # No task-evidence patch: show the genuine generic-admission gap.
        with patch.object(o.research.world,'submit',side_effect=fake_world_check(o.research)):
            o.research.supervisor.step(plan['plan_id'])
            plan=o.research.supervisor.step(plan['plan_id'])
        report={'status':'PASS' if plan['reason']=='TASK_EVIDENCE_UNKNOWN' and not o.b.commands else 'FAIL',
            'source':'SYNTHETIC_CONTRACT_ONLY_NOT_LEARNED_OUTPUT_OR_PHYSICAL_EPISODE',
            'real_astra_calls':0,'hardware_calls':0,'new_physics_episodes':0,'learned_forward_passes':0,
            'fake_broker_calls':o.research.broker.calls,'native_subagent_acceptance':'NOT_VERIFIED',
            'plan':plan,'semantic_evidence_id':e['evidence_id'],
            'model_raw_artifacts':'owner/private/research_broker; FAKE_MODEL_RAW only',
            'claims':'schema, provenance and refusal routing only'}
        (a.output/'DEMO_REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='plan'},indent=2))
        return 0 if report['status']=='PASS' else 1
    finally:o.close();runtime.cleanup()

if __name__=='__main__':raise SystemExit(main())
