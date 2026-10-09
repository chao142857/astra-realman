"""Standalone stdlib adapter: pin this repository version; never import a scene."""
import hashlib,json,sys
from pathlib import Path
VERSION='astra.realman.platform.v1'
class PlatformError(RuntimeError):pass
class Client:
    def __init__(self,reader=None,writer=None,public='/public'):
        self.reader=reader or sys.stdin;self.writer=writer or sys.stdout;self.public=Path(public);self.counter=0
        self.pending=set();self.replies={}
    def call(self,method,**params):
        return self.wait(self.begin(method,**params))
    def begin(self,method,**params):
        """Send without waiting; one caller can query a broker while execution runs."""
        self.counter+=1
        self.writer.write(json.dumps({'version':VERSION,'id':self.counter,'method':method,'params':params})+'\n');self.writer.flush()
        self.pending.add(self.counter);return self.counter
    def wait(self,request_id):
        if request_id not in self.pending:raise PlatformError('UNKNOWN_PENDING_REQUEST')
        while request_id not in self.replies:
            line=self.reader.readline()
            if not line:raise PlatformError('OWNER_DISCONNECTED')
            r=json.loads(line);identity=r.get('id')
            if r.get('version')!=VERSION or type(identity) is not int or identity not in self.pending or identity in self.replies:raise PlatformError('REPLY_BINDING')
            self.replies[identity]=r
        r=self.replies.pop(request_id);self.pending.remove(request_id)
        if not r['ok']:raise PlatformError(r['error'])
        return r['result']
    def reset(self):return self.call('reset')
    def observe(self):return self.call('observe')
    def execute(self,chunk,source_observation_id,proposal_id=None):
        return self.call('execute',chunk=chunk,source_observation_id=source_observation_id,proposal_id=proposal_id)
    def infer(self,source_observation_id):return self.call('infer',source_observation_id=source_observation_id)
    def commit(self,proposal_id):return self.call('commit',proposal_id=proposal_id)
    def research_capabilities(self):return self.call('research_capabilities')
    def broker_submit(self,request):return self.call('broker_submit',request=request)
    def broker_poll(self,request_id):return self.call('broker_poll',request_id=request_id)
    def broker_cancel(self,request_id):return self.call('broker_cancel',request_id=request_id)
    def world_submit(self,observation_ids,evidence_ids=None,backend='legacy_rgb_rays_v1',reference_world_id=None):
        return self.call('world_submit',observation_ids=observation_ids,evidence_ids=evidence_ids or [],backend=backend,reference_world_id=reference_world_id)
    def world_poll(self,request_id):return self.call('world_poll',request_id=request_id)
    def world_cancel(self,request_id):return self.call('world_cancel',request_id=request_id)
    def supervisor_from_broker(self,request_id):return self.call('supervisor_from_broker',request_id=request_id)
    def supervisor_load(self,plan):return self.call('supervisor_load',plan=plan)
    def supervisor_step(self,plan_id):return self.call('supervisor_step',plan_id=plan_id)
    def supervisor_cancel(self,plan_id):return self.call('supervisor_cancel',plan_id=plan_id)
    def events(self,after=0):return self.call('events',after=after)
    def stop(self):return self.call('stop')
    def finish(self,verdict='unknown'):return self.call('finish',verdict=verdict)
    def rgb(self,observation,camera):
        record=next(x for x in observation['rgb'] if x['camera']==camera)
        path=(self.public/record['file']).resolve()
        if not path.is_relative_to(self.public.resolve()):raise PlatformError('PUBLIC_PATH_ESCAPE')
        data=path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(data).hexdigest()!=record['sha256']:raise PlatformError('RGB_HASH')
        return data
class Replay:
    """Sequential public events only. execute never invokes physics or a policy."""
    def __init__(self,bundle):
        self.root=Path(bundle);self.index=json.loads((self.root/'index.json').read_text())
        if self.index['version']!=VERSION:raise PlatformError('REPLAY_VERSION')
        for name,h in self.index['files'].items():
            p=(self.root/name).resolve()
            if not p.is_relative_to(self.root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise PlatformError('REPLAY_HASH')
        self.rows=[json.loads(s) for s in (self.root/'events.jsonl').read_text().splitlines()];self.reset()
    def reset(self):self.cursor=0;return {'version':VERSION,'mode':'READ_ONLY_REPLAY','events':len(self.rows)}
    def events(self):
        while self.cursor<len(self.rows):
            r=self.rows[self.cursor];self.cursor+=1;yield r
    def observe(self):
        for e in self.events():
            if e['kind']=='observation':return e['data']
        raise EOFError('REPLAY_END')
    def execute(self,*_,**__):raise PlatformError('REPLAY_EXECUTION_FORBIDDEN')
    def score_private(self):raise PlatformError('PRIVATE_SCORE_NOT_IN_REPLAY')
    def rgb(self,observation,camera):return Client(public=self.root).rgb(observation,camera)
