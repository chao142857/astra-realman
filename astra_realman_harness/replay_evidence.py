"""Read-only, same-step evidence pairing. Post-hoc markers never enter model contexts."""
import copy
import hashlib
import io
import json
import math
import re
import struct
import time
import uuid
import zipfile
from pathlib import Path
from io_utils import ROOT, read_json, write_json

MARKERS=('first_approach_basket','first_release_attempt','first_clear_deviation')


def optional(path):
    return read_json(path) if path.is_file() else {}


def image_record(camera, observation_id=None):
    result={k:camera.get(k) for k in ('serial','role','captured_at','sha256','image_path')}
    result.update(observation_id=observation_id,available=False,errors=[],expected_hash=camera.get('sha256'),actual_hash=None,integrity_status='invalid')
    try:
        path=Path(camera['image_path']).resolve()
        if not path.is_relative_to((ROOT/'logs').resolve()) or not 0<path.stat().st_size<=8*1024*1024:
            raise ValueError('IMAGE_PATH_OR_SIZE')
        data=path.read_bytes()
        result['actual_hash']=hashlib.sha256(data).hexdigest()
        if result['actual_hash']!=camera.get('sha256'):result['errors'].append('IMAGE_HASH')
        if len(data)<24 or data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG_HEADER')
        w,h=struct.unpack('>II',data[16:24])
        if not w or not h:raise ValueError('IMAGE_DIMENSIONS')
        result.update(width=w,height=h)
        shape=camera.get('shape')
        if shape is not None and (not isinstance(shape,list) or shape[:2]!=[h,w]):raise ValueError('IMAGE_SHAPE_MISMATCH')
        if ('width' in camera or 'height' in camera) and (camera.get('width'),camera.get('height'))!=(w,h):
            raise ValueError('CONFIG_DIMENSIONS_DIFFER_FROM_PNG')
        if type(camera.get('captured_at')) not in (float,int) or not math.isfinite(camera['captured_at']):raise ValueError('IMAGE_TIMESTAMP_MISSING')
        result['available']=not result['errors']
        result['integrity_status']='valid' if result['available'] else 'invalid'
    except (KeyError,ValueError,OSError,TypeError) as exc:result['errors'].append(str(exc))
    return result


def step_folder(run,name):
    if not re.fullmatch(r'step-\d+',name):raise ValueError('STEP_NAME')
    path=(run/name).resolve()
    if path.parent!=run.resolve() or not path.is_dir():raise ValueError('STEP_PATH')
    return path


