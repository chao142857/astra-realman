#!/usr/bin/env python3
"""Archive offline protocol acceptance; production services cannot be contacted."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from spatial_eval.adapter import PARAMETERS, prepare
from spatial_eval.cli import run, assess_response
from spatial_eval.inputs import load_snapshot, build_input
from spatial_eval.schema import write, read
from spatial_eval.scoring import evaluate
from offline_bridge import fake_bridge, audit


def task_review(paths):
    rows=[]
    for path in paths:
        snapshot=load_snapshot(path);task=snapshot['task'][1];scene=snapshot['scene_id']
        primary=scene in ('lab_s5_placement','lab_s6_held_object_detour')
        row={'scene_id':scene,'task_id':task['task_id'],'kind':task['kind'],
             'first_round_primary_planning':primary,'orientation_choice':'PRESCRIBED',
             'planning_scope':'static geometry; no dynamics, reachability, support or robot control',
             'limitations':['Task-region centers and dimensions are explicitly provided in both A and C.']}
        if primary:
            witness=read(path.parent/'private/planning_witness.json')
            positive=evaluate(snapshot,task,witness);assert positive['success']
            negative=copy.deepcopy(witness)
            if task['kind']=='placement':
                region=next(x for x in snapshot['ground_truth']['regions'] if x['id']==task['constraints']['allowed_region_id'])
                negative['position_m']=region['center_m'];constraint='placement_collision_free'
            else:
                negative['waypoints_m']=[negative['position_m']];constraint='continuous_path_collision_free'
                row['limitations'].append('Any feasible 3D detour is accepted, including over the obstacle; fixed orientation, no optimality requirement.')
            assessed=evaluate(snapshot,task,negative);assert not assessed['constraints'][constraint]
            row.update(private_feasibility_check='PASS',naive_policy_rejection='PASS',rejected_constraint=constraint)
        elif scene=='lab_s4_rotated_fit':
            row['interpretation']='Instructed orientation and geometric fit; not autonomous orientation planning.'
            row['future_variant']={'status':'DEFERRED','task_id':'plan_free_orientation',
                'required_quaternion_wxyz':None,'requirement':'Remove prescribed orientation, let model choose unit quaternion; freeze new A/C pair separately.'}
        else:
            row['interpretation']='Understanding / simple placement control; not primary planning difficulty.'
        rows.append(row)
    return rows


def accept(suite,output):
    output.mkdir(parents=True,exist_ok=False)
    paths=sorted(suite.glob('*/snapshot.json'));assert len(paths)==6
    snapshot=load_snapshot(paths[0]);task=snapshot['task'][0]
    context,_,images=build_input(snapshot,task,'RGB_MULTI_VIEW')
    cases=[]
    with tempfile.TemporaryDirectory(prefix='offline-bridge-token-') as temporary:
        with fake_bridge(temporary) as state, patch('subprocess.Popen',side_effect=AssertionError('NO_REAL_GENERATION_ALLOWED')):
            rows=run(paths,output/'mock_ac',['RGB_MULTI_VIEW','RGB_ORACLE_3D'],transport_adapter=state['adapter'])
            assert len(rows)==24 and all(r['parse_status']=='VALID' and r['model_calls']==0 for r in rows)
            pairs=read(output/'mock_ac/paired_comparison.json');assert len(pairs)==12 and all(p['eligible'] for p in pairs)
            for a,c in zip(state['payloads'][::2],state['payloads'][1::2]):
                ac=copy.deepcopy(c['context']);ac['geometry']=None
                assert ac==a['context'] and a['images']==c['images'] and a['schema']==c['schema']
            success_calls=state['decide_calls']
            for mode in ('invalid-output','parameter-drift','malformed-response','timeout','trickle','busy','auth-failure'):
                state['mode']=mode if mode not in ('busy','auth-failure') else 'success'
                before=state['decide_calls'];name='fault_'+mode
                if mode=='busy':state['busy_lock'].acquire()
                original_token=state['token_file'].read_text()
                if mode=='auth-failure':state['token_file'].write_text('wrong-fixture-token-long-enough')
                try:response=state['adapter'].infer(context,images,output/name,timeout_s=.2 if mode in ('timeout','trickle') else 2)
                finally:
                    if mode=='busy':state['busy_lock'].release()
                    state['token_file'].write_text(original_token)
                assessed=assess_response(response,snapshot,task);write(output/name/'evaluation.json',assessed)
                assert state['decide_calls']-before==1
                if mode=='invalid-output':assert assessed['parse_status']=='INVALID' and assessed['score']==0
                else:assert assessed['score_status']=='NOT_SCORED' and assessed['score'] is None
                cases.append({'case':mode,'status':'PASS','dispatches':1,'retries':0,'score_status':assessed['score_status'],'error':response['error']})
            for mode in ('image-hash','schema'):
                bad=copy.deepcopy(context)
                if mode=='image-hash':bad['attachments'][0]['sha256']='0'*64
                else:bad['output_schema']={'type':'object'}
                before=state['decide_calls']
                try:state['adapter'].infer(bad,images,output/('prewire_'+mode),timeout_s=2)
                except ValueError as exc:reason=str(exc)
                else:raise AssertionError('PREWIRE_VALIDATION_MISSING')
                assert state['decide_calls']==before
                cases.append({'case':mode,'status':'PASS','dispatches':0,'retries':0,'error':reason})
            counters=audit(state)
            # All evidence must be free of the fixture secret, including error responses.
            for p in output.rglob('*'):
                if p.is_file():assert original_token.encode() not in p.read_bytes()
    review=task_review(paths);write(output/'task_review.json',review)
    s5=load_snapshot(next(p for p in paths if 'lab_s5_placement' in str(p)))
    context,manifest,images=build_input(s5,s5['task'][1],'RGB_MULTI_VIEW')
    prepare(context,images,output/'prepared_next_A',real=True) # schema compilation only
    write(output/'prepared_next_A/manifest.json',manifest)
    write(output/'acceptance.json',{'status':'PASS','base_commit':'d9000b3','real_model_calls':0,
        'production_endpoint_requests':0,'success_protocol_samples':success_calls,'paired_tasks':len(pairs),
        'fake_service':counters,'fault_cases':cases,'parameters':PARAMETERS,
        'parity':'same task, RGB, calibration, schema, model parameters and evaluator; only geometry differs',
        'limitations':['Fake responses validate integration only; no Astra capability conclusion.',
            'Current production bridge and reverse tunnel were not started or contacted.',
            'First real valid JSON still requires separate user authorization.']})
    write(output/'artifact_seal.json',{str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(output.rglob('*')) if p.is_file()})
    print('PASS: 24 offline A/C transports, 12 pairs, 9 fault cases; real_model_calls=0')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();accept(args.suite,args.output)
