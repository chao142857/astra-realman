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
        self.learned_config=None
        self.public_plane=None
        self.feedback_provider=None
        self.rebuild_requests=[]

    def build(self, observation_id):
        """Explicit initial learned geometry; semantic E0 still uses the existing Broker."""
        return self.submit([observation_id], [], 'da3_small_v1')

    def bind_semantic_grounding(self, world_id, evidence_id, task):
        """Publish semantics on unchanged measured geometry; zero sensing/model calls."""
        from .semantic_binding import bind_grounding
        if self.closed or self.job or time.monotonic() >= self.deadline:
            raise ValueError('WORLD_BUSY_CLOSED_OR_DEADLINE')
        world = self.store.get_world(world_id)
        if world['binding']['execution_epoch'] != self.epoch(): raise ValueError('STALE_BINDING_EPOCH')
        return bind_grounding(self.store, world_id, evidence_id, task)

    def update(self, reference_world_id, observation_id, completed_monotonic):
        """Current RGB/FK update, synchronously on CPU; zero learned jobs."""
        from .cheap_update import measure
        if self.closed or self.job:raise ValueError('WORLD_BUSY_OR_CLOSED')
        reference=self.store.get_world(reference_world_id)
        if reference['world_revision']!=self.store.revision:raise ValueError('STALE_UPDATE_BASE')
        if reference['state'].get('initialization') == 'geometry_first_v2':
            raise ValueError('GEOMETRY_FIRST_UPDATE_CONTRACT_ONLY_NOT_ACCEPTED')
        source=self.store.get(observation_id)
        if source['execution_epoch']!=self.epoch():raise ValueError('STALE_UPDATE_EPOCH')
        previous=self.store.get(reference['state']['observation_id'])
        start=time.monotonic()
        if reference['state'].get('geometry_backend')=='rgbd_object_state_v1':
            from .rgbd_world import update as rgbd_update
            feedback=source.get('execution_feedback')
            if feedback is None and self.feedback_provider is not None:
                feedback=self.feedback_provider(completed_monotonic)
            state=rgbd_update(reference['state'],previous,source,self._images(observation_id),
                {c:self.store.depth(observation_id,c) for c in ('assembly','fixed','wrist')},
                self._images,completed_monotonic,feedback)
        elif reference['state']['backend']=='object_silhouette_world_v1':
            from .object_tracking import measure as object_measure
            state=object_measure(reference['state'],previous,source,self._images(previous['observation_id']),
                self._images(observation_id),completed_monotonic,reference['state']['object_config']['tracker'])
        else:
            state=measure(reference['state'],previous,source,self._images(previous['observation_id']),
                self._images(observation_id),completed_monotonic)
        if reference['world_revision']!=self.store.revision or source['execution_epoch']!=self.epoch():
            raise ValueError('STALE_UPDATE_AFTER_COMPUTE')
        if self.closed or time.monotonic()>=self.deadline:raise ValueError('UPDATE_DEADLINE_OR_CLOSED')
        state['resource_metrics']['update_wall_s']=time.monotonic()-start
        binding={'observation_ids':[observation_id],'execution_epoch':self.epoch(),
            'reference_world_id':reference_world_id,'world_revision':reference['world_revision'],
            'completed_monotonic':completed_monotonic}
        return self.store.publish_world(state,binding,reference['provenance'])

    def build_geometry_first(self, observation_id, config):
        """Geometry-only RGB-D Build; deliberately no semantic/evidence argument."""
        from .rgbd_world import build_geometry_first
        from .model_context import calibration_key, VISIBILITY_VERSION
        if self.closed or self.job: raise ValueError('WORLD_BUSY_OR_CLOSED')
        o = self.store.get(observation_id); revision = self.store.revision
        if o['execution_epoch'] != self.epoch(): raise ValueError('STALE_BUILD_EPOCH')
        if self.public_plane is None: raise ValueError('PUBLIC_PLANE_REQUIRED')
        start = time.monotonic()
        depths = {c: self.store.depth(observation_id, c) for c in ('assembly', 'fixed', 'wrist')}
        loaded = time.monotonic()
        state = build_geometry_first(o, depths, config, self.public_plane)
        state['resource_metrics']['sensor_load_s'] = loaded - start
        if revision != self.store.revision or o['execution_epoch'] != self.epoch(): raise ValueError('STALE_BUILD_AFTER_COMPUTE')
        if self.closed or time.monotonic() >= self.deadline: raise ValueError('BUILD_DEADLINE_OR_CLOSED')
        return self.store.publish_world(state, {'observation_ids': [observation_id], 'evidence_ids': [],
            'execution_epoch': self.epoch(), 'world_revision': revision,
            'image_sha256': {c: self.store.image(observation_id, c)[1]['sha256'] for c in ('assembly','fixed','wrist')}},
            'PUBLIC_RGBD_MEASUREMENT', read_versions={calibration_key(o['calibration']): 1,
                'geometry_first/' + digest(config): 1, 'visibility/' + VISIBILITY_VERSION: 1})

    def build_objects(self, observation_id, semantic_evidence_id, masks, config):
        """Host-supplied pretrained/diagnostic masks bound to existing Broker evidence.

        No paths/model dispatch in this method. Caller records segmentation outside
        the owner process. Existing Broker E0 schema and immutable RGB remain authority.
        Offline annotations keep their own provenance; they never become model raw.
        """
        return self._build_instances(observation_id,semantic_evidence_id,masks,config,'silhouette')

    def build_rgbd(self, observation_id, semantic_evidence_id, masks, config):
        """Same semantic/mask binding, explicit sensor geometry; no model job."""
        return self._build_instances(observation_id,semantic_evidence_id,masks,config,'rgbd')

    def build_rgbd_from_semantic(self, observation_id, semantic_evidence_id, config):
        """Real E0 bbox -> current measured masks -> existing RGB-D Build. No calls."""
        if self.store.get_evidence(semantic_evidence_id)['provenance']!='MODEL_RAW':
            raise ValueError('REAL_E0_REQUIRED_FOR_SEMANTIC_BUILD')
        from .semantic_rgbd import prepare_masks
        masks,report=prepare_masks(self.store,observation_id,semantic_evidence_id,self.public_plane)
        return {'world':self.build_rgbd(observation_id,semantic_evidence_id,masks,config),'mask_report':report}

    def _build_instances(self, observation_id, semantic_evidence_id, masks, config, backend):
        from .fusion import semantic_schema as scene_schema
        if self.closed or self.job:raise ValueError('WORLD_BUSY_OR_CLOSED')
        if self.public_plane is None:raise ValueError('PUBLIC_PLANE_REQUIRED')
        observation=self.store.get(observation_id);revision=self.store.revision
        if observation['execution_epoch']!=self.epoch():raise ValueError('STALE_BUILD_EPOCH')
        e=self.store.get_evidence(semantic_evidence_id)
        if e['role']!='semantic_e0' or e['observation_ids']!=[observation_id]:raise ValueError('FROZEN_SEMANTIC_INPUT_REQUIRED')
        jsonschema.validate(e['result'],scene_schema())
        attachments={a['id']:a for a in e['attachments']}
        if len(attachments)!=3 or {a['camera'] for a in attachments.values()}!={'assembly','fixed','wrist'}:
            raise ValueError('THREE_FROZEN_RGB_REQUIRED')
        image_hashes={}
        for a in attachments.values():
            _,record=self.store.image(observation_id,a['camera'])
            if a['observation_id']!=observation_id or a['source_sha256']!=record['sha256'] or a['transform']['crop_xyxy_pixels'] is not None:
                raise ValueError('FROZEN_IMAGE_BINDING')
            if a['transform']['source_resolution']!=observation['calibration'][a['camera']]['resolution']:
                raise ValueError('IMAGE_RESOLUTION_BINDING')
            image_hashes[a['camera']]=record['sha256']
        entities=[]
        for entity in e['result']['entities']:
            ent=clone(entity);views=[]
            for v in ent['views']:
                if v['attachment_id'] not in attachments:raise ValueError('UNSEEN_SEMANTIC_VIEW')
                a=attachments[v['attachment_id']]
                if a['camera'] in [x['camera'] for x in views]:raise ValueError('DUPLICATE_ENTITY_VIEW')
                box=v['bbox']
                if not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:raise ValueError('REGION_BBOX')
                rec=masks.get((ent['entity_id'],a['camera']))
                if rec and (rec['image_sha256']!=image_hashes[a['camera']] or rec.get('semantic_evidence_id')!=semantic_evidence_id):
                    raise ValueError('MASK_EVIDENCE_BINDING')
                if rec and rec.get('bbox_prompt_normalized')!=box:raise ValueError('MASK_PROMPT_BINDING')
                views.append({**v,'camera':a['camera']})
            ent['views']=views;entities.append(ent)
        ids={ent['entity_id'] for ent in entities}
        if e['result']['task_target_id'] is not None and e['result']['task_target_id'] not in ids:
            raise ValueError('TASK_TARGET_NOT_AN_ENTITY')
        for relation in e['result']['relations']:
            if relation['subject'] not in ids or relation['object'] not in ids or not set(relation['evidence_refs'])<=set(attachments):
                raise ValueError('UNBOUND_SEMANTIC_RELATION')
        if backend=='rgbd':
            from .rgbd_world import build
            state=build(observation,entities,masks,
                {c:self.store.depth(observation_id,c) for c in ('assembly','fixed','wrist')},
                config,self.public_plane,{'evidence_id':semantic_evidence_id,'provenance':e['provenance']})
        else:
            from .object_world import build
            state=build(observation,entities,masks,config['geometry'],self.public_plane,
                {'evidence_id':semantic_evidence_id,'provenance':e['provenance']})
        state['object_config']=clone(config)
        state['relations']=clone(e['result']['relations']);state['unknowns']=clone(e['result']['unknowns'])
        state['task_target_id']=e['result']['task_target_id']
        if self.store.revision!=revision or observation['execution_epoch']!=self.epoch():raise ValueError('STALE_BUILD_AFTER_COMPUTE')
        if self.closed or time.monotonic()>=self.deadline:raise ValueError('BUILD_DEADLINE_OR_CLOSED')
        binding={'observation_ids':[observation_id],'evidence_ids':[semantic_evidence_id],
            'world_revision':revision,'execution_epoch':self.epoch(),'image_sha256':image_hashes}
        from .model_context import calibration_key,VISIBILITY_VERSION
        return self.store.publish_world(state,binding,e['provenance'],read_versions={
            'semantic/'+semantic_evidence_id:1,calibration_key(observation['calibration']):1,
            'object_config/'+digest(config):1,'task_scope/coarse_precontact_v1':1,
            'task_selection/'+digest({'semantic_evidence_id':semantic_evidence_id,'target_id':state['task_target_id']}):1,
            'visibility/'+VISIBILITY_VERSION:1})

    def request_rebuild(self, reference_world_id, observation_id, reason, components):
        """Record an explicit request only. No hidden geometry or semantic dispatch."""
        reference=self.store.get_world(reference_world_id);source=self.store.get(observation_id)
        if self.closed or reference['world_revision']!=self.store.revision:raise ValueError('STALE_REBUILD_BASE')
        if source['execution_epoch']!=self.epoch():raise ValueError('STALE_REBUILD_EPOCH')
        if source['captured_monotonic']<reference['state']['captured_monotonic']:raise ValueError('OLD_REBUILD_OBSERVATION')
        if not reason or not components or not set(components)<={'geometry','semantic'}:raise ValueError('REBUILD_REQUEST')
        request={'request_id':'rebuild-%03d'%(len(self.rebuild_requests)+1),
            'reference_world_id':reference_world_id,'world_revision':reference['world_revision'],
            'observation_id':observation_id,'execution_epoch':self.epoch(),'reason':reason,
            'components':list(components),'status':'REQUESTED_NOT_DISPATCHED','DA3_calls':0,'Astra_calls':0}
        self.rebuild_requests.append(request);self.emit('REBUILD_REQUEST',request)
        return clone(request)

    def _images(self, observation_id):
        import io
        import numpy as np
        from PIL import Image
        return {c:np.array(Image.open(io.BytesIO(self.store.image(observation_id,c)[0])).convert('RGB'))
            for c in ('assembly','fixed','wrist')}

    def configure_learned(self, config):
        from .learned_runtime import validate_config
        if self.job or self.rows: raise ValueError('CONFIGURE_BEFORE_WORLD_WORK')
        validate_config(config)
        self.learned_config=clone(config)

    def submit(self, observation_ids, evidence_ids, backend, reference_world_id=None):
        if self.closed or self.job: raise ValueError('ONE_WORLD_WORKER_OR_CLOSED')
        if len(self.rows)>=64: raise ValueError('WORLD_OBSERVATION_BUDGET')
        if backend not in ('legacy_rgb_rays_v1','bbox_rays_v1','da3_small_v1'): raise ValueError('WORLD_BACKEND')
        if backend=='da3_small_v1' and self.learned_config is None: raise ValueError('DA3_NOT_CONFIGURED_NOT_ACCEPTED')
        if backend=='da3_small_v1' and (len(observation_ids)!=1 or evidence_ids): raise ValueError('DA3_FROZEN_GEOMETRY_ONLY')
        if not isinstance(observation_ids,list) or not 1<=len(observation_ids)<=8: raise ValueError('WORLD_OBSERVATION_IDS')
        if len(set(observation_ids))!=len(observation_ids): raise ValueError('DUPLICATE_OBSERVATION')
        identity='world-%03d'%(len(self.rows)+1);folder=self.root/identity;folder.mkdir(parents=True,exist_ok=False)
        row={'request_id':identity,'status':'PREPARING','error':None,'result':None,'usage_raw':None,
             'preparation_started_monotonic':time.monotonic()}
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
                'world_revision':self.store.revision,
                'capture_times':[o['captured_monotonic'] for o in observations],
                'calibration_hashes':[digest(o['calibration']) for o in observations]}
            wire={'binding':binding,'backend':backend,'observations':observations,'regions':regions}
            if backend=='da3_small_v1':
                wire['learned']={k:v for k,v in self.learned_config.items() if k not in ('venv','weights')}
            data=json.dumps(wire,sort_keys=True,allow_nan=False).encode();(inp/'world_input.json').write_bytes(data)
            for p in inp.iterdir():p.chmod(0o444)
            shutil.copy2(self.worker_path,code/'worker.py')
            base=Path(__file__).resolve().parents[2]/'sim_skills/full_pnp'
            for name in ('rgb.py','requirements.py'):shutil.copy2(base/name,code/name)
            if backend=='da3_small_v1':shutil.copy2(Path(__file__).with_name('da3_geometry.py'),code/'da3_geometry.py')
            venv=str(Path(sys.prefix).resolve())
            command=['/usr/bin/bwrap','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
                '--ro-bind',venv,venv,'--ro-bind',str(inp),'/input','--ro-bind',str(code),'/code',
                '--tmpfs','/tmp','--proc','/proc','--dev','/dev','--unshare-all','--die-with-parent','--new-session',
                '--chdir','/input']
            executable=sys.executable;timeout=10
            if backend=='da3_small_v1':
                from .learned_runtime import sandbox_parts
                mounts,executable=sandbox_parts(self.learned_config);command+=mounts
                timeout=self.learned_config['timeout_s']
            command += [executable,'-B','/code/worker.py','--sha256',hashlib.sha256(data).hexdigest()]
            if time.monotonic()>=self.deadline:raise ValueError('NO_REMAINING_WORLD_BUDGET')
            (folder/'command.json').write_text(json.dumps(command,indent=2))
            job=ProcessJob(folder,command,{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
                'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HOME':'/tmp/hf','HOME':'/tmp',
                'PYTHONDONTWRITEBYTECODE':'1'},min(time.monotonic()+timeout,self.deadline))
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
        row['returned_monotonic']=time.monotonic()
        row['full_job_wall_s']=row['returned_monotonic']-row['preparation_started_monotonic']
        try:
            if result['cancel_reason'] or result['return_code']!=0:raise ValueError(result['cancel_reason'] or 'WORLD_WORKER_FAILED')
            if len(result['bytes'])>2*1024*1024:raise ValueError('WORLD_RESULT_SIZE')
            out=strict_json(result['bytes']);fields(out,('binding','state'))
            if out['binding']!=row['binding']:raise ValueError('WORLD_BINDING')
            if row['binding']['execution_epoch']!=self.epoch():raise ValueError('STALE_WORLD_EXECUTION_EPOCH')
            if row['binding']['world_revision']!=self.store.revision:raise ValueError('STALE_WORLD_REVISION')
            # A replacement worker cannot manufacture provenance or a simulator-state field.
            state_fields=('backend','observation_id','captured_monotonic','scene_healthy','entities',
                'robot_state','history_semantics','geometry_only','task_identity_verified')
            fields(out['state'],state_fields+(('surface_samples','resource_metrics') if row['backend']=='da3_small_v1' else ()))
            if out['state']['task_identity_verified'] is not False or out['state']['geometry_only'] is not True:raise ValueError('GEOMETRY_NOT_IDENTITY_AUTHORITY')
            source=self.store.get(row['binding']['observation_ids'][-1])
            if out['state']['robot_state']!=source['state'] or out['state']['observation_id']!=source['observation_id']:raise ValueError('WORLD_STATE_SOURCE')
            if out['state']['captured_monotonic']!=source['captured_monotonic'] or out['state']['backend']!=row['backend'] or type(out['state']['scene_healthy']) is not bool:raise ValueError('WORLD_METADATA')
            if row['backend']=='da3_small_v1':
                samples=out['state']['surface_samples']
                if not isinstance(samples,list) or len(samples)>1728: raise ValueError('SURFACE_SAMPLE_COUNT')
                for p in samples:
                    fields(p,('camera','pixel','point_world_m','confidence_raw','observation_id'))
                    if p['observation_id']!=source['observation_id'] or p['camera'] not in source['calibration']: raise ValueError('SURFACE_SOURCE')
                    width,height=source['calibration'][p['camera']]['resolution']
                    if len(p['point_world_m'])!=3 or len(p['pixel'])!=2 or not all(type(v) in (int,float) and math.isfinite(v) for v in p['point_world_m']+p['pixel']+[p['confidence_raw']]): raise ValueError('SURFACE_NONFINITE')
                    if not 0<=p['pixel'][0]<width or not 0<=p['pixel'][1]<height: raise ValueError('SURFACE_PIXEL')
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
            if row['backend']=='da3_small_v1':
                from .geometry_quality import assess
                out['state']['geometry_quality']=assess(out['state'],source,
                    self._images(source['observation_id']),self.public_plane)
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
