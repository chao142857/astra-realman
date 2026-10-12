"""Offline runner. Real API mode requires an explicit flag and a finite call budget."""
import argparse
import hashlib
from pathlib import Path
from .schema import CONDITIONS, write, read, parse_prediction
from .inputs import load_snapshot, build_input
from .scoring import evaluate
from .adapter import infer, preflight
from .report import reports


def assess_response(response, snapshot, task):
    raw=response.get('raw','');prediction=None;errors=[]
    # A missing response or failed transport is not evidence of a model spatial decision.
    infrastructure=(response.get('return_code')!=0 or
                    (response.get('error') and not response['error'].startswith('LOCAL_OUTPUT_VALIDATION:')))
    if infrastructure:
        errors.append('MODEL_TRANSPORT_ERROR:'+str(response.get('error') or 'CLI_EXIT_'+str(response.get('return_code'))))
    if raw:
        try:
            prediction=parse_prediction(raw,task);parse_status='VALID'
        except (ValueError,TypeError,KeyError) as exc:
            parse_status='INVALID';errors.append('JSON_PARSE_OR_SCHEMA:'+str(exc))
    else:
        parse_status='NO_MODEL_RESPONSE';errors.append('NO_MODEL_RESPONSE')
    if response.get('error','') and response['error'].startswith('LOCAL_OUTPUT_VALIDATION:'):
        errors.append('AUTHORITATIVE_VALIDATION:'+response['error']);prediction=None
    if infrastructure or not raw:
        evaluation={'status':'NOT_SCORED','score':None,'constraints':{},'error_types':[]}
    elif prediction is None:
        evaluation={'status':'SCORED' if snapshot['ground_truth'] is not None else 'NOT_SCORED',
                    'score':0. if snapshot['ground_truth'] is not None else None,'constraints':{},'error_types':[]}
    else:evaluation=evaluate(snapshot,task,prediction)
    return {'parse_status':parse_status,'prediction':prediction,'score_status':evaluation['status'],
            'score':evaluation['score'],'evaluation':evaluation,'error_types':errors+evaluation['error_types']}


def rescore(paths, source, output):
    """Re-evaluate immutable recorded responses; never launches model or simulation."""
    snapshots={s['scene_id']:s for s in [load_snapshot(p) for p in paths]}
    source=Path(source).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    manifest=read(source/'run_manifest.json')
    if manifest['snapshot_sha256']!=[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]:
        raise ValueError('RESCORE_SNAPSHOT_HASH_MISMATCH')
    rows=read(source/'results.json')
    import os
    for row in rows:
        snapshot=snapshots[row['scene_id']];task=next(t for t in snapshot['task'] if t['task_id']==row['task_id'])
        artifact=source/row['artifact'];response=read(artifact/'response.json')
        row.update(assess_response(response,snapshot,task))
        row['artifact']=os.path.relpath(artifact,output)
    reports(rows,output)
    write(output/'run_manifest.json',{'mode':'RESCORE_ONLY','new_model_attempts':0,'source_run':str(source),
         'source_manifest_sha256':hashlib.sha256((source/'run_manifest.json').read_bytes()).hexdigest()})
    return rows


