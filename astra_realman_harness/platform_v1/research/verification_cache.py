"""Trusted-host proof cache, not execution authority.

Proofs contain immutable canonical bytes. Mutable registry aliases are watched
recursively; any normal JSON mutation invalidates their version token. External
sensor files are never declared immutable: inode/ctime/mtime guards invalidate
proofs and force original hash validation. Cached sensor bytes themselves are
immutable. Full audit bypasses all proof and sensor reuse.

Single-owner synchronous use only. Arbitrary trusted-host monkeypatching,
bypassing dict overrides, or a malicious filesystem/kernel is outside this
boundary (as with the original in-process receipt registry).
"""
import hashlib,json,time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


def canonical(value):return json.dumps(value,sort_keys=True,allow_nan=False).encode()

def wrap(value,touch):
    if isinstance(value,dict):return WatchedDict(value,touch)
    if isinstance(value,list):return WatchedList(value,touch)
    return value

class WatchedDict(dict):
    def __init__(self,value,touch):
        self._touch=touch
        dict.__init__(self,((k,wrap(v,touch)) for k,v in value.items()))
    def __setitem__(self,k,v):self._touch();dict.__setitem__(self,k,wrap(v,self._touch))
    def __delitem__(self,k):self._touch();dict.__delitem__(self,k)
    def clear(self):self._touch();dict.clear(self)
    def pop(self,k,*default):self._touch();return dict.pop(self,k,*default)
    def popitem(self):self._touch();return dict.popitem(self)
    def update(self,*args,**kwargs):
        for k,v in dict(*args,**kwargs).items():self[k]=v
    def setdefault(self,k,default=None):
        if k not in self:self[k]=default
        return self[k]
    def __ior__(self,other):self.update(other);return self

class WatchedList(list):
    def __init__(self,value,touch):self._touch=touch;list.__init__(self,(wrap(v,touch) for v in value))
    def __setitem__(self,k,v):
        self._touch();list.__setitem__(self,k,[wrap(x,self._touch) for x in v] if isinstance(k,slice) else wrap(v,self._touch))
    def __delitem__(self,k):self._touch();list.__delitem__(self,k)
    def append(self,v):self._touch();list.append(self,wrap(v,self._touch))
    def extend(self,v):self._touch();list.extend(self,[wrap(x,self._touch) for x in v])
    def insert(self,k,v):self._touch();list.insert(self,k,wrap(v,self._touch))
    def pop(self,k=-1):self._touch();return list.pop(self,k)
    def remove(self,v):self._touch();list.remove(self,v)
    def clear(self):self._touch();list.clear(self)
    def reverse(self):self._touch();list.reverse(self)
    def sort(self,*a,**k):self._touch();list.sort(self,*a,**k)
    def __iadd__(self,v):self.extend(v);return self
    def __imul__(self,n):self._touch();list.__imul__(self,n);return self

class Registry(dict):
    """Per-entry mutation token; insertion of a new record leaves old tokens valid."""
    def __init__(self,value=()):
        dict.__init__(self);self.tokens={}
        self.update(value)
    def __setitem__(self,k,v):
        def touch():self.tokens[k]=object()
        touch();dict.__setitem__(self,k,wrap(v,touch))
    def __delitem__(self,k):self.tokens.pop(k,None);dict.__delitem__(self,k)
    def clear(self):self.tokens.clear();dict.clear(self)
    def pop(self,k,*default):self.tokens.pop(k,None);return dict.pop(self,k,*default)
    def popitem(self):k,v=dict.popitem(self);self.tokens.pop(k,None);return k,v
    def update(self,*a,**kw):
        for k,v in dict(*a,**kw).items():self[k]=v
    def setdefault(self,k,default=None):
        if k not in self:self[k]=default
        return self[k]
    def __ior__(self,other):self.update(other);return self

REGISTRIES=('worlds','observations','evidence','geometry_update_receipts','grounding_sources','semantic_world_pins')

def fingerprint(path):
    s=Path(path).stat()
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)

@dataclass(frozen=True)
class FileSnapshot:
    path: str
    signature: tuple
    sha256: str
    data: bytes

@dataclass(frozen=True)
class Proof:
    world_bytes: bytes
    dependencies: tuple
    files: tuple
    parent: object = None

