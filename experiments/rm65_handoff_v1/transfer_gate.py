"""One transfer episode's explicit permission and cumulative <=16 client dispatches.

No historical ledger is opened. Atomic persistence reuses the existing helper.
"""
import hashlib
import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from action_interface import accept_result
from pilot02_dispatcher import save, now

ROOT = Path(__file__).resolve().parent
VERSION = 'rm65.transfer_only.episode.v1'


def new_root(root):
    path=Path(root).resolve();allowed=ROOT/'evidence/transfer_runs'
    fixture=any(p.startswith('rm65-transfer-fixture-') for p in path.parts)
    if not fixture and (not path.is_relative_to(allowed) or path==allowed):raise ValueError('DEDICATED_NEW_TRANSFER_ROOT_REQUIRED')
    return path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes():
    names = ('action_interface.py','run_episode.py','dual_scene.py','carry_collision.py','initial_transfer.py','initial_v1.py',
             'scene_v4_ready_transfer_1100.json','transfer_episode.py','transfer_gate.py',
             'transfer_preflight.py','evaluate_transfer.py','transfer_criteria_v1.json')
    result={name: sha(ROOT/name) for name in names}
    repo=ROOT.parents[1]
    for name in ('codex_astra_mac_bridge.py','structured_outputs.py'):
        result['production/'+name]=sha(repo/'astra_realman_harness/scripts'/name)
    result['transport/mac_bridge.py']=sha(repo/'experiments/spatial_input_eval_v0/spatial_eval/mac_bridge.py')
    return result


def prepare(root):
    root = new_root(root);root.mkdir(parents=True,exist_ok=False,mode=0o700)
    state = {'version':VERSION,'batch_id':uuid.uuid4().hex,'output_root':str(root),
             'task':'handoff_transfer_only','source_hashes':hashes(),'status':'DRAFT',
             'authorization':None,'reserved_budget':0,'runs':[],'shadow_validated':False}
    save(root/'ledger.json',state)
    grant = {k:state[k] for k in ('version','batch_id','output_root','task','source_hashes')}
    grant.update(generation_authorized=False,max_dispatches=0,client_timeout_s=180,
                 server_timeout_s=190,workers=1,user_authorization_statement='')
    save(root/'authorization_REQUEST_NOT_GRANTED.json',grant)
    return state


