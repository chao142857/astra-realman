#!/usr/bin/env python3
"""Read-only real-batch reporting; no network, generation, ledger writes or rescoring changes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
from pilot02_runtime import assess, read, write


def group(scene):
    if scene.startswith('p02_a_m'):return {'03':'placement_3mm','10':'placement_10mm','30':'placement_30mm'}[scene[7:9]]
    if scene.startswith('p02_b_'):return 'restricted_detour'
    if scene.startswith('p02_c_'):return 'autonomous_yaw'
    raise ValueError('UNKNOWN_SCENE_GROUP:'+scene)

def usage_parts(usage):
    usage=usage or {};details=usage.get('output_tokens_details') or {}
    reasoning=details.get('reasoning_tokens',usage.get('reasoning_output_tokens'))
    cached=(usage.get('input_tokens_details') or {}).get('cached_tokens',usage.get('cached_input_tokens'))
    return {'input_tokens':usage.get('input_tokens'),'output_tokens':usage.get('output_tokens'),
            'reasoning_tokens':reasoning,'cached_input_tokens':cached}

def summarize(root):
    root=Path(root);state=read(root/'ledger.json')
    if state['mode']!='REAL':raise ValueError('REAL_LEDGER_REQUIRED')
    rows=[]
    for run in state['runs']:
        if run['status'] in ('RESERVED','UNKNOWN'):raise ValueError('UNRESOLVED_RUN; report only after batch stops')
        folder=root/run['artifact'];result=assess(folder,run['job'])
        if result!=run['assessment'] or result!=read(folder/'independent_rescore.json'):raise ValueError('RESCORE_MISMATCH')
        usage=usage_parts(result.get('usage'))
        row={'index':run['index'],'scene':run['job']['scene_id_private_catalog_only'],'condition':run['job']['condition'],
             'status':result['status'],'score':result['score'],'failure':result.get('failure'),
             'failed_constraints':result.get('evaluation',{}).get('error_types',[]),'client_wall_latency_s':result.get('latency_s'),**usage}
        row['group']=group(row['scene']);rows.append(row)
    grouped=[]
    for name in ['placement_3mm','placement_10mm','placement_30mm','restricted_detour','autonomous_yaw']:
        record={'group':name}
        for label,condition in [('A','RGB_MULTI_VIEW'),('C','RGB_ORACLE_3D')]:
            selected=[r for r in rows if r['group']==name and r['condition']==condition];valid=[r for r in selected if r['status']=='VALID']
            record[label]={'planned':2,'dispatched':len(selected),'valid':len(valid),'successes':sum(r['score']==1 for r in valid),
                           'success_rate_valid':sum(r['score']==1 for r in valid)/len(valid) if valid else None}
        grouped.append(record)
    pairs=read(root/'paired_results.json')
    out={'status':state['status'],'batch_id':state['batch_id'],'authorized_max':20,'budget_reserved':state['reserved_budget'],
         'remaining_authorized':20-state['reserved_budget'],'real_dispatches':len(rows),'valid_samples':sum(r['status']=='VALID' for r in rows),
         'not_scored_samples':sum(r['status']!='VALID' for r in rows),'completed_pairs':len(pairs),'groups':grouped,'runs':rows,'pairs':pairs,
         'notes':['No missing/invalid output is counted as a geometry zero.','Descriptive pilot results only; no significance or generalization claims.',
                  'Null reasoning/cache tokens mean not reported, not zero. Tokens are usage, not exact internal compute.',
                  'Client wall time includes transport and any cancellation; not pure model compute time.','All raw predictions and frozen scoring thresholds unchanged.']}
    write(root/'research_summary.json',out)
    lines=['# Pilot 02 real batch results','',f'Batch `{state["batch_id"]}`; status **{state["status"]}**; reserved {state["reserved_budget"]}/20. Valid {out["valid_samples"]}; NOT_SCORED {out["not_scored_samples"]}; complete A/C pairs {len(pairs)}.','',
           '| Group | A successes / valid | C successes / valid |','|---|---:|---:|']
    for r in grouped:
        def cell(c):return f'{c["successes"]}/{c["valid"]}' if c['valid'] else 'N/A (no valid samples)'
        lines.append(f'| {r["group"]} | {cell(r["A"])} | {cell(r["C"])} |')
    lines.extend(['','## Per-dispatch evidence','','| # | Scene | A/C | Status | Score | Input / output / reasoning tokens | Wall seconds | Failure |','|---|---|---|---|---:|---|---:|---|'])
    for r in rows:
        lines.append(f'| {r["index"]} | {r["scene"]} | {r["condition"]} | {r["status"]} | {r["score"]} | {r["input_tokens"]} / {r["output_tokens"]} / {r["reasoning_tokens"]} | {r["client_wall_latency_s"]} | {r["failure"] or ", ".join(r["failed_constraints"])} |')
    lines+=['',*out['notes'],'','Every row was independently re-read and rescored against its original archived assessment.']
    (root/'RESEARCH_REPORT.md').write_text('\n'.join(lines)+'\n')
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=summarize(a.output);print(json.dumps({k:v for k,v in result.items() if k not in ('runs','pairs','notes')},indent=2))
