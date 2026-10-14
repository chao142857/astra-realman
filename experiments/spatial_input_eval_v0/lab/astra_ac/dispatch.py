"""Dedicated sequential 24-job binding; default dry-run, no implicit permission."""
import argparse,json,os,socket,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
from astra_ac import runtime as r
ROOT=r.M/'evidence/astra_ac_runs'
VERSION='astra.six_scene_ac.dispatch.v1'
def safe_root(root):
 p=Path(root).absolute();resolved=p.resolve()
 if p!=resolved:raise ValueError('SYMLINK_OUTPUT_FORBIDDEN')
 temp=Path(tempfile.gettempdir()).resolve()
 if not (resolved.is_relative_to(ROOT) and resolved!=ROOT) and not (resolved.is_relative_to(temp) and any(x.startswith('astra-ac-') for x in resolved.relative_to(temp).parts)):
  raise ValueError('NEW_AC_BATCH_ROOT_REQUIRED')
 return resolved
def hashes():
 names=['lab/astra_ac/runtime.py','lab/astra_ac/dispatch.py','lab/astra_ac/verify.py','lab/pilot02_runtime.py','lab/pilot02_dispatcher.py','lab/pilot02_contract.py','spatial_eval/mac_bridge.py','spatial_eval/scoring.py','spatial_eval/geometry.py','spatial_eval/schema.py','spatial_eval/adapter.py']
 result={n:r.sha(r.M/n) for n in names}
 for n in ('codex_astra_mac_bridge.py','structured_outputs.py'):result['production/'+n]=r.sha(r.M.parents[1]/'astra_realman_harness/scripts'/n)
 return result
def prepare(root):
 root=safe_root(root);order=r.frozen();root.parent.mkdir(parents=True,exist_ok=True);root.mkdir(mode=0o700,exist_ok=False)
 s={'version':VERSION,'root':str(root),'batch_id':uuid.uuid4().hex,'created_at':r.now(),'status':'DRY_RUN','mode':'DRY_RUN','jobs':order['ordered_samples'],'order_sha256':r.sha(r.ORDER),'release_sha256':r.EXPECTED_RELEASE_SHA,'implementation_sha256':hashes(),'deadline_s':180,'server_timeout_s':190,'concurrency':1,'automatic_retries':0,'max_client_dispatches':24,'authorization':None,'production_preflight':None,'reserved_budget':0,'runs':[]}
 r.save(root/'ledger.json',s);return s
def load(root):
 root=safe_root(root);s=r.read(root/'ledger.json');order=r.frozen()
 expected={'version':VERSION,'root':str(root),'jobs':order['ordered_samples'],'order_sha256':r.sha(r.ORDER),'release_sha256':r.EXPECTED_RELEASE_SHA,'implementation_sha256':hashes(),'deadline_s':180,'server_timeout_s':190,'concurrency':1,'automatic_retries':0,'max_client_dispatches':24}
 if any(s.get(k)!=v for k,v in expected.items()):raise ValueError('AC_LEDGER_SCOPE_CHANGED')
 if s['mode'] not in ('DRY_RUN','REAL','OFFLINE_FIXTURE') or s['status'] not in ('DRY_RUN','READY','STOPPED','COMPLETE','BUDGET_EXHAUSTED'):raise ValueError('AC_LEDGER_STATE')
 if s['reserved_budget']!=len(s['runs']) or len(s['runs'])>24:raise ValueError('AC_BUDGET_CORRUPT')
 for i,row in enumerate(s['runs']):
  if row['index']!=i+1 or row['job']!=s['jobs'][i] or row['artifact']!=f'run-{i+1:03d}':raise ValueError('AC_RESERVATION_CORRUPT')
 return s