class Gate:
    version=VERSION
    task='handoff_transfer_only'
    new_root=staticmethod(new_root)
    hashes=staticmethod(hashes)
    execution_hostname='tongji-Precision-3680'
    max_total=16
    max_execute=None
    extra_grant_parameters={}
    requires_shadow=True

    def accept(self,folder):return accept_result(folder)

    def __init__(self,root,authorization,preflight,config,stage):
        import fcntl
        if stage not in ('shadow','execute'):raise ValueError('UNKNOWN_STAGE')
        self.root=self.new_root(root);self.handle=(self.root/'episode.lock').open('a')
        try:fcntl.flock(self.handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.handle.close();raise ValueError('ANOTHER_TRANSFER_EPISODE_ACTIVE')
        try:
            self.state=json.loads((self.root/'ledger.json').read_text());s=self.state
            grant=json.loads(Path(authorization).read_text());check=json.loads(Path(preflight).read_text())
            expected={k:s[k] for k in ('version','batch_id','output_root','task','source_hashes')}
            if any(grant.get(k)!=v for k,v in expected.items()) or s['version']!=self.version or s['task']!=self.task or s['source_hashes']!=self.hashes() or s['output_root']!=str(self.root):raise ValueError('TRANSFER_SCOPE_CHANGED')
            if grant.get('generation_authorized') is not True or type(grant.get('max_dispatches')) is not int or not 1<=grant['max_dispatches']<=self.max_total or not grant.get('user_authorization_statement','').strip():raise ValueError('NEW_TRANSFER_USER_AUTHORIZATION_REQUIRED')
            if any(grant.get(k)!=v for k,v in dict({'client_timeout_s':180,'server_timeout_s':190,'workers':1},**self.extra_grant_parameters).items()):raise ValueError('TRANSFER_PARAMETERS_CHANGED')
            if any(r['status']!='VALID' for r in s['runs']):
                s.update(status='STOPPED',stop_reason='UNRESOLVED_PRIOR_RESERVATION');save(self.root/'ledger.json',s)
                raise ValueError('STOPPED_OR_UNKNOWN_NO_RESUME')
            if s['status'] not in ('DRAFT','READY') or s['reserved_budget']!=len(s['runs']):raise ValueError('STOPPED_OR_UNKNOWN_NO_RESUME')
            bound={'sha256':sha(authorization),'grant':grant}
            if s['authorization'] is not None and s['authorization']!=bound:raise ValueError('NO_REPLACEMENT_OR_ADDED_BUDGET')
            required={'status':'PASS','batch_id':s['batch_id'],'source_hashes':s['source_hashes'],
                      'actual_hostname':socket.gethostname(),'bridge_config_sha256':sha(config),
                      'client_timeout_s':180,'server_timeout_s':190,'model':'gpt-6-astra',
                      'reasoning':'medium','non_generating_auth_and_tunnel_check':True}
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(check['checked_at'])).total_seconds()
            if socket.gethostname()!=self.execution_hostname or any(check.get(k)!=v for k,v in required.items()) or not 0<=age<=900:raise ValueError('FRESH_HOST_PRODUCTION_PREFLIGHT_REQUIRED')
            valid_shadows=[r for r in s['runs'] if r['stage']=='shadow' and r['status']=='VALID']
            if len(valid_shadows)>1 or s['shadow_validated']!=(len(valid_shadows)==1):raise ValueError('SHADOW_STATE_INCONSISTENT')
            if stage=='shadow' and valid_shadows:raise ValueError('SHADOW_ALREADY_DISPATCHED')
            if stage=='execute' and self.requires_shadow and len(valid_shadows)!=1:raise ValueError('VALID_SHADOW_REQUIRED_FIRST')
            for r in s['runs']:self.accept(self.root/r['artifact'])
            s.update(authorization=bound,status='READY');self.limit=grant['max_dispatches'];self.stage=stage;self.flush()
        except BaseException:self.handle.close();raise

    def flush(self):save(self.root/'ledger.json',self.state)

    def reserve(self,folder,context):
        s=self.state
        if self.hashes()!=s['source_hashes']:
            self.stop('SOURCE_CHANGED_BEFORE_DISPATCH');raise ValueError('TRANSFER_SOURCE_CHANGED')
        if s['status']!='READY' or s['reserved_budget']>=self.limit:raise ValueError('TRANSFER_BUDGET_EXHAUSTED')
        if any(r['status']!='VALID' for r in s['runs']):raise ValueError('SINGLE_OUTSTANDING_REQUEST_ONLY')
        if self.stage=='shadow' and any(r['stage']=='shadow' for r in s['runs']):raise ValueError('SHADOW_ALREADY_DISPATCHED')
        if self.stage=='execute' and self.max_execute is not None and sum(r['stage']=='execute' for r in s['runs'])>=self.max_execute:raise ValueError('EXECUTION_STAGE_BUDGET_EXHAUSTED')
        folder=Path(folder).resolve()
        if not folder.is_relative_to(self.root) or folder.exists():raise ValueError('NEW_TRANSFER_ARTIFACT_REQUIRED')
        row={'index':len(s['runs'])+1,'stage':self.stage,'status':'RESERVED',
             'artifact':str(folder.relative_to(self.root)),'reserved_at':now(),
             'context_sha256':hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()}
        s['runs'].append(row);s['reserved_budget']+=1;self.flush()
        return row

    def complete(self,row,folder):
        self.accept(folder)
        wire=json.loads((Path(folder)/'bridge_request.json').read_text())
        response=json.loads((Path(folder)/'response.json').read_text())
        if response['source']!='REAL_ASTRA_ATTEMPT':raise ValueError('REAL_SOURCE_REQUIRED')
        context_sha=hashlib.sha256(json.dumps(wire['context'],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        if row['context_sha256']!=context_sha:raise ValueError('REQUEST_CONTEXT_CHANGED')
        events=[json.loads(line) for line in response['events'].splitlines() if line.strip()]
        thread=next(x['thread_id'] for x in events if x.get('type')=='thread.started')
        if not thread or any(thread==r.get('thread_id') or wire['request_id']==r.get('request_id') for r in self.state['runs'] if r is not row):raise ValueError('SESSION_OR_REQUEST_REUSE')
        row.update(status='VALID',thread_id=thread,request_id=wire['request_id'],finished_at=now())
        if self.stage=='shadow':self.state['shadow_validated']=True
        self.flush()

    def stop(self,reason):
        self.state.update(status='STOPPED',stop_reason=reason);self.flush()

    def close(self):self.handle.close()
