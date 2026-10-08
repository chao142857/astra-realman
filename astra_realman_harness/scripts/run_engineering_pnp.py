#!/usr/bin/env python3
"""Thin ENGINEERING_REFERENCE preparation/ledger over existing offline script runner.
No new policy, physics, scene ownership or model service. Prepared bundle is single-use.
"""
import argparse,hashlib,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
CONFIG='configs/rm65_ctag_reference/assembly.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def write(p,x):
    with Path(p).open('x') as f:json.dump(x,f,indent=2)
def verify_assets(assets):
    for n,r in read(assets/'asset_manifest.json')['files'].items():
        if sha(assets/n)!=r['sha256']:raise ValueError('ASSET_HASH:'+n)
def layout_config(original,layout):
    cfg=json.loads(json.dumps(original))
    for key,n in [('object_initial_xyz',3),('target_xy',2)]:
        v=layout[key]
        import math
        if not isinstance(v,list) or len(v)!=n or not all(type(x) in (int,float) and math.isfinite(x) for x in v):raise ValueError('LAYOUT_COORDINATES')
    cfg['scene']['cube_initial_xyz']=layout['object_initial_xyz'];cfg['scene']['place_zone_xy']=layout['target_xy']
    return cfg

def prepare(a):
    reference=read(a.reference/'result.json')
    if reference['status']!='PASS' or not reference['episode']['score']['strict_success'] or reference['condition']!='script':raise ValueError('REFERENCE_COMPLETE_PASS_REQUIRED')
    plan=read(a.layouts)
    if plan['repeats']!=2 or len(plan['layouts'])!=3 or len({tuple(x['object_initial_xyz']+x['target_xy']) for x in plan['layouts']})!=3:raise ValueError('THREE_DISTINCT_LAYOUTS_TWICE_REQUIRED')
    if plan['episode_budget_s']!=300 or plan['process_watchdog_s']!=360 or plan['model_calls']!=0 or plan['hardware_calls']!=0 or plan['reference_parameters']!={'grasp_z_m':.04,'opening':.45}:raise ValueError('FIXED_ENGINEERING_SCOPE')
    ids=[x['id'] for x in plan['layouts']]
    if ids!=['L1','L2','L3']:raise ValueError('LAYOUT_IDS')
    verify_assets(a.assets);a.output.mkdir(parents=True,exist_ok=False)
    original=read(a.assets/CONFIG);records=[]
    for layout in plan['layouts']:
        dest=a.output/'assets'/layout['id'];shutil.copytree(a.assets,dest,ignore=shutil.ignore_patterns('__pycache__'))
        cfg=layout_config(original,layout);(dest/CONFIG).write_text(json.dumps(cfg,indent=2)+'\n')
        manifest=read(dest/'asset_manifest.json');entry=manifest['files'][CONFIG]
        entry.update(sha256=sha(dest/CONFIG),changes=['ENGINEERING_REFERENCE initial object xyz / placement marker xy only'])
        (dest/'asset_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');verify_assets(dest)
        changed=[n for n in manifest['files'] if sha(dest/n)!=sha(a.assets/n)]
        if any(n!=CONFIG for n in changed):raise ValueError('UNEXPECTED_ASSET_CHANGE')
        records.append({'id':layout['id'],'asset_manifest_sha256':sha(dest/'asset_manifest.json'),'changed_files':changed})
    write(a.output/'prepared.json',{'label':'ENGINEERING_REFERENCE','plan':plan,'layout_manifests':records,
      'original_asset_manifest_sha256':sha(a.assets/'asset_manifest.json'),'reference_result_sha256':sha(a.reference/'result.json'),
      'source_sha256':{str(p.relative_to(BASE)):sha(p) for p in [BASE/'scripts/run_full_pnp_offline.py',*sorted((BASE/'sim_skills').rglob('*.py'))]},
      'prepared_unix':time.time(),'reference_run':str(a.reference.resolve()),'plan_sha256':sha(a.layouts)})
    print(json.dumps({'prepared':str(a.output),'cases':6,'physics_runs':0}))

def classify(result):
    if result.get('status')=='PASS':return None
    error=json.dumps(result.get('episode',{}).get('error') or result.get('error') or '')
    if 'STOP' in error:return 'STOP'
    if any(x in error for x in ('PLAN','IK','planner')):return 'PLANNING_IK'
    if any(x in error for x in ('PENETRATION','COLLISION')):return 'GEOMETRY_CONTACT_SAFETY'
    if 'GRASP_CONTACT' in error:return 'CONTACT_LOSS_OR_GRASP'
    if any(x in error for x in ('TRACKING','JOIN')):return 'EXECUTION_ERROR'
    if any(x in error for x in ('GRIPPER','RGB','DEPENDENC')):return 'EVIDENCE_GATE'
    if 'DEADLINE' in error:return 'TIMEOUT'
    if result.get('episode',{}).get('score'):return 'SCORING'
    return 'OTHER'