def authorize(s,path):
 grant=r.read(path);keys={'generation_authorized','batch_id','output_root','order_sha256','release_sha256','implementation_sha256','max_dispatches','deadline_s','server_timeout_s','concurrency','user_authorization_statement'}
 if set(grant)!=keys or grant['generation_authorized'] is not True:raise ValueError('NEW_EXPLICIT_AUTHORIZATION_REQUIRED')
 for a,b in [('batch_id','batch_id'),('output_root','root'),('order_sha256','order_sha256'),('release_sha256','release_sha256'),('implementation_sha256','implementation_sha256'),('deadline_s','deadline_s'),('server_timeout_s','server_timeout_s'),('concurrency','concurrency')]:
  if grant[a]!=s[b]:raise ValueError('AUTHORIZATION_SCOPE_MISMATCH')
 if type(grant['max_dispatches']) is not int or not 1<=grant['max_dispatches']<=24 or not isinstance(grant['user_authorization_statement'],str) or not grant['user_authorization_statement'].strip():raise ValueError('AUTHORIZATION_BUDGET_OR_STATEMENT')
 bound={'sha256':r.sha(path),'grant':grant}
 if s['authorization'] is not None:
  if s['authorization']!=bound:raise ValueError('NO_REPLACEMENT_OR_ADDED_BUDGET')
 elif s['mode']!='DRY_RUN' or s['status']!='DRY_RUN' or s['runs']:raise ValueError('NEW_AUTHORIZATION_STATE')
 else:s.update(authorization=bound,mode='REAL',status='READY')
 return s
def check_preflight(s,path,config):
 p=r.read(path);expected={'status':'PASS','batch_id':s['batch_id'],'execution_host':'ubuntu-robot','actual_hostname':socket.gethostname(),'order_sha256':s['order_sha256'],'release_sha256':s['release_sha256'],'implementation_sha256':s['implementation_sha256'],'bridge_config_sha256':r.sha(config),'server_timeout_s':190,'client_timeout_s':180,'single_worker':True,'non_generating_auth_and_tunnel_check':True,'model':'gpt-6-astra','reasoning':'medium','ephemeral':True}
 if socket.gethostname().lower()!='ubuntu-robot' or any(p.get(k)!=v for k,v in expected.items()):raise ValueError('NEW_BATCH_PRODUCTION_CHECK_REQUIRED')
 age=(datetime.now(timezone.utc)-datetime.fromisoformat(p['checked_at'])).total_seconds()
 if not 0<=age<=900:raise ValueError('PRODUCTION_CHECK_STALE')
 return {'sha256':r.sha(path),'receipt':p}
def report(root,s):
 pairs=[]
 for pid in dict.fromkeys(j['pair_id'] for j in s['jobs']):
  rows=[x for x in s['runs'] if x['job']['pair_id']==pid]
  if len(rows)!=2 or any(x['status']!='VALID' for x in rows):continue
  by={x['job']['condition']:x for x in rows};a=by['RGB_MULTI_VIEW'];c=by['RGB_ORACLE_3D']
  pairs.append({'pair_id':pid,'scene':a['job']['scene'],'repeat':a['job']['repeat'],'A':a['assessment'],'C':c['assessment'],'C_minus_A':c['assessment']['score']-a['assessment']['score'],'category':('both_success' if a['assessment']['score'] and c['assessment']['score'] else 'A_only_success' if a['assessment']['score'] else 'C_only_success' if c['assessment']['score'] else 'both_failed'),'spatial_fact_estimation':'NOT_MEASURED','source':a['assessment']['source']})
 r.save(Path(root)/'paired_results.json',pairs)
def check_archives(root,s):
 seen_threads=set();seen_requests=set()
 for row in s['runs']:
  if row['status']!='VALID':raise ValueError('UNRESOLVED_DISPATCH')
  result=r.assess(Path(root)/row['artifact'],row['job'])
  if result!=row['assessment']:raise ValueError('ARCHIVE_CHANGED')
  if result['thread_id'] in seen_threads or result['request_id'] in seen_requests:raise ValueError('REUSED_SESSION_OR_REQUEST')
  seen_threads.add(result['thread_id']);seen_requests.add(result['request_id'])
