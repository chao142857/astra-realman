"""Read-only physical acceptance; full recordings stay on the execution host."""
import gzip,hashlib,json,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'evidence/interface_repair_yanglab_20261017'
KEYS=('arms','contacts','object_pose','object_velocity','drive_targets','bilateral_contact')

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def rows(p):
    op=gzip.open if p.suffix=='.gz' else open
    with op(p,'rt') as f:
        for l in f:yield json.loads(l)

def main():
    archived=ROOT/'evidence/full_task_real_20261016/episode'
    reference={r['step']:r for r in rows(archived/'physics.jsonl.gz') if r['step'] in (11675,27325)}
    result={'host':subprocess.check_output(['hostname'],text=True).strip(),'real_requests':0,'bridge_connections':0,
        'historical_scores_changed':False,'whole_task_success_claimed':False,'cases':{}}
    for name in ['contact_d1_original_01','contact_d1_readback_02','contact_d1_left_v4_01','contact_d1_slow2_01','sequential_d4_01','vacant_table_01','grasp_release_01']:
        p=OUT/name
        reportfile=next((p/x for x in ('replay.json','acceptance.json','negative_control.json') if (p/x).exists()),None)
        if reportfile is None:
            result['cases'][name]={'status':'PENDING'};continue
        rep=json.loads(reportfile.read_text());first=None;last=None;maxpen=0.;checks={};forbidden_contacts=[]
        for r in rows(p/'physics.jsonl'):
            last=r
            if first is None and r['bilateral_contact']['left']:first=r['step']
            if r['step'] in reference:checks[str(r['step'])]={k:r[k]==reference[r['step']][k] for k in KEYS}
            for c in r['contacts']:
                if 'target_cube' in c['names'] and any('Support_Link' in n for n in c['names']):maxpen=max(maxpen,-min(q['separation'] for q in c['points']))
        item={'status':rep.get('status'),'error':rep.get('error'),'physics_steps':last['step'],
            'sim_time_s':last['sim_time_s'],'first_left_bilateral_step':first,
            'max_pad_penetration_m':maxpen,'final_bilateral':last['bilateral_contact'],
            'exact_archived_state_checks':checks,'raw_report_sha256':sha(reportfile)}
        guard=list(p.glob('group_*/contact_guard_summary_PRIVATE.json'))
        item['contact_guards']=[{'group':q.parent.name,**{k:v for k,v in json.loads(q.read_text()).items() if k in ('first_bilateral_step','first_danger','execution_abort')}} for q in guard]
        # First danger can contain large contact records; keep the source unchanged and summarize here.
        for g in item['contact_guards']:
            if g['first_danger'] is not None:g['first_danger']={k:g['first_danger'][k] for k in ('step','forbidden_fcl_pairs','bilateral')}
        item['source_answers']=rep.get('source_answers',[])
        if name.startswith('contact_d1'):
            events=list(p.rglob('events.jsonl'))
            item['latch_events']=[]
            for e in events:
                for r in rows(e):
                    if r.get('event') in ('bilateral_contact_latch','left_contact_hold_v4','explicit_contact_hold'):item['latch_events'].append(r)
        if name=='sequential_d4_01':
            groups=rep['new_receipt']['groups'];item['executed_groups']=len(groups)
            item['duplicate_stage']=[g for g in groups if g.get('stage_index')==2]
            # Keep only index, boundary and measured TCP evidence, no huge state receipts.
            item['duplicate_stage']=[{**{k:v for k,v in g.items() if k in ('stage_index','input_action_indices','operation_start_measured_tcp','commands')},'start_step':g.get('receipt',{}).get('start_step'),'end_step':g.get('receipt',{}).get('end_step')} for g in item['duplicate_stage']]
        for key in ('post_lift_private_evidence','release_regression'):
            if key in rep:item[key]=rep[key]
        video=p/'execution.mp4'
        if video.exists():
            item['video']={'path':str(video),'bytes':video.stat().st_size,'sha256':sha(video)}
        result['cases'][name]=item
    ledgers=subprocess.check_output(['git','ls-files','*ledger*.json'],cwd=ROOT,text=True).splitlines()
    unchanged=[]
    for name in ledgers:
        path=ROOT/name
        old=subprocess.check_output(['git','show','624d80f:experiments/rm65_handoff_v1/'+name],cwd=ROOT)
        unchanged.append({'path':name,'unchanged':path.read_bytes()==old,'sha256':sha(path)})
    result['historical_tracked_ledgers']=unchanged
    (OUT/'independent_acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:{a:b for a,b in v.items() if a in ('status','error','physics_steps','max_pad_penetration_m','executed_groups')} for k,v in result['cases'].items()},indent=2))

if __name__=='__main__':main()
