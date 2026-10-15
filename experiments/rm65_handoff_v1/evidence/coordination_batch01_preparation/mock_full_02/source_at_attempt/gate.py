"""One persistent campaign budget and deadline, never an episode budget reset."""
import fcntl
import hashlib
import json
import socket
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path
from action_interface import accept_result
from transfer_gate import save,now,sha
from workspace_gate import hashes as original_hashes
from .contract import HERE,ROOT,ORDER,TASK

VERSION='rm65.coordination.campaign.v1'


def hashes():
    result=original_hashes()
    for p in sorted(HERE.iterdir()):
        if p.suffix in ('.py','.sh','.json') and p.name!='freeze.json':
            result['coordination_batch01/'+p.name]=sha(p)
    return result


def root_path(root):
    root=Path(root).resolve();allowed=ROOT/'evidence/coordination_campaigns'
    fixture=any(x.startswith('rm65-campaign-fixture-') for x in root.parts)
    if not fixture and (root==allowed or not root.is_relative_to(allowed)):
        raise ValueError('NEW_CAMPAIGN_ROOT_REQUIRED')
    return root


def prepare(root,*,offline=False):
    root=root_path(root);freeze=json.loads((HERE/'freeze.json').read_text())
    if freeze['source_hashes']!=hashes():raise ValueError('FREEZE_HASH_MISMATCH')
    root.mkdir(parents=True,exist_ok=False,mode=0o700)
    state={'version':VERSION,'campaign_id':uuid.uuid4().hex,'output_root':str(root),'task':TASK,
           'source_hashes':hashes(),'freeze_sha256':sha(HERE/'freeze.json'),'status':'DRAFT',
           'authorization':None,'reserved_budget':0,'dispatches':[],'first_dispatch_at':None,
           'elapsed_wall_s':0.,'episodes':[dict(v,status='NOT_STARTED') for v in ORDER['order']],
           'offline_fixture':offline}
    grant={k:state[k] for k in ('version','campaign_id','output_root','task','source_hashes','freeze_sha256')}
    grant.update(generation_authorized=False,max_dispatches=0,planned_max_dispatches=50,
                 max_wall_s=3600,max_decisions_per_episode=7,max_shadow_dispatches=0,
                 model='gpt-6-astra',reasoning='medium',ephemeral=True,workers=1,
                 client_timeout_s=180,server_timeout_s=190,user_authorization_statement='')
    save(root/'ledger.json',state);save(root/'authorization_REQUEST_NOT_GRANTED.json',grant)
    return state


class Limit(Exception):
    pass


