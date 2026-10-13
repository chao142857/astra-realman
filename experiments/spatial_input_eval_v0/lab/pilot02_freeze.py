#!/usr/bin/env python3
"""Seal zero-generation deliverables and an inert future order; never dispatches a job."""
import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from spatial_eval.schema import write
from spatial_eval.geometry import axes,corners,dot
from pilot02_specs import specs

MODULE=Path(__file__).resolve().parents[1]
REPO=MODULE.parents[1]
BASE='b103ee5577f6a3805ae18984dee9157ffa328849'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path): return json.loads(Path(path).read_text())

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    preview=MODULE/'evidence/pilot02_preview_20261013';suite=preview/'suite_v2'
    acceptance=load(preview/'acceptance_v2/acceptance.json');assert acceptance['status']=='PASS'
    assert load(preview/'visual_review.json')['status'].startswith('PASS')
    tests=load(preview/'offline_test_summary.json')
    assert tests['new_tests']=={'total':26,'passed':26,'modules':{'test_pilot01_analysis':5,'test_pilot01_replay':4,'test_pilot02':17}}
    assert tests['status']=='PASS_NEW_TESTS_WITH_LEGACY_PLATFORM_FIXTURE_FAILURE'
    assert tests['full_suite']=={'total':94,'passed':93,'failed':1,'log':'full_offline_tests.log','sha256':sha(preview/'full_offline_tests.log')}
    probe=load(preview/'mac_socket_probe.json')
    assert probe['checks'][0]['result']=='timeout' and probe['checks'][1]['result']=='ConnectionRefusedError'
    # No baseline tracked path may change; new deliverables are allowed.
    diff=subprocess.check_output(['git','diff','--name-status',BASE,'--'],cwd=REPO,text=True)
    assert all(line.startswith('A\t') for line in diff.splitlines()), 'BASELINE_TRACKED_FILE_CHANGED'
    ledgers={}
    for name in ('pilot01_20261013','pilot01_parallel180_20261013'):
        path=MODULE/'evidence'/name/'ledger.json';rel=path.relative_to(REPO)
        original=subprocess.check_output(['git','show',BASE+':'+str(rel)],cwd=REPO)
        assert hashlib.sha256(original).hexdigest()==sha(path)
        ledgers[str(rel)]={'sha256':sha(path),'unchanged':True}
    write(a.output/'preservation_and_budget.json',{'baseline_commit':BASE,'baseline_tracked_files_unchanged':True,'test_status':tests,
            'historical_ledgers':ledgers,'new_generation_budget':0,'new_generation_dispatches':0,
            'old_next_or_wave_executed':False,'hardware_connections':0,
            'scope':'offline analysis, private replay, actual simulation capture, fixture tests and inert schedule'})
    design=specs(); first=['A','C','C','A','A','C','C','A','A','C']; order=[]; gaps=[]
    for i,(s,f) in enumerate(zip(design,first)):
        folder=suite/s['scene_id']; snap=load(folder/'snapshot.json'); gt=snap['ground_truth']
        for cond in ([f,'C' if f=='A' else 'A']):
            condition={'A':'RGB_MULTI_VIEW','C':'RGB_ORACLE_3D'}[cond]; context=folder/'model_inputs'/condition/'context.json'; c=load(context)
            assert s['scene_id'] not in json.dumps(c)
            order.append({'planned_order':len(order)+1,'scene_id_private_catalog_only':s['scene_id'],'task_id':'plan','condition':condition,
                          'input_directory':str(context.parent.relative_to(MODULE)),'context_sha256':sha(context),
                          'rgb_sha256':[x['sha256'] for x in c['attachments']],
                          'output_schema_sha256':hashlib.sha256(json.dumps(c['output_schema'],sort_keys=True).encode()).hexdigest()})
        if s['family'] in ('A_PLACEMENT_MARGIN','C_FREE_YAW'):
            blocks={b['id']:b for b in gt['obstacles']};basis=axes(blocks['block_x_minus']['quaternion_wxyz'])
            widths=[]
            for axis,label in enumerate(('x','y')):
                lo=max(dot(p,basis[axis]) for p in corners(blocks['block_'+label+'_minus']))
                hi=min(dot(p,basis[axis]) for p in corners(blocks['block_'+label+'_plus']))
                widths.append(hi-lo)
            size=gt['objects'][0]['size_m']
            gaps.append({'scene_id':s['scene_id'],'family':s['family'],'nominal_A_per_side_gap_mm':1000*s['design']['nominal_per_side_gap_m'] if s['family'].startswith('A') else '',
                         'readback_opening_x_mm':1000*widths[0],'readback_opening_y_mm':1000*widths[1],
                         'aligned_per_side_gap_x_mm':500*(widths[0]-size[0]),'aligned_per_side_gap_y_mm':500*(widths[1]-size[1]),
                         'required_SAT_axis_clearance_mm':2})
    with (a.output/'physical_opening_gaps.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(gaps[0]));w.writeheader();w.writerows(gaps)
    write(a.output/'future_ac_order.json',{'status':'FROZEN_PLAN_ONLY_NOT_A_LEDGER','generation_authorized':False,'current_request_budget':0,
        'planned_inputs':20,'sample_selection':'All 10 predetermined geometry variants; no selection based on model outputs',
        'first_condition_counts':{'A':5,'C':5},'ordered_samples':order,
        'future_protocol':{'model':'gpt-6-astra','reasoning':'medium','provider':'openai','ephemeral':True,'client_deadline_s':180,
            'concurrency':1,'backend':'Original Mac ChatGPT SSH bridge, production bridge unchanged',
            'cache_policy':'Record cache tokens; do not force warmup or extra calls; report paired no-cache subset',
            'retry_policy':'No automatic retries; timeout/unknown completion/transport/invalid JSON/parameter or isolation drift stops batch; legal JSON geometry failure is retained'},
        'before_any_future_dispatch':['New explicit generation authorization and new budget record independent of Pilot01',
            'Independent Pilot02 adapter/runner must validate public task_policy; legacy MacBridgeAdapter rejects this extra context key',
            'Offline fixture acceptance of that adapter and exact original command/model flags; never drop policy to bypass validation',
            'Use pilot02_contract.score, never V0 scorer alone; verify frozen hashes and non-generating transport health'],
        'parallel8':'Not part of this experiment freeze. A future change requires a separate preregistered execution amendment before generation.'})
    protected={}
    # Include all source/tests/contracts and all final rendered inputs/GT, not Python caches.
    paths=list((MODULE/'lab').glob('pilot02_*.py'))+[MODULE/'lab/robotwin_scene_setup.py',MODULE/'lab/render_scenes.py',MODULE/'lab/verify_suite.py',MODULE/'lab/replay_pilot01.py',MODULE/'lab/analyze_pilot01.py',MODULE/'lab/plot_pilot01_analysis.py']
    paths+=list((MODULE/'spatial_eval').glob('*.py'))+list((MODULE/'schema').glob('*.json'))
    paths+=list((MODULE/'tests').glob('*.py'))+[REPO/'astra_realman_harness/scripts/codex_astra_mac_bridge.py',REPO/'astra_realman_harness/scripts/structured_outputs.py']
    paths+=list(preview.rglob('*'))
    paths += [preview/'visual_review.json',preview/'full_offline_tests.log',MODULE/'docs/PILOT02_OFFLINE.md']
    paths += list((MODULE/'evidence/pilot01_analysis_20261013').rglob('*'))+list((MODULE/'evidence/pilot01_replay_20261013').rglob('*'))
    for path in sorted(set(paths)):
        if path.is_file() and '__pycache__' not in path.parts:protected[str(path.relative_to(REPO))]=sha(path)
    write(a.output/'artifact_seal.json',{'algorithm':'SHA256','baseline_commit':BASE,'status':'FROZEN_BEFORE_ANY_PILOT02_MODEL_CALL','test_caveat':'New26/26 pass; full local suite93/94, one documented legacy macOS bound-socket fixture failure; lab full-suite completion unknown',
          'entries':protected,'entry_count':len(protected),'future_order_sha256':sha(a.output/'future_ac_order.json'),
          'scorer':'lab/pilot02_contract.py score: V0 continuous SAT + region containment + explicit positive-z upright rule; no reference answer matching'})
    print('PASS: baseline preserved; new26/26, full local93/94 (documented legacy socket fixture); offline data/policy/scoring/order frozen; generations=0')

if __name__=='__main__':main()
