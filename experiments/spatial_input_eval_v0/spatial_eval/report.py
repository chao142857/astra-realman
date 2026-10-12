"""Comparable pairs exclude missing GT, invalid outputs, and mixed backends."""
import csv
import itertools
import json
from .schema import CONDITIONS, write


def reports(rows, output):
    write(output/'results.json',rows)
    cols=['scene_id','task_id','condition','source','model_calls','image_count','geometry_source',
          'parse_status','score_status','score','latency_s','token_usage','raw_output','prediction','constraints','error_types','artifact']
    with (output/'results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=cols,lineterminator="\n");writer.writeheader()
        for row in rows:
            entry={k:row.get(k) for k in cols};entry['constraints']=row.get('evaluation',{}).get('constraints')
            for k in ('token_usage','prediction','constraints','error_types'):entry[k]=json.dumps(entry[k],ensure_ascii=False)
            writer.writerow(entry)
    grouped={}
    for r in rows:grouped.setdefault((r['scene_id'],r['task_id']),{})[r['condition']]=r
    pairs=[]
    for (sid,tid),group in grouped.items():
        for left,right in itertools.combinations(CONDITIONS,2):
            a,c=group.get(left),group.get(right)
            if a is None or c is None:continue
            eligible=(a['source']==c['source'] and a['score_status']==c['score_status']=='SCORED'
                      and a['task_prompt_sha256']==c['task_prompt_sha256'])
            # Invalid JSON with reliable truth is a failed response, score=0, included in paired effectiveness.
            pairs.append({'scene_id':sid,'task_id':tid,'left':left,'right':right,'eligible':eligible,
                          'source':a['source'],'score_delta_right_minus_left':c['score']-a['score'] if eligible else None})
    write(output/'paired_comparison.json',pairs)
    failure=[{'scene_id':r['scene_id'],'task_id':r['task_id'],'condition':r['condition'],
              'error_types':r['error_types'],'artifact':r['artifact']} for r in rows if r['error_types']]
    write(output/'failure_index.json',failure)
    real=sum(r['model_calls'] for r in rows);lines=['# Astra spatial input evaluation V0','',
        f'Recorded samples: {len(rows)}; recorded real infer attempts started: {real}.',
        'Remote service invocation count is UNKNOWN unless established by response events; CLI startup is not model completion.',
        'Mock results verify plumbing only; no claim of Astra capability or significance.','',
        '| Condition | Rows | Scored | Mean score |','|---|---:|---:|---:|']
    for condition in CONDITIONS:
        group=[r for r in rows if r['condition']==condition];valid=[r['score'] for r in group if r['score'] is not None]
        lines.append(f'| {condition} | {len(group)} | {len(valid)} | {sum(valid)/len(valid) if valid else "UNKNOWN"} |')
    lines+=['','Paired comparisons (right minus left):','']
    for left,right in itertools.combinations(CONDITIONS,2):
        valid=[p['score_delta_right_minus_left'] for p in pairs if p['eligible'] and p['left']==left and p['right']==right]
        lines.append(f'- {left} → {right}: n={len(valid)}, mean delta={sum(valid)/len(valid) if valid else "UNKNOWN"}.')
    lines+=['','Significance: NOT_ESTABLISHED. V0 reports paired descriptive differences only; repeated scenes/tasks are not independent replicates.','',
            'See `failure_index.json` and each request/response/evaluation artifact for the exact failed constraint.']
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
