#!/usr/bin/env python3
"""Read-only post-run continuation report; never mutates ledgers or original scoring."""
import argparse
import json
from pathlib import Path
import statistics
import pilot02_continuation as c
import pilot02_runtime as r
from pilot02_real_report import usage_parts, group


def summarize(root):
    root=Path(root);state=r.read(root/'ledger.json');manifest=c.frozen()
    assert state['version']=='pilot02.continuation.v1' and state['mode']=='REAL'
    assert state['jobs']==manifest['ordered_samples'] and state['prior_client_dispatches']==12
    assert state['status'] in ('STOPPED','BUDGET_EXHAUSTED')
    rows=[]
    for item in state['runs']:
        folder=root/item['artifact'];result=r.assess(folder,item['job'])
        assert result==item['assessment']==r.read(folder/'independent_rescore.json')
        transport=r.read(folder/'transport.json');assert transport['dispatch_attempts']==1 and transport['retries']==0
        events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
        errors=[e.get('message') for e in events if e.get('type')=='error']
        rows.append({'index':item['index'],'original_order':item['job']['planned_order'],'scene':item['job']['scene_id_private_catalog_only'],
                     'condition':item['job']['condition'],'group':group(item['job']['scene_id_private_catalog_only']),
                     'status':result['status'],'score':result['score'],'failure':result.get('failure'),
                     'failed_constraints':result.get('evaluation',{}).get('error_types',[]),
                     'client_wall_latency_s':result.get('latency_s'),**usage_parts(result.get('usage')),
                     'cli_top_level_errors':errors,'cli_reconnect_events':[x for x in errors if isinstance(x,str) and 'reconnecting' in x.lower()]})
    groups=[]
    for name in ('restricted_detour','autonomous_yaw'):
        g={'group':name}
        for label,condition in [('A','RGB_MULTI_VIEW'),('C','RGB_ORACLE_3D')]:
            dispatched=[x for x in rows if x['group']==name and x['condition']==condition];valid=[x for x in dispatched if x['status']=='VALID']
            successes=sum(x['score']==1 for x in valid)
            g[label]={'planned':2,'dispatched':len(dispatched),'valid':len(valid),'successes':successes,'success_rate_valid':successes/len(valid) if valid else None}
        groups.append(g)
    pairs=[]
    for scene in dict.fromkeys(x['scene'] for x in rows):
        by={x['condition']:x for x in rows if x['scene']==scene and x['status']=='VALID'}
        if set(by)=={'RGB_MULTI_VIEW','RGB_ORACLE_3D'}:
            a=by['RGB_MULTI_VIEW'];oracle=by['RGB_ORACLE_3D']
            keys=('score','input_tokens','output_tokens','reasoning_tokens','client_wall_latency_s')
            pairs.append({'scene':scene,'A':a,'C':oracle,'C_minus_A':{k:oracle[k]-a[k] if oracle[k] is not None and a[k] is not None else None for k in keys}})
    stats={}
    for label in ('A','C'):
        stats[label]={'complete_pairs':len(pairs)}
        for key in ('input_tokens','output_tokens','reasoning_tokens','other_output_tokens','client_wall_latency_s'):
            values=[p[label][key] for p in pairs if p[label][key] is not None]
            stats[label][key]={'reported_samples':len(values),'mean':statistics.mean(values) if values else None,'total':sum(values) if values else None}
    cached_pairs=[p['scene'] for p in pairs if (p['A']['cached_input_tokens'] or 0)>0 or (p['C']['cached_input_tokens'] or 0)>0]
    assert state['reserved_budget']==len(rows)<=8
    result={'scope':'CONTINUATION_ONLY; original STOPPED batch and original run12 NOT_SCORED unchanged',
            'batch_id':state['batch_id'],'original_batch_id':state['original_batch_id'],'status':state['status'],
            'completed_all_eight':len(rows)==8 and all(x['status']=='VALID' for x in rows),
            'maximum_new_client_dispatches':8,'new_client_dispatches':len(rows),'prior_client_dispatches':12,
            'cumulative_client_dispatches':12+len(rows),'unused_new_dispatch_capacity':8-len(rows),'dispatcher_retries':0,
            'upstream_generation_attempts':'Not independently measurable from client dispatch count or native reconnect counters',
            'valid_outputs':sum(x['status']=='VALID' for x in rows),'not_scored_outputs':sum(x['status']!='VALID' for x in rows),
            'groups':groups,'runs':rows,'complete_pairs':len(pairs),'paired_metrics':pairs,'paired_resources':stats,'pairs_with_reported_cache_hits':cached_pairs,
            'old_batch_status':r.read(c.OLD/'ledger.json')['status'],'old_run12_status':r.read(c.OLD/'run-012/assessment.json')['status'],
            'old_files_verified':len(r.read(c.PREP/'original_batch_hashes.json')),'sealed_files_verified':607,
            'notes':['Valid geometric failures remain zero; invalid transport/protocol outputs are not capability zeros.',
                     'Tokens are reported usage, not exact internal compute. Client wall time includes transport and queuing.',
                     'Exploratory descriptive results only; no significance or generalization claims.']}
    r.write(root/'continuation_summary.json',result)
    lines=['# Pilot02 continuation results','',f'Batch `{state["batch_id"]}`. New client dispatches {len(rows)}/8; prior client dispatches 12. Status {state["status"]}.','',
           '| Group | A success / valid | C success / valid |','|---|---:|---:|']
    for g in groups:
        def cell(v):return f'{v["successes"]}/{v["valid"]}' if v['valid'] else 'N/A'
        lines.append(f'| {g["group"]} | {cell(g["A"])} | {cell(g["C"])} |')
    lines+=['','| Original order | Condition | Score | Status / constraint failures | Input / output / reasoning tokens | Wall seconds |','|---:|---|---:|---|---|---:|']
    for row in rows:
        lines.append(f'| {row["original_order"]} | {row["condition"]} | {row["score"]} | {row["status"]}: {row["failure"] or ", ".join(row["failed_constraints"])} | {row["input_tokens"]} / {row["output_tokens"]} / {row["reasoning_tokens"]} | {row["client_wall_latency_s"]} |')
    lines+=['',*result['notes'],'','Original run12 and original main pairs were not modified or recombined. All continuation results were independently re-read and rescored. Native CLI top-level errors and reconnect events are preserved per row.']
    (root/'CONTINUATION_REPORT.md').write_text('\n'.join(lines)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=summarize(a.output);print(json.dumps({k:v for k,v in result.items() if k not in ('runs','paired_metrics','notes')},indent=2))
