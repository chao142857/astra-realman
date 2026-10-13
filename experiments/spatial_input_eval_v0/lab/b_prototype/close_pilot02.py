"""Read historical assessments only; never calls report writers on old batch roots."""
import argparse,json,hashlib,statistics
from pathlib import Path

def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def close(module,out):
 out.mkdir(parents=True,exist_ok=False);rows=[];stages=[];hashes=[]
 for name in ('pilot02_real_01','pilot02_continuation_01'):
  root=module/'evidence/pilot02_runs'/name;l=read(root/'ledger.json');stages.append({'phase':name,'batch_id':l['batch_id'],'status':l['status'],'client_dispatches':l['reserved_budget'],'client_deadline_s':180,'worker_count':1})
  for p in sorted(root.rglob('*')):
   if p.is_file():hashes.append({'path':str(p.relative_to(module)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
  for run in l['runs']:
   a=read(root/run['artifact']/'assessment.json');u=a.get('usage') or {};scene=run['job']['scene_id_private_catalog_only'];kind='placement' if scene.startswith('p02_a_') else 'restricted_detour' if scene.startswith('p02_b_') else 'autonomous_yaw'
   rows.append({'phase':name,'original_order':run['job']['planned_order'],'scene':scene,'group':kind,'condition':run['job']['condition'],'status':a['status'],'score':a['score'],'client_wall_s':a.get('latency_s'),'reported_reasoning_tokens':(u.get('output_tokens_details') or {}).get('reasoning_tokens',u.get('reasoning_output_tokens')),'cached_input_tokens':(u.get('input_tokens_details') or {}).get('cached_tokens',u.get('cached_input_tokens'))})
 main=[x for x in rows if x['status']=='VALID'];appendix=[x for x in rows if x['status']!='VALID'];pairs=[s for s in dict.fromkeys(x['scene'] for x in main) if len([x for x in main if x['scene']==s])==2];assert len(main)==19 and len(pairs)==9 and len(appendix)==1 and appendix[0]['original_order']==12
 groups=[]
 for phase in [s['phase'] for s in stages]:
  for kind in ('placement','restricted_detour','autonomous_yaw'):
   for cond in ('RGB_MULTI_VIEW','RGB_ORACLE_3D'):
    selected=[x for x in main if x['phase']==phase and x['group']==kind and x['condition']==cond]
    if not selected:continue
    row={'phase':phase,'group':kind,'condition':cond,'valid':len(selected),'successes':sum(x['score']==1 for x in selected)}
    row['success_rate']=row['successes']/row['valid']
    for key in ('client_wall_s','reported_reasoning_tokens'):
     values=[x[key] for x in selected if x[key] is not None];row[key]={'reported_n':len(values),'mean':statistics.mean(values) if values else None,'total':sum(values) if values else None}
    groups.append(row)
 write(out/'summary.json',{'stages':stages,'protocol_valid_outputs':19,'complete_pairs':9,'groups':groups,'main_rows':main,'excluded_appendix_only':appendix,'complete_pair_scenes':pairs,'new_astra_requests':0,'notes':['Original run12 remains NOT_SCORED, excluded from primary success/time/token aggregates.','Reported tokens are not exact compute; wall time is not pure model latency.','Cache values are recorded per row; missing values are unknown, not zero.','Historical A/C are references, not future repeated samples.']})
 write(out/'historical_file_hashes.json',hashes)
 lines=['# Pilot 02 capability pilot closeout','','19 protocol-valid outputs; 9 complete pairs. Original run12 is appendix-only NOT_SCORED.','','| Phase | Group | Condition | Success / valid | Mean wall s | Mean reported reasoning tokens |','|---|---|---|---:|---:|---:|']
 for g in groups:lines.append(f"| {g['phase']} | {g['group']} | {g['condition']} | {g['successes']}/{g['valid']} | {g['client_wall_s']['mean']:.3f} | {g['reported_reasoning_tokens']['mean']} |")
 lines+=['','Both stages remain distinct. All frozen assessments and ledgers are read-only. No invalid output is treated as a geometric zero. Small descriptive pilot only.','Original run12 post-hoc analysis remains in docs/PILOT02_RUN12_POSTHOC_APPENDIX.md and is not merged into main results.']
 (out/'CLOSEOUT.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--module',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();close(a.module,a.output)
