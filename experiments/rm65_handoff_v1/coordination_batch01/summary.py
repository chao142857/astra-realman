"""Descriptive campaign statistics, retaining censored and infrastructure cases."""
import csv
import json
from pathlib import Path


def summarize(root):
    root=Path(root);state=json.loads((root/'ledger.json').read_text());rows=[]
    for entry in state['episodes']:
        f=root/entry['episode_id']/'episode.json'
        e=json.loads(f.read_text()) if f.exists() else dict(entry)
        if e['status']=='RUNNING':e['status']='INFRASTRUCTURE_FAILURE'
        usage={};inference=0.
        for p in sorted((root/entry['episode_id']).glob('decision_*/response.json')):
            r=json.loads(p.read_text());inference+=r.get('wall_latency_s',0.)
            for k,v in (r.get('usage') or {}).items():
                if type(v) is int:usage[k]=usage.get(k,0)+v
        rows.append({**{k:entry[k] for k in ('episode_id','condition_id','repeat')},'status':e['status'],
                     'decisions':e.get('decisions',0),'client_dispatches':e.get('client_dispatches',0),
                     'executed_action_groups':e.get('executed_action_groups',0),
                     'numeric_refusals':e.get('numeric_refusals',0),'episode_wall_s':e.get('episode_wall_s'),
                     'sim_time_s':e.get('sim_time_s'),'inference_wall_s':inference,'usage':usage,
                     'score':e.get('score'),'rejections':e.get('rejections',[]),
                     'safety_stop':e.get('safety_stop',False),'corrections_after_refusal':e.get('corrections_after_refusal',[])})
    groups={}
    for condition in [*dict.fromkeys(r['condition_id'] for r in rows),'ALL']:
        selected=[r for r in rows if condition=='ALL' or r['condition_id']==condition]
        started=[r for r in selected if r['status']!='NOT_STARTED']
        evaluable=[r for r in selected if r['status'] in ('SUCCESS','TASK_FAILURE')]
        statuses={s:sum(r['status']==s for r in selected) for s in ('SUCCESS','TASK_FAILURE','BUDGET_TRUNCATED','INFRASTRUCTURE_FAILURE','NOT_STARTED')}
        timed=[r for r in started if r['episode_wall_s'] is not None]
        groups[condition]={'counts':statuses,'planned_episodes':len(selected),'started_episodes':len(started),
            'success_per_started':statuses['SUCCESS']/len(started) if started else None,
            'success_per_uncensored_evaluable':statuses['SUCCESS']/len(evaluable) if evaluable else None,
            'mean_decisions_per_started':sum(r['decisions'] for r in started)/len(started) if started else None,
            'mean_client_dispatches_per_started':sum(r['client_dispatches'] for r in started)/len(started) if started else None,
            'mean_inference_wall_s':sum(r['inference_wall_s'] for r in started)/len(started) if started else None,
            'mean_sim_time_s':sum(r['sim_time_s'] or 0. for r in started)/len(started) if started else None,
            'mean_episode_wall_s':sum(r['episode_wall_s'] for r in timed)/len(timed) if timed else None}
    result={'campaign_id':state['campaign_id'],'source':'MOCK_NOT_ASTRA' if state['offline_fixture'] else 'REAL_ASTRA',
            'status':state['status'],'reserved_budget':state['reserved_budget'],'elapsed_wall_s':state['elapsed_wall_s'],
            'groups':groups,'episodes':rows,'interpretation':'Descriptive fixed-scene results only. Budget/time truncation and infrastructure failures are separate; no replacement episodes.'}
    (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);print(json.dumps(summarize(p.parse_args().root),indent=2))
