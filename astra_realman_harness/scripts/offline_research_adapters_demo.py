#!/usr/bin/env python3
"""OFFLINE ONLY: unchanged runner + real isolated processes + test fake executor.
No SAPIEN instantiation, native subagents, real model or hardware. No online fallback.
"""
import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(BASE/'tests')]
from scripts.prepare_research_fake_cli import prepare
from scripts import run_research_platform as runner
from platform_v1.owner import Owner
from research_fixtures import FakeBackend


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--scenario',choices=('h8','async_ea'),default='h8');a=p.parse_args()
    root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    launcher=prepare(root/'fake_cli')
    config=launcher.parent.parent/'fixture.json';data=json.loads(config.read_text());data['delay_ms']=600;config.write_text(json.dumps(data))
    assets=root/'fake_assets';assets.mkdir();(assets/'asset_manifest.json').write_text('{"source":"OFFLINE_FIXTURE_NO_PHYSICS"}')
    async_ea=a.scenario=='async_ea';cap=2 if async_ea else 3
    args=SimpleNamespace(assets=assets,output=root/'run',program=BASE/'examples/research_platform'/('async_ea_transport_fixture.py' if async_ea else 'research_adapter_client.py'),
        source='ENGINEERING_REFERENCE' if async_ea else 'RESEARCH_PROGRAM',seed=2,budget_s=120,fake_cli=launcher,enable_real_model=False,model_max_requests=0,
        research_adapters=True,research_fake_attempts=cap)
    def factory(*args,**kwargs):return Owner(*args,backend_factory=FakeBackend,**kwargs)
    with patch('platform_v1.owner.Owner',factory):code=runner.run(args)
    result=json.loads((root/'run/result.json').read_text())
    plans=list((root/'run/private/plans').glob('*.json'))
    plan=json.loads(plans[0].read_text()) if len(plans)==1 else None
    overlap=[]
    if async_ea and code==0:
        events=[json.loads(s) for s in (root/'run/public/events.jsonl').read_text().splitlines()]
        start=next(e['monotonic'] for e in events if e['kind']=='action_begin');end=next(e['monotonic'] for e in events if e['kind']=='execution')
        for row in result['broker_attempts']:
            first=next(s['monotonic'] for s in row['stages'] if s['stage']=='STARTED');last=next(s['monotonic'] for s in row['stages'] if s['stage']=='RETURNED')
            overlap.append({'role':row['role'],'pid':row['pid'],'worker_start':first,'worker_return':last,
                'execution_start':start,'execution_return':end,'overlap_s':max(0,min(last,end)-max(first,start))})
    accepted=(len(overlap)==2 and all(r['overlap_s']>0 for r in overlap) and not plan) if async_ea else (plan and plan['status']=='COMPLETED' and plan['K_completed']==8)
    report={'source':'OFFLINE_FAKE_EXECUTOR_AND_FAKE_MODEL_NOT_NATIVE_SUBAGENTS','real_model_calls':0,'hardware_calls':0,'new_physics_episodes':0,
        'status':'PASS' if code==0 and accepted and result['fake_model_attempts']==cap else 'FAIL','scenario':a.scenario,'overlap':overlap,
        'H':plan['plan']['H'] if plan else next((r['parsed']['result']['H'] for r in result.get('broker_attempts',[]) if r['role']=='action' and r.get('parsed')),None),
        'K':plan['K_completed'] if plan else 0,
        'fake_score':'NOT_PHYSICAL_ACCEPTANCE','all_artifacts':'run/private; public only for independent caller'}
    (root/'OFFLINE_ACCEPTANCE.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