class Gate:
    def __init__(self,root,authorization,preflight,config,*,offline=False):
        self.root=root_path(root);self.handle=(self.root/'campaign.lock').open('a');self.clock_start=None
        try:fcntl.flock(self.handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.handle.close();raise ValueError('SINGLE_WORKER_LOCKED')
        try:
            self.state=json.loads((self.root/'ledger.json').read_text());s=self.state
            if s['status']!='DRAFT' or s['reserved_budget']!=0 or s['dispatches']:
                if s['status']=='RUNNING':
                    s.update(status='STOPPED',stop_reason='INTERRUPTED_OR_UNKNOWN_NO_RESUME');save(self.root/'ledger.json',s)
                raise ValueError('CAMPAIGN_NO_RESUME_OR_RESET')
            grant=json.loads(Path(authorization).read_text());check=json.loads(Path(preflight).read_text())
            if any(grant.get(k)!=s[k] for k in ('version','campaign_id','output_root','task','source_hashes','freeze_sha256')):
                raise ValueError('AUTHORIZATION_SCOPE_CHANGED')
            if s['source_hashes']!=hashes() or s['freeze_sha256']!=sha(HERE/'freeze.json'):
                raise ValueError('FROZEN_SOURCE_CHANGED')
            if s['output_root']!=str(self.root) or s['episodes']!=[dict(v,status='NOT_STARTED') for v in ORDER['order']]:
                raise ValueError('ORDER_OR_ROOT_CHANGED')
            params={'max_dispatches':50,'max_wall_s':3600,'max_decisions_per_episode':7,
                    'max_shadow_dispatches':0,'model':'gpt-6-astra','reasoning':'medium',
                    'ephemeral':True,'workers':1,'client_timeout_s':180,'server_timeout_s':190}
            if any(grant.get(k)!=v or type(grant.get(k)) is not type(v) for k,v in params.items()):raise ValueError('FROZEN_PARAMETERS_CHANGED')
            if offline:
                if not s['offline_fixture'] or grant.get('generation_authorized') is not False or not grant.get('offline_fixture'):
                    raise ValueError('EXPLICIT_OFFLINE_FIXTURE_REQUIRED')
            elif s['offline_fixture'] or grant.get('generation_authorized') is not True or not grant.get('user_authorization_statement','').strip():
                raise ValueError('NEW_CAMPAIGN_USER_AUTHORIZATION_REQUIRED')
            required={'status':'PASS','campaign_id':s['campaign_id'],'source_hashes':s['source_hashes'],
                      'freeze_sha256':s['freeze_sha256'],'actual_hostname':'Ubuntu-Robot',
                      'bridge_config_sha256':sha(config),'non_generating_auth_and_tunnel_check':True,
                      'client_timeout_s':180,'server_timeout_s':190,'model':'gpt-6-astra','reasoning':'medium','workers':1}
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(check['checked_at'])).total_seconds()
            if (not offline and socket.gethostname()!='Ubuntu-Robot') or not 0<=age<=900 or any(check.get(k)!=v for k,v in required.items()):
                raise ValueError('FRESH_BOUND_PRODUCTION_PREFLIGHT_REQUIRED')
            self.offline=offline
            s.update(status='RUNNING',authorization={'sha256':sha(authorization),'grant':grant})
            self.flush()
        except BaseException:self.handle.close();raise

    @property
    def deadline(self):
        return None if self.clock_start is None else self.clock_start+3600

    def elapsed(self):
        return 0. if self.clock_start is None else max(0.,time.monotonic()-self.clock_start)

    def flush(self):
        self.state['elapsed_wall_s']=self.elapsed();save(self.root/'ledger.json',self.state)

    def check_time(self):
        if self.elapsed()>=3600:raise Limit('WALL_TIME_LIMIT')

    def check_new_dispatch(self):
        self.check_time()
        if self.state['reserved_budget']>=50:raise Limit('GLOBAL_DISPATCH_LIMIT')

    def begin_episode(self,episode):
        pending=[e for e in self.state['episodes'] if e['status'] in ('NOT_STARTED','RUNNING')]
        if not pending or pending[0] is not episode or episode['status']!='NOT_STARTED':
            raise ValueError('FROZEN_EPISODE_ORDER_REQUIRED')
        episode.update(status='RUNNING',started_at=now());self.flush()

    def reserve(self,episode,folder,context):
        self.check_new_dispatch();s=self.state
        if s['status']!='RUNNING' or any(r['status']!='VALID' for r in s['dispatches']):
            raise ValueError('SINGLE_OUTSTANDING_REQUEST_OR_STOPPED')
        if hashes()!=s['source_hashes']:raise ValueError('SOURCE_CHANGED_BEFORE_DISPATCH')
        if episode not in s['episodes'] or episode['status']!='RUNNING':raise ValueError('ACTIVE_EPISODE_REQUIRED')
        pending=[e for e in s['episodes'] if e['status'] in ('NOT_STARTED','RUNNING')]
        if not pending or pending[0] is not episode:raise ValueError('FROZEN_EPISODE_ORDER_REQUIRED')
        prior=[r for r in s['dispatches'] if r['episode_id']==episode['episode_id']]
        if len(prior)>=7:raise Limit('EPISODE_DECISION_LIMIT')
        folder=Path(folder).resolve()
        if not folder.is_relative_to(self.root/episode['episode_id']) or folder.exists():
            raise ValueError('NEW_SCOPED_DECISION_FOLDER_REQUIRED')
        if self.clock_start is None:
            self.clock_start=time.monotonic();s['first_dispatch_at']=now()
            s['first_dispatch_monotonic_s']=self.clock_start
        row={'index':s['reserved_budget']+1,'episode_id':episode['episode_id'],'condition_id':episode['condition_id'],
             'decision':len(prior)+1,'status':'RESERVED','reserved_at':now(),'elapsed_wall_s':self.elapsed(),
             'artifact':str(folder.relative_to(self.root)),
             'context_sha256':hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()}
        s['dispatches'].append(row);s['reserved_budget']+=1;self.flush();return row

    def complete(self,row,folder):
        if row not in self.state['dispatches'] or row['status']!='RESERVED':raise ValueError('RESERVED_REQUEST_REQUIRED')
        accept_result(folder)
        response=json.loads((folder/'response.json').read_text());wire=json.loads((folder/'bridge_request.json').read_text())
        if response['source']!=('FAKE_MAC_BRIDGE_NOT_ASTRA' if self.offline else 'REAL_ASTRA_ATTEMPT'):
            raise ValueError('REAL_MOCK_SOURCE_MISMATCH')
        digest=hashlib.sha256(json.dumps(wire['context'],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        events=[json.loads(x) for x in response['events'].splitlines() if x.strip()]
        thread=next(e['thread_id'] for e in events if e['type']=='thread.started')
        if digest!=row['context_sha256'] or not thread or any(thread==r.get('thread_id') or wire['request_id']==r.get('request_id') for r in self.state['dispatches'] if r is not row):
            raise ValueError('CONTEXT_OR_SESSION_REUSE')
        row.update(status='VALID',thread_id=thread,request_id=wire['request_id'],finished_at=now(),
                   elapsed_completed_s=self.elapsed(),usage=response.get('usage'),latency_s=response['wall_latency_s'])
        self.flush()

    def finish(self,status,reason):
        self.state.update(status=status,stop_reason=reason,finished_at=now())
        for episode in self.state['episodes']:
            if episode['status']=='NOT_STARTED':episode.update(not_started_reason=reason)
        self.flush()

    def close(self):self.handle.close()