def run(paths, output, conditions, *, real=False, max_real_calls=0, fixture_response=None):
    if len(set(conditions))!=len(conditions):raise ValueError('DUPLICATE_CONDITIONS')
    if real and fixture_response:raise ValueError('FIXTURE_CANNOT_ENTER_REAL_MODEL')
    snapshots=[load_snapshot(p) for p in paths]
    if len({s['scene_id'] for s in snapshots})!=len(snapshots):raise ValueError('DUPLICATE_SCENE_ID')
    jobs=[(s,t,c) for s in snapshots for t in s['task'] for c in conditions]
    if real and (max_real_calls<=0 or len(jobs)>max_real_calls):raise ValueError('EXPLICIT_REAL_CALL_BUDGET_REQUIRED')
    if real:
        for s,t,c in jobs:build_input(s,t,c) # All conditions must be available before spending any request.
    if real and any(s['provenance']=='SYNTHETIC_ANALYTICAL_TEST_NOT_SIMULATION' for s in snapshots):raise ValueError('SYNTHETIC_FIXTURE_REAL_CALL_FORBIDDEN')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    rows=[]
    for i,(s,t,c) in enumerate(jobs):
        name='sample-%04d'%i;folder=output/name
        row={'scene_id':s['scene_id'],'task_id':t['task_id'],'condition':c,
             'source':'REAL_ASTRA_ATTEMPT' if real else 'MOCK_NOT_ASTRA','model_calls':0,
             'image_count':len(s['observations']['rgb']),'geometry_source':None,'raw_output':'','prediction':None,
             'parse_status':'NOT_ATTEMPTED','score_status':'NOT_SCORED','score':None,'latency_s':None,
             'token_usage':None,'error_types':[],'artifact':name,'task_prompt_sha256':None}
        try:
            context,manifest,images=build_input(s,t,c);row.update(manifest)
            response=infer(context,images,folder,real=real,fixture_response=fixture_response)
            row.update(source=response['source'],model_calls=response['model_calls'],raw_output=response.get('raw',''),
                       latency_s=response['wall_latency_s'],token_usage=response.get('usage'))
            row.update(assess_response(response,s,t))
            write(folder/'evaluation.json',row['evaluation'])
        except (ValueError,TypeError,KeyError,FileNotFoundError,ImportError) as exc:
            row['error_types'].append('INPUT_OR_DEPENDENCY:'+type(exc).__name__+':'+str(exc))
        rows.append(row);reports(rows,output)
        # No automatic retry after a real failure; retain completed rows and stop remaining requests.
        if real and (row['parse_status']!='VALID' or any(x.startswith(('MODEL_TRANSPORT_ERROR','AUTHORITATIVE_VALIDATION','INPUT_OR_DEPENDENCY')) for x in row['error_types'])):break
    write(output/'run_manifest.json',{'real_enabled':real,'max_real_calls':max_real_calls,'planned_samples':len(jobs),
         'recorded_samples':len(rows),'model_calls':sum(r['model_calls'] for r in rows),
         'completed':len(rows)==len(jobs),'snapshot_sha256':[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]})
    return rows


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('--snapshot',type=Path,nargs='+',required=True);r.add_argument('--output',type=Path,required=True)
    r.add_argument('--conditions',nargs='+',choices=CONDITIONS,default=[CONDITIONS[0],CONDITIONS[2]])
    r.add_argument('--real',action='store_true');r.add_argument('--max-real-calls',type=int,default=0)
    r.add_argument('--fixture-response',type=Path)
    q=sub.add_parser('rescore');q.add_argument('--snapshot',type=Path,nargs='+',required=True);q.add_argument('--source-run',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('preflight');q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('import-archive');q.add_argument('--archive',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('fixtures');q.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.command=='run':
        rows=run(a.snapshot,a.output,a.conditions,real=a.real,max_real_calls=a.max_real_calls,fixture_response=a.fixture_response)
        print(f'recorded={len(rows)} real_model_attempts={sum(r["model_calls"] for r in rows)} output={a.output}')
        return int(any(r['parse_status']!='VALID' or any(e.startswith(('MODEL_TRANSPORT_ERROR','AUTHORITATIVE_VALIDATION','INPUT_OR_DEPENDENCY')) for e in r['error_types']) for r in rows))
    if a.command=='rescore':
        print('rescored=',len(rescore(a.snapshot,a.source_run,a.output)),'new_model_attempts=0');return 0
    if a.command=='preflight':
        result=preflight(a.output);print(result['status']);return int(result['status']!='PASS')
    if a.command=='import-archive':
        from .data import import_archive
        print(import_archive(a.archive,a.output))
    if a.command=='fixtures':
        from .data import fixtures
        print(fixtures(a.output))
    return 0

if __name__=='__main__':raise SystemExit(main())
