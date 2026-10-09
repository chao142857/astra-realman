"""Read-only process adapter, checkpoint-neutral, public snapshots in /input only."""
import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
import jsonschema
from sim_skills.full_pnp.wire import strict_json
from .contracts import clone, digest, fields, semantic_schema, WORLD_VERSION
from .jobs import ProcessJob

class WorldHead:
    def __init__(self, root, store, *, epoch, deadline, emit, worker_path=None):
        self.root=root;self.store=store;self.epoch=epoch;self.deadline=deadline;self.emit=emit
        self.worker_path=Path(worker_path or Path(__file__).with_name('geometry_worker.py'))
        self.rows={};self.job=None;self.closed=False

    def submit(self, observation_ids, evidence_ids, backend, reference_world_id=None):
        if self.closed or self.job: raise ValueError('ONE_WORLD_WORKER_OR_CLOSED')
        if len(self.rows)>=64: raise ValueError('WORLD_OBSERVATION_BUDGET')
        if backend not in ('legacy_rgb_rays_v1','bbox_rays_v1'): raise ValueError('WORLD_BACKEND')
        if not isinstance(observation_ids,list) or not 1<=len(observation_ids)<=8: raise ValueError('WORLD_OBSERVATION_IDS')
        if len(set(observation_ids))!=len(observation_ids): raise ValueError('DUPLICATE_OBSERVATION')
        identity='world-%03d'%(len(self.rows)+1);folder=self.root/identity;folder.mkdir(parents=True,exist_ok=False)
        row={'request_id':identity,'status':'PREPARING','error':None,'result':None,'usage_raw':None}
        self.rows[identity]=row
        try:
            inp=folder/'input_only';inp.mkdir();code=folder/'worker_code';code.mkdir()
            observations=[]
            for oid in observation_ids:
                o=self.store.get(oid)
                if observations and o['captured_monotonic']<observations[-1]['captured_monotonic']: raise ValueError('HISTORY_TIME_ORDER')
                item={k:clone(o[k]) for k in ('observation_id','captured_monotonic','capture_span_s','calibration','state','execution_epoch')}
                item.update(images={},image_sha256={})
                for camera in ('assembly','fixed','wrist'):
                    data,record=self.store.image(oid,camera);name='%d-%s.png'%(len(observations),camera)
                    (inp/name).write_bytes(data);item['images'][camera]=name;item['image_sha256'][camera]=record['sha256']
                observations.append(item)
            if observations[-1]['execution_epoch']!=self.epoch(): raise ValueError('WORLD_CURRENT_EPOCH')
            regions=[];provenance='PUBLIC_GEOMETRY'
            for eid in evidence_ids:
                e=self.store.get_evidence(eid)
                if e['role'] not in ('semantic_e0','local_reground'): raise ValueError('GEOMETRY_EVIDENCE_ROLE')
                jsonschema.validate(e['result'],semantic_schema())
                if e['provenance']=='FAKE_MODEL_RAW': provenance='FAKE_MODEL_RAW'
                allowed={a['id']:a for a in e['attachments']}
                for r in e['result']['regions']:
                    if r['attachment_id'] not in allowed: raise ValueError('UNSEEN_REGION_ATTACHMENT')
                    a=allowed[r['attachment_id']];b=r['bbox']
                    if not 0<=b[0]<b[2]<=1 or not 0<=b[1]<b[3]<=1: raise ValueError('REGION_BBOX')
                    clipped=b[0]<=0 or b[1]<=0 or b[2]>=1 or b[3]>=1
                    if a['observation_id'] not in observation_ids: raise ValueError('REGION_NOT_IN_PUBLIC_HISTORY')
                    crop=a['transform']['crop_xyxy_pixels'];width,height=a['transform']['source_resolution']
                    if crop: b=[(crop[0]+b[0]*(crop[2]-crop[0]))/width,(crop[1]+b[1]*(crop[3]-crop[1]))/height,
                                (crop[0]+b[2]*(crop[2]-crop[0]))/width,(crop[1]+b[3]*(crop[3]-crop[1]))/height]
                    regions.append({'entity_id':r['entity_id'],'label':r['label'],'bbox':b,
                        'observation_id':a['observation_id'],'camera':a['camera'],'evidence_id':eid,'identity_status':r['identity_status'],
                        'clipped_in_selected_image':clipped})
            reference=self.store.get_world(reference_world_id) if reference_world_id else None
            binding={'version':WORLD_VERSION,'episode_id':self.store.episode_id,'execution_epoch':self.epoch(),
                'observation_ids':observation_ids,'evidence_ids':evidence_ids,'reference_world_id':reference_world_id,
                'world_revision':reference['world_revision'] if reference else self.store.revision,
                'capture_times':[o['captured_monotonic'] for o in observations],
                'calibration_hashes':[digest(o['calibration']) for o in observations]}
            wire={'binding':binding,'backend':backend,'observations':observations,'regions':regions}
            data=json.dumps(wire,sort_keys=True,allow_nan=False).encode();(inp/'world_input.json').write_bytes(data)
            for p in inp.iterdir():p.chmod(0o444)
            shutil.copy2(self.worker_path,code/'worker.py')
            base=Path(__file__).resolve().parents[2]/'sim_skills/full_pnp'
            for name in ('rgb.py','requirements.py'):shutil.copy2(base/name,code/name)
            venv=str(Path(sys.prefix).resolve())
            command=['/usr/bin/bwrap','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
                '--ro-bind',venv,venv,'--ro-bind',str(inp),'/input','--ro-bind',str(code),'/code',
                '--tmpfs','/tmp','--proc','/proc','--dev','/dev','--unshare-all','--die-with-parent','--new-session',
                '--chdir','/input',sys.executable,'-B','/code/worker.py','--sha256',hashlib.sha256(data).hexdigest()]
            if time.monotonic()>=self.deadline:raise ValueError('NO_REMAINING_WORLD_BUDGET')
            job=ProcessJob(folder,command,{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},min(time.monotonic()+10,self.deadline))
            row.update(status='STARTED',binding=binding,backend=backend,provenance=provenance,
                worker_sha256=hashlib.sha256(self.worker_path.read_bytes()).hexdigest(),pid=job.proc.pid)
            self.job=(identity,job)
        except Exception as exc:row.update(status='FAILED',error=repr(exc));self.save(row);raise
        self.save(row);return clone(row)

    def save(self,row):
        (self.root/row['request_id']/'world_attempt.json').write_text(json.dumps(row,indent=2,allow_nan=False))
        self.emit('WORLD_STAGE',{'request_id':row['request_id'],'status':row['status']})

    def tick(self):
        if not self.job:return
        identity,job=self.job;result=job.poll()
        if result is None:return
        self.job=None;row=self.rows[identity]
        try:
            if result['cancel_reason'] or result['return_code']!=0:raise ValueError(result['cancel_reason'] or 'WORLD_WORKER_FAILED')
            if len(result['bytes'])>2*1024*1024:raise ValueError('WORLD_RESULT_SIZE')
            out=strict_json(result['bytes']);fields(out,('binding','state'))
            if out['binding']!=row['binding']:raise ValueError('WORLD_BINDING')
            if row['binding']['execution_epoch']!=self.epoch():raise ValueError('STALE_WORLD_EXECUTION_EPOCH')
            if row['binding']['world_revision']!=self.store.revision:raise ValueError('STALE_WORLD_REVISION')
            # A replacement worker cannot manufacture provenance or a simulator-state field.
            fields(out['state'],('backend','observation_id','captured_monotonic','scene_healthy','entities',
                'robot_state','history_semantics','geometry_only','task_identity_verified'))
            if out['state']['task_identity_verified'] is not False or out['state']['geometry_only'] is not True:raise ValueError('GEOMETRY_NOT_IDENTITY_AUTHORITY')
            source=self.store.get(row['binding']['observation_ids'][-1])
            if out['state']['robot_state']!=source['state'] or out['state']['observation_id']!=source['observation_id']:raise ValueError('WORLD_STATE_SOURCE')
            if out['state']['captured_monotonic']!=source['captured_monotonic'] or out['state']['backend']!=row['backend'] or type(out['state']['scene_healthy']) is not bool:raise ValueError('WORLD_METADATA')
            for entity in out['state']['entities'].values():
                required={'status','point_world_m','uncertainty_radius_m','identity_status','sources','uncertainty_semantics'}
                if not required<=set(entity) or set(entity)-required-{'reason','residual_m'}:raise ValueError('WORLD_ENTITY_FIELDS')
                if entity['identity_status']!='hypothesis_not_verified':raise ValueError('GEOMETRY_IDENTITY_CLAIM')
                if entity['status'] not in ('coarse','unknown'):raise ValueError('WORLD_ENTITY_STATUS')
                if entity['status']=='coarse':
                    xyz=entity['point_world_m'];radius=entity['uncertainty_radius_m']
                    if len(xyz)!=3 or not all(type(v) in (int,float) and math.isfinite(v) for v in xyz) or not .02<=radius:raise ValueError('WORLD_UNCERTAINTY')
                elif entity['point_world_m'] is not None or entity['uncertainty_radius_m'] is not None:raise ValueError('UNKNOWN_IS_NOT_A_POSITION')
                for view in entity['sources']:
                    fields(view,('observation_id','camera','pixel','captured_monotonic','source'))
                    if view['observation_id']!=source['observation_id'] or view['captured_monotonic']!=source['captured_monotonic'] or view['camera'] not in source['calibration']:raise ValueError('WORLD_ENTITY_SOURCE')
                    pixel=view['pixel'];width,height=source['calibration'][view['camera']]['resolution']
                    if len(pixel)!=2 or not 0<=pixel[0]<width or not 0<=pixel[1]<height:raise ValueError('WORLD_SOURCE_PIXEL')
            reference=row['binding']['reference_world_id']
            if reference:
                if row['binding']['world_revision']!=self.store.revision:raise ValueError('STALE_WORLD_REVISION')
                row['result']={'version':WORLD_VERSION,'kind':'WorldCheck','binding':row['binding'],'state':out['state'],
                    'created_monotonic':time.monotonic(),'provenance':row['provenance']}
            else:row['result']=self.store.publish_world(out['state'],row['binding'],row['provenance'])
            row['status']='READY'
        except Exception as exc:row.update(status='CANCELLED' if result['cancel_reason'] else 'FAILED',error=repr(exc))
        self.save(row)

    def poll(self,request_id):
        self.tick()
        if request_id not in self.rows:raise ValueError('UNKNOWN_WORLD_REQUEST')
        return clone(self.rows[request_id])

    def cancel(self,request_id):
        if request_id not in self.rows:raise ValueError('UNKNOWN_WORLD_REQUEST')
        if self.job and self.job[0]==request_id:self.job[1].cancel('EXTERNAL_CANCEL')
        return self.poll(request_id)

    def close(self):
        self.closed=True
        if self.job:self.job[1].close();self.tick()