def advance(root,s,runner,limit):
 # Caller holds the shared host lock. Reservation is fsync/replace before runner.
 root=Path(root)
 if s['status']!='READY':raise ValueError('BATCH_NOT_READY')
 if type(limit) is not int or not 1<=limit<=24:raise ValueError('MAXIMUM_24')
 if s['mode']=='REAL':
  if not s['authorization'] or limit!=s['authorization']['grant']['max_dispatches'] or not s['production_preflight']:raise ValueError('AUTHORIZATION_AND_PRODUCTION_CHECK_REQUIRED')
 elif s['mode']!='OFFLINE_FIXTURE':raise ValueError('NO_DISPATCH_PERMISSION')
 try:check_archives(root,s)
 except Exception:
  s['status']='STOPPED';r.save(root/'ledger.json',s);raise
 while len(s['runs'])<limit:
  try:r.frozen();job=s['jobs'][len(s['runs'])];r.job_input(job)
  except Exception:
   s['status']='STOPPED';r.save(root/'ledger.json',s);raise
  index=len(s['runs'])+1;folder=root/f'run-{index:03d}'
  if folder.exists() or folder.is_symlink():s['status']='STOPPED';r.save(root/'ledger.json',s);raise ValueError('OUTPUT_EXISTS_NO_RETRY')
  row={'index':index,'job':job,'artifact':folder.name,'status':'RESERVED','reserved_at':r.now()};s['runs'].append(row);s['reserved_budget']=len(s['runs']);r.save(root/'ledger.json',s)
  try:
   result=runner(job,folder)
   expected='REAL_ASTRA_ATTEMPT' if s['mode']=='REAL' else 'FAKE_MAC_BRIDGE_NOT_ASTRA'
   if result.get('source')!=expected:result=dict(result,status='NOT_SCORED',score=None,failure='SOURCE_MISMATCH')
   if result['status']=='VALID' and any(result[k]==p.get('assessment',{}).get(k) for p in s['runs'][:-1] for k in ('thread_id','request_id')):result=dict(result,status='NOT_SCORED',score=None,failure='REUSED_SESSION_OR_REQUEST')
   row.update(assessment=result,status='VALID' if result['status']=='VALID' else 'INVALID_OR_UNKNOWN',finished_at=r.now())
   if row['status']!='VALID':s['status']='STOPPED'
  except BaseException as exc:
   row.update(status='UNKNOWN',error_class=type(exc).__name__);s['status']='STOPPED';r.save(root/'ledger.json',s);report(root,s);raise
  r.save(root/'ledger.json',s);report(root,s)
  if s['status']=='STOPPED':return s
 s['status']='COMPLETE' if len(s['runs'])==24 else 'BUDGET_EXHAUSTED';r.save(root/'ledger.json',s);return s
def run(root,*,real=False,authorization=None,preflight=None,config=None):
 with r.lock():
  try:s=load(root)
  except Exception:
   path=safe_root(root)/'ledger.json'
   if real and path.exists():
    prior=r.read(path)
    if prior.get('version')==VERSION and prior.get('root')==str(safe_root(root)):
     prior.update(status='STOPPED',stop_reason='LOAD_INTEGRITY_FAILURE');r.save(path,prior)
   raise
  if not real:return {'status':'DRY_RUN_NO_DISPATCH','batch_id':s['batch_id'],'reserved_budget':s['reserved_budget'],'planned':24,'generation_requests':0}
  if any(x is None for x in (authorization,preflight,config)):raise ValueError('NEW_AUTHORIZATION_PREFLIGHT_CONFIG_REQUIRED')
  if not Path(s['root']).is_relative_to(ROOT):raise ValueError('REAL_RUN_REQUIRES_DEDICATED_ROOT')
  s=authorize(s,authorization);s['production_preflight']=check_preflight(s,preflight,config);r.save(Path(root)/'ledger.json',s)
  return advance(root,s,lambda j,p:r.perform(j,p,r.MacBridgeConfig.load(config)),s['authorization']['grant']['max_dispatches'])
def reconcile(root):
 # Inspection only. An unknown or protocol-failed batch never auto-resumes or refunds.
 with r.lock():
  s=load(root);out=[]
  for row in s['runs']:out.append({'index':row['index'],'assessment':r.assess(Path(root)/row['artifact'],row['job'])})
  if s['status'] not in ('COMPLETE','BUDGET_EXHAUSTED'):s['status']='STOPPED'
  r.save(Path(root)/'ledger.json',s);r.save(Path(root)/'reconciliation.json',{'status':s['status'],'dispatches':0,'refunds':0,'rows':out});return s
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','status','reconcile']);p.add_argument('--output',type=Path,required=True);p.add_argument('--real',action='store_true');p.add_argument('--authorization',type=Path);p.add_argument('--preflight',type=Path);p.add_argument('--bridge-config',type=Path);a=p.parse_args()
 if a.action=='prepare':
  if a.real or a.authorization:raise ValueError('PREPARE_IS_DRY_RUN')
  with r.lock():s=prepare(a.output)
 elif a.action=='run':s=run(a.output,real=a.real,authorization=a.authorization,preflight=a.preflight,config=a.bridge_config)
 elif a.action=='reconcile':s=reconcile(a.output)
 else:s=load(a.output)
 print(json.dumps({k:v for k,v in s.items() if k not in ('jobs','runs','authorization','production_preflight')},indent=2))
if __name__=='__main__':main()
