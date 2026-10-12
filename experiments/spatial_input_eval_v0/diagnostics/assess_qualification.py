"""Offline acceptance of a recorded attempt; no network or model invocation."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spatial_eval.cli import assess_response
from spatial_eval.inputs import load_snapshot
from spatial_eval.schema import read, write


def observable_progress(events):
    return [e for e in events if e.get('type') in ('response.output_text.delta', 'response.reasoning_summary_text.delta')
            or (e.get('type') in ('item.started','item.updated','item.completed')
                and e.get('item',{}).get('type') in ('reasoning','agent_message'))]


def assess(run, snapshot_path):
    run=Path(run);snapshot=load_snapshot(snapshot_path)
    row=read(run/'results.json')[0]
    response=read(run/row['artifact']/'response.json')
    task=next(t for t in snapshot['task'] if t['task_id']==row['task_id'])
    events=[json.loads(line) for line in response.get('events','').splitlines() if line]
    assessed=assess_response(response,snapshot,task)
    completion=any(e.get('type')=='turn.completed' for e in events)
    progress=observable_progress(events)
    nonempty=bool(response.get('raw','').strip())
    return {'status':'PASS' if (completion and nonempty and assessed['parse_status']=='VALID'
              and assessed['score_status']=='SCORED' and not response.get('error')) else 'FAIL',
            'criteria':{'normal_model_completion':completion,'nonempty_real_output':nonempty,
                'strict_json_prediction':assessed['parse_status'],
                'independent_evaluator_executed':True,'independent_score_status':assessed['score_status'],
                'request_response_latency_usage_preserved':all((run/row['artifact']/f).exists() for f in
                    ('request.json','response.json','raw.txt','evaluation.json','model_parameters.json'))
                    and 'wall_latency_s' in response and 'usage' in response},
            'recorded_attempts':read(run/'run_manifest.json')['model_calls'],
            'raw_error':response.get('error'),'latency_s':response['wall_latency_s'],
            'usage':response.get('usage'),'score':assessed['score'],
            'observable_generation_progress_events':progress,
            'routing_errors':[e for e in events if 'routing discovery failed' in json.dumps(e)],
            'event_types':[e.get('type') for e in events],
            'reassessment_matches_saved':assessed['evaluation']==read(run/row['artifact']/'evaluation.json'),
            'new_model_requests_from_assessment':0,
            'interpretation':'Local startup events do not prove server acceptance. Missing progress is not proof of slow reasoning.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=assess(a.run,a.snapshot);write(a.output,result);print(result['status'])