def replay(run,name):
    step=step_folder(run,name)
    decision=optional(step/'input_observation.json') or optional(step/'input/observation.json')
    before=optional(step/'pre-execution/observation.json')
    after=optional(step/'next_observation.json') or optional(step/'after/observation.json')
    transition=optional(step/'transition.json')
    warnings=[]
    if not before:warnings.append('MISSING_DISPATCH_BEFORE: 未记录执行前图；决策图单独展示，不能替代。')
    if not after:warnings.append('MISSING_AFTER: 未记录本步动作后图。')
    if not transition:warnings.append('MISSING_TRANSITION: 仅展示原始日志，不补造 transition。')
    groups={}
    for stage,obs in [('decision',decision),('before',before),('after',after)]:
        groups[stage]=[]
        seen=set()
        for c in obs.get('cameras',[]):
            item=image_record(c,obs.get('observation_id'));key=(item['serial'],item['role'])
            if key in seen:item['errors'].append('DUPLICATE_CAMERA_IDENTITY');item['available']=False
            seen.add(key);groups[stage].append(item)
        if obs and not obs.get('observation_id'):
            warnings.append(stage+': OBSERVATION_ID_MISSING')
            for item in groups[stage]:item['available']=False;item['errors'].append('OBSERVATION_ID_MISSING')
    if transition:
        for stage in ('decision','after'):
            obs={'decision':decision,'after':after}[stage]
            if obs and transition.get(stage+'_observation_id')!=obs.get('observation_id'):
                warnings.append(stage+': TRANSITION_OBSERVATION_MISMATCH')
                for item in groups[stage]:item['available']=False;item['errors'].append('TRANSITION_OBSERVATION_MISMATCH')
            refs=transition.get('camera_references',{}).get(stage,[])
            for item in groups[stage]:
                matches=[c for c in refs if (c.get('serial'),c.get('role'))==(item['serial'],item['role'])]
                if len(matches)!=1 or any(matches[0].get(k)!=item.get(k) for k in ('sha256','captured_at')):
                    item['available']=False;item['errors'].append('TRANSITION_IMAGE_REFERENCE_MISMATCH')
        stamps=transition.get('timestamps',{})
        if before and before.get('captured_at')!=stamps.get('dispatch_before'):
            warnings.append('BEFORE_TIMESTAMP_MISMATCH')
            for item in groups['before']:item['available']=False;item['errors'].append('BEFORE_TIMESTAMP_MISMATCH')
        if transition.get('step')!=int(name.split('-')[1]) or transition.get('episode_id')!=decision.get('episode_id',run.name):
            warnings.append('TRANSITION_EPISODE_OR_STEP_MISMATCH')
            for items in groups.values():
                for item in items:item['available']=False;item['errors'].append('TRANSITION_EPISODE_OR_STEP_MISMATCH')
    for items in groups.values():
        for item in items:item['integrity_status']='valid' if item['available'] else 'invalid'
    identities=list(dict.fromkeys((c['serial'],c['role']) for items in groups.values() for c in items))
    pairs=[{'serial':serial,'role':role,**{stage:next((c for c in items if (c['serial'],c['role'])==(serial,role)),None) for stage,items in groups.items()}} for serial,role in identities]
    execution=optional(step/'group_result.json') or optional(step/'execution_result.json');check=optional(step/'group_preflight.json') or optional(step/'feasibility.json')
    factual={'transition':transition,'execution':execution,'feasibility':check,
             'proposal':optional(step/'parsed_group.json') or optional(step/'parsed_action.json'),'diagnostics_hypotheses':optional(step/'diagnostics.json')}
    if (step/'parsed_group.json').exists():
        from parallel_gui_evidence import group_evidence
        factual['arms']=group_evidence(step)['arms']
    events=[read_json(p) for p in sorted(run.glob('review-marker-*.json')) if read_json(p).get('step')==name]
    result={'run':run.name,'step':name,'pairs':pairs,'warnings':warnings,'facts':factual,'markers':events,
            'synthetic':(run/'SYNTHETIC.json').exists(),'readonly':True,
            'note':'图像变化是观察；模型诊断是待验证判断。画面右侧不代表 work +X，未推断因果。'}

    request=_request_image_evidence(run,name,result)
    if request['source']=='recorded_request_attachments':
        for pair in pairs:
            item=pair['decision']
            if item is None:continue
            matches=[c for c in request['images'] if (c['serial'],c['role'])==(item['serial'],item['role'])]
            if len(matches)!=1:item['errors'].append('REQUEST_IMAGE_REFERENCE_MISSING_OR_AMBIGUOUS')
            else:item['errors']=list(dict.fromkeys(item['errors']+matches[0]['errors']))
            item['available']=not item['errors'];item['integrity_status']='valid' if item['available'] else 'invalid'
    return result


def request_image_evidence(run,name):
    return _request_image_evidence(run,name,replay(run,name))


def _request_image_evidence(run,name,view):
    step=step_folder(run,name)
    obs=optional(step/'input_observation.json') or optional(step/'input/observation.json')
    decision=[p['decision'] for p in view['pairs'] if p['decision']]
    path=step/'decision/attachments.json'
    attachments=read_json(path) if path.is_file() else optional(step/'model_input.json').get('images_in_attachment_order')
    source='recorded_request_attachments' if attachments is not None else 'observation_only_request_unconfirmed'
    if attachments is None:attachments=obs.get('cameras',[])
    if not isinstance(attachments,list):raise ValueError('ATTACHMENTS_LIST_REQUIRED')
    result=[]
    for attachment in attachments:
        matches=[c for c in obs.get('cameras',[]) if (c.get('serial'),c.get('role'))==(attachment.get('serial'),attachment.get('role'))]
        reference=matches[0] if len(matches)==1 else {}
        item=image_record(dict(reference,**attachment),obs.get('observation_id'))
        qualified=[c for c in decision if (c['serial'],c['role'])==(attachment.get('serial'),attachment.get('role'))]
        if len(matches)!=1 or len(qualified)!=1:
            item['errors'].append('REQUEST_IMAGE_REFERENCE_MISSING_OR_AMBIGUOUS')
        else:
            for key in ('image_path','captured_at','sha256','observation_id'):
                expected=obs.get('observation_id') if key=='observation_id' else reference.get(key)
                if key in attachment and attachment[key]!=expected:item['errors'].append('REQUEST_IMAGE_REFERENCE_MISMATCH:'+key)
            item['errors'].extend(qualified[0]['errors'])
        item['errors']=list(dict.fromkeys(item['errors']))
        item['available']=not item['errors'];item['integrity_status']='valid' if item['available'] else 'invalid'
        result.append(item)
    return {'source':source,'images':result}


def mark(run,body):
    step_folder(run,body['step'])
    if body.get('kind') not in MARKERS:raise ValueError('MARKER_KIND')
    if not all(isinstance(body.get(k),str) and 0<len(body[k].strip())<=2000 for k in ('observer','evidence')):
        raise ValueError('MARKER_OBSERVER_AND_EVIDENCE_REQUIRED')
    value={k:body[k] for k in ('step','kind','observer','evidence')}
    value.update(recorded_at=time.time(),post_hoc=True,model_input=False,run=run.name,episode_id=optional(run/'summary.json').get('episode_id',run.name))
    write_json(run/('review-marker-'+uuid.uuid4().hex+'.json'),value)
    return value