class VerificationCache:
    def __init__(self,store):
        self.store=store;self.proofs={};self.files={};self.scope=None;self.force_audit=False
        self.metrics={};self.reset_metrics()
    def reset_metrics(self):
        self.metrics={k:0 for k in ('proof_hits','proof_misses','file_reads','file_bytes','file_hashes','file_reuses','depth_decodes','depth_reuses','history_file_guards')}
        self.metrics.update(current_evidence_validation_s=0.,historical_evidence_io_hash_s=0.,history_validation_s=0.)
    @property
    def enabled(self):return self.store.validation_cache_enabled and not self.force_audit
    @contextmanager
    def transaction(self,current_id=None):
        if self.scope is not None or not self.enabled:
            yield;return
        self.scope={'current_id':current_id,'files':{},'depth':{}}
        try:yield
        finally:self.scope=None
    @contextmanager
    def audit(self):
        old=self.force_audit;self.force_audit=True
        try:yield
        finally:self.force_audit=old
    def read(self,path,expected,error,max_bytes=None,historical=False):
        path=Path(path);key=str(path);start=time.monotonic();signature=fingerprint(path)
        cached=None
        if self.enabled and self.scope is not None:
            cached=self.scope['files'].get(key)
            if cached is None and historical:cached=self.files.get(key)
        if cached is not None and cached.signature==signature and cached.sha256==expected:
            self.metrics['file_reuses']+=1;data=cached.data
        else:
            data=path.read_bytes();self.metrics['file_reads']+=1;self.metrics['file_bytes']+=len(data)
            actual=hashlib.sha256(data).hexdigest();self.metrics['file_hashes']+=1
            if fingerprint(path)!=signature:raise ValueError('SENSOR_CHANGED_DURING_READ')
            if actual!=expected or (max_bytes is not None and len(data)>max_bytes):raise ValueError(error)
            cached=FileSnapshot(key,signature,actual,data)
        if self.enabled:
            self.files[key]=cached
            if self.scope is not None:self.scope['files'][key]=cached
        self.metrics['historical_evidence_io_hash_s' if historical else 'current_evidence_validation_s']+=time.monotonic()-start
        return data
    def check_transaction(self):
        if self.scope is not None:
            for item in tuple(self.scope['files'].values()):
                if fingerprint(item.path)!=item.signature:
                    self.read(item.path,item.sha256,'SENSOR_CHANGED_BEFORE_PUBLICATION')
    def sensor_paths(self,oid):
        o=self.store.get(oid);paths=[]
        for rgb in o['rgb']:
            paths.append(self.store.root/rgb['file'])
            for rec in o.get('depth',[]):
                if rec['camera']==rgb['camera']:
                    paths.extend(self.store.root/Path(rgb['file']).parent/rec[k]['file'] for k in ('depth','validity'))
        return paths
    def dependencies(self,world):
        parent_id=world['binding'].get('reference_world_id')
        parent=self.proofs.get(parent_id)
        deps=[]
        files=[]
        # The non-update semantic root is pinned as a whole dependency closure.
        pending=[world];seen=set()
        while pending:
            w=pending.pop();wid=w['world_id']
            if wid in seen:continue
            seen.add(wid);keys=[('worlds',wid),('observations',w['state']['observation_id'])]
            if w['state'].get('geometry_update_version'):keys.append(('geometry_update_receipts',wid))
            if wid in self.store.semantic_world_pins:keys.append(('semantic_world_pins',wid))
            for eid in w['binding'].get('evidence_ids',[]):keys.extend([('evidence',eid),('grounding_sources',eid)])
            for name,key in keys:
                registry=getattr(self.store,name)
                if key in registry:deps.append((name,key,registry,registry.tokens[key]))
            for p in self.sensor_paths(w['state']['observation_id']):
                snapshot=self.files.get(str(p))
                if snapshot is not None:files.append(snapshot)
            pid=w['binding'].get('reference_world_id') or w['binding'].get('geometry_world_id')
            if pid and pid not in self.proofs:pending.append(self.store.get_world(pid))
        # Shared immutable data, not repeated ancestor byte copies.
        return tuple({(n,k):(n,k,r,t) for n,k,r,t in deps}.values()),tuple({f.path:f for f in files}.values())
    def remember(self,world):
        if self.enabled:
            deps,files=self.dependencies(world)
            self.proofs[world['world_id']]=Proof(canonical(world),deps,files,
                self.proofs.get(world['binding'].get('reference_world_id')))
    def hit(self,world):
        if not self.enabled:return False
        p=self.proofs.get(world['world_id']);start=time.monotonic()
        if p is not None and p.world_bytes==canonical(world):
            valid=True;node=p;seen_files=set();seen_deps=set()
            while node is not None and valid:
                for name,key,registry,token in node.dependencies:
                    identity=(name,key)
                    if identity in seen_deps:continue
                    seen_deps.add(identity);now=getattr(self.store,name)
                    if now is not registry or now.tokens.get(key) is not token:valid=False;break
                if valid:
                    for f in node.files:
                        if f.path in seen_files:continue
                        seen_files.add(f.path);self.metrics['history_file_guards']+=1
                        if fingerprint(f.path)!=f.signature:valid=False;break
                node=node.parent
            if valid:
                self.metrics['proof_hits']+=1;self.metrics['history_validation_s']+=time.monotonic()-start
                return True
        self.metrics['proof_misses']+=1;self.metrics['history_validation_s']+=time.monotonic()-start
        return False