def process_status(result,code,watchdog):
    if watchdog:return 'TIMEOUT'
    if code!=0 and result.get('status')=='PASS':return 'PROCESS_FAILURE'
    return result.get('status','INCOMPLETE')

def run(a):
    prep=read(a.prepared/'prepared.json');plan=prep['plan']
    for n,h in prep['source_sha256'].items():
        if sha(BASE/n)!=h:raise ValueError('SOURCE_CHANGED_AFTER_PREPARE:'+n)
    for row in prep['layout_manifests']:
        assets=a.prepared/'assets'/row['id']
        if sha(assets/'asset_manifest.json')!=row['asset_manifest_sha256']:raise ValueError('MANIFEST_CHANGED')
        verify_assets(assets)
    a.output.mkdir(parents=True,exist_ok=False)
    # Failure consumes this prepared bundle. Never delete this marker to retry.
    write(a.prepared/'CONSUMED.json',{'output':str(a.output.resolve()),'started_unix':time.time()})
    stream=(a.output/'attempts.jsonl').open('x',buffering=1);completed=[];child=None;stopped=False;active=None
    def stop(*_):
        nonlocal stopped
        stopped=True
        if child and child.poll() is None:child.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        for layout in plan['layouts']:
            for repeat in (1,2):
                if stopped:break
                name=f"{layout['id']}-r{repeat}";dest=a.output/name
                cmd=[sys.executable,str(BASE/'scripts/run_full_pnp_offline.py'),'--condition','script','--assets',str((a.prepared/'assets'/layout['id']).resolve()),'--output',str(dest.resolve()),'--seed',str(plan['seed_each_process']),'--video','--budget-s','300']
                attempt={'case':name,'layout':layout,'repeat':repeat,'label':'ENGINEERING_REFERENCE','command':cmd,'started_unix':time.time(),'status':'STARTING'}
                active=attempt
                stream.write(json.dumps(attempt)+'\n');start=time.monotonic()
                with (a.output/(name+'.stdout.log')).open('x') as out,(a.output/(name+'.stderr.log')).open('x') as err:
                    child=subprocess.Popen(cmd,cwd=BASE.parent,stdout=out,stderr=err,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
                    try:code=child.wait(timeout=plan['process_watchdog_s'])
                    except subprocess.TimeoutExpired:
                        child.terminate()
                        try:code=child.wait(timeout=5)
                        except subprocess.TimeoutExpired:child.kill();code=child.wait()
                        attempt['watchdog']='TIMEOUT_NO_RETRY'
                result=read(dest/'result.json') if (dest/'result.json').exists() else {'status':'INCOMPLETE','error':'PROCESS_NO_RESULT'}
                status=process_status(result,code,attempt.get('watchdog'))
                attempt.update(status=status,raw_result_status=result['status'],returncode=code,wall_s=time.monotonic()-start,result=str(dest/'result.json'),failure_class='TIMEOUT' if attempt.get('watchdog') else classify(result))
                completed.append(attempt);stream.write(json.dumps(attempt)+'\n');print(json.dumps({'case':name,'status':attempt['status'],'failure_class':attempt['failure_class']}),flush=True)
                child=None;active=None
            if stopped:break
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        if active is not None:
            active.update(status='INCOMPLETE',failure_class='PROCESS_LIFECYCLE',error=repr(sys.exc_info()[1]))
            completed.append(active);stream.write(json.dumps(active)+'\n')
        not_run=[f"{x['id']}-r{n}" for x in plan['layouts'] for n in (1,2) if f"{x['id']}-r{n}" not in {y['case'] for y in completed}]
        stream.close();write(a.output/'batch.json',{'label':'ENGINEERING_REFERENCE','prepared_sha256':sha(a.prepared/'prepared.json'),
           'planned_cases':6,'attempted_cases':len(completed),'cases':completed,'not_run':not_run,'external_STOP':stopped,'real_model_calls':0,'hardware_calls':0,'retries':0})
    return 0 if len(completed)==6 and all(x['status']=='PASS' for x in completed) else 1

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    q=sub.add_parser('prepare');q.add_argument('--assets',type=Path,required=True);q.add_argument('--reference',type=Path,required=True);q.add_argument('--layouts',type=Path,default=BASE/'config/engineering/layouts_v1.json');q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('run');q.add_argument('--prepared',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    a=p.parse_args();return prepare(a) if a.mode=='prepare' else run(a)
if __name__=='__main__':raise SystemExit(main())
