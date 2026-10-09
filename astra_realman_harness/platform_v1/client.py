"""Standalone stdlib adapter: pin this repository version; never import a scene."""
import hashlib,json,sys
from pathlib import Path
VERSION='astra.realman.platform.v1'
class PlatformError(RuntimeError):pass
class Client:
    def __init__(self,reader=None,writer=None,public='/public'):
        self.reader=reader or sys.stdin;self.writer=writer or sys.stdout;self.public=Path(public);self.counter=0
    def call(self,method,**params):
        self.counter+=1
        self.writer.write(json.dumps({'version':VERSION,'id':self.counter,'method':method,'params':params})+'\n');self.writer.flush()
        line=self.reader.readline()
        if not line:raise PlatformError('OWNER_DISCONNECTED')
        r=json.loads(line)
        if r.get('version')!=VERSION or r.get('id')!=self.counter:raise PlatformError('REPLY_BINDING')
        if not r['ok']:raise PlatformError(r['error'])
        return r['result']
    def reset(self):return self.call('reset')
    def observe(self):return self.call('observe')
    def execute(self,chunk,source_observation_id,proposal_id=None):
        return self.call('execute',chunk=chunk,source_observation_id=source_observation_id,proposal_id=proposal_id)
    def infer(self,source_observation_id):return self.call('infer',source_observation_id=source_observation_id)
    def commit(self,proposal_id):return self.call('commit',proposal_id=proposal_id)
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