def evidence_zip(run,name=None):
    """Portable allowlisted bundle. Images are content addressed, JSON paths rewritten."""
    run=run.resolve()
    if not run.is_relative_to((ROOT/'logs').resolve()):raise ValueError('EXPORT_OUTSIDE_LOGS')
    data=replay(run,name) if name else dict(read_json(run/'controls_manifest.json'),warnings=[])
    step=step_folder(run,name) if name else run
    files={};missing=[]
    secrets=[]
    token=ROOT/'config/codex_astra_bridge.token'
    if token.is_file():secrets=[token.read_text().strip()]
    def clean_text(value):
        from decision_backends import redact
        value=redact(value)
        for secret in secrets:
            if secret:value=value.replace(secret,'[REDACTED]')
        value=re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_.-]+',r'\1[REDACTED]',value)
        return value
    def scrub(value,key=''):
        from evidence_redaction import sensitive_key,statistic,STATS,STAT_OBJECTS
        if sensitive_key(key):return '[REDACTED]'
        if key in STATS|STAT_OBJECTS:return statistic(key,value)
        if isinstance(value,dict):return {k:scrub(v,k) for k,v in value.items()}
        if isinstance(value,list):return [scrub(v,key) for v in value]
        if not isinstance(value,str):return value
        if key=='image_path':
            p=Path(value).resolve()
            if p.is_relative_to((ROOT/'logs').resolve()) and p.is_file() and p.stat().st_size<=8*1024*1024:
                raw=p.read_bytes();dest='images/'+hashlib.sha256(raw).hexdigest()+'.png';files[dest]=raw;return dest
            missing.append(value);return 'MISSING_IMAGE'
        value=clean_text(value)
        if value.startswith(str(ROOT)):
            p=Path(value)
            if p.is_relative_to(run):return str(p.relative_to(run))
            return '[EXTERNAL_LOCAL_PATH]/'+p.name
        return value.replace(str(ROOT),'[HARNESS_ROOT]')
    allowed=['summary.json','history_profile.json','gui_launch.json','launch_manifest.json','independent_observation.json','SYNTHETIC.json','source_manifest.json','config.json','action_schema.json','camera_streams.json','failure.json']
    sources=[(run/n,n) for n in allowed]+[(p,p.name) for p in run.glob('review-marker-*.json')]
    stepnames=['input_observation.json','input/observation.json','pre-execution/observation.json','after/observation.json','next_observation.json','transition.json','model_input.json','parsed_action.json','planned_commands.json','executed_action.json','execution_result.json','feasibility.json','diagnostics.json','timing.json','decision/attachments.json','decision/backend_result.json','decision/prompt.txt','decision/astra_raw.txt','raw_proposal.txt','safety.json','input_validation.json','after_validation.json','after_state.json','sdk_result.json','pose-telemetry.json','failure.json']
    if name:sources += [(step/n,name+'/'+n) for n in stepnames]
    else:
        allowed_names={'controls_manifest.json','human_verification.json','replay_manifest.json','final_transitions.json','model_input.json','attachments.json','backend_result.json','prompt.txt','astra_raw.txt','raw_proposal.txt','parsed_action.json','diagnostics.json'}
        sources=[(p,str(p.relative_to(run))) for p in run.rglob('*') if p.is_file() and p.name in allowed_names and p.resolve().is_relative_to(run)]
    for path,dest in sources:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(run):continue
        if path.suffix=='.json':value=scrub(read_json(path));raw=json.dumps(value,ensure_ascii=False,indent=2).encode()
        elif path.name=='prompt.txt':
            try:raw=json.dumps(scrub(json.loads(path.read_text())),ensure_ascii=False,indent=2).encode()
            except ValueError:raw=clean_text(path.read_text()).replace(str(ROOT),'[HARNESS_ROOT]').encode()
        else:raw=clean_text(path.read_text()).replace(str(ROOT),'[HARNESS_ROOT]').encode()
        files[dest]=raw
    files['replay.json']=json.dumps(scrub(data),ensure_ascii=False,indent=2).encode()
    manifest={'version':1,'run':run.name,'step':name,'synthetic':data['synthetic'],'missing_images':[Path(p).name for p in missing],
              'warnings':data['warnings'],'files':{n:{'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} for n,v in files.items()},
              'path_base':'archive root; all image_path values are relative to archive root','post_hoc_never_model_input':True}
    files['manifest.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for n,v in files.items():z.writestr(n,v)
    return out.getvalue()
