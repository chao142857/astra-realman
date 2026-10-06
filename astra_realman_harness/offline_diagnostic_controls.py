"""Isolated fixed-observation controls. No executor, action repair, rollout, or retries."""
import copy
import json
import math
import threading
from pathlib import Path
from io_utils import ROOT, read_json, write_json, new_run
from scripts.prepare_history_replay import prepare, decision_observation, ready_time
from history_diagnostics import schema_path, decode
from replay_evidence import image_record


def annotation_template(obs):
    return {'observation_id':obs['observation_id'],'observer':'',
            'visual_positions':[],
            'task_state':{'holding':'unknown','evidence_camera_serials':[]},
            'reference_images':[{k:image_record(c,obs['observation_id']).get(k) for k in ('serial','role','sha256','width','height','captured_at')} for c in obs['cameras']]}


def verified_facts(obs,annotation):
    allowed={'observation_id','observer','visual_positions','task_state','reference_images'}
    if set(annotation)!=allowed or annotation['observation_id']!=obs['observation_id']:
        raise ValueError('ANNOTATION_FIELDS_OR_OBSERVATION')
    if not isinstance(annotation['observer'],str) or not 0<len(annotation['observer'].strip())<=128:raise ValueError('OBSERVER_REQUIRED')
    if any(not image_record(c,obs['observation_id'])['available'] or c['captured_at']>ready_time(obs) for c in obs['cameras']):raise ValueError('CURRENT_IMAGE_INVALID_OR_FUTURE')
    refs=annotation_template(obs)['reference_images']
    if annotation['reference_images']!=refs:raise ValueError('ANNOTATION_IMAGE_REFERENCE_MISMATCH')
    byserial={c['serial']:c for c in refs}
    positions=annotation['visual_positions']
    if not isinstance(positions,list) or len(positions)>20:raise ValueError('VISUAL_POSITIONS')
    clean=[]
    for p in positions:
        if set(p)!={'object','camera_serial','coordinate_system','xy','source'}:raise ValueError('POSITION_FIELDS')
        if p['object'] not in ('ball','gripper','basket'):raise ValueError('POSITION_OBJECT')
        if p['source']!='human_verified_current_image':raise ValueError('POSITION_SOURCE')
        ref=byserial.get(p['camera_serial'])
        if not ref or not ref.get('width'):raise ValueError('POSITION_CAMERA')
        xy=p['xy']
        if not isinstance(xy,list) or len(xy)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in xy):raise ValueError('POSITION_XY')
        if p['coordinate_system']=='pixels_top_left_x_right_y_down':
            if not (0<=xy[0]<ref['width'] and 0<=xy[1]<ref['height']):raise ValueError('PIXEL_OUT_OF_RANGE')
            pixels=xy
        elif p['coordinate_system']=='normalized_0_1000_top_left_x_right_y_down':
            if any(not 0<=v<=1000 for v in xy):raise ValueError('NORMALIZED_OUT_OF_RANGE')
            pixels=[xy[0]*(ref['width']-1)/1000,xy[1]*(ref['height']-1)/1000]
        else:raise ValueError('POSITION_COORDINATE_SYSTEM')
        clean.append(dict(p,image_reference=ref,pixels_xy=pixels,conversion='normalized x*(width-1)/1000, y*(height-1)/1000; pixels unchanged'))
    state=annotation['task_state']
    if not isinstance(state,dict) or set(state)!={'holding','evidence_camera_serials'} or state['holding'] not in ('holding','not_holding','unknown'):
        raise ValueError('CURRENT_TASK_STATE_ONLY')
    serials=state['evidence_camera_serials']
    if not isinstance(serials,list) or any(s not in byserial for s in serials) or (state['holding']!='unknown' and not serials):raise ValueError('STATE_CURRENT_IMAGE_EVIDENCE_REQUIRED')
    return {'observer':annotation['observer'],'observation_id':obs['observation_id'],'visual_positions':clean,
            'task_state':dict(state,image_references=[byserial[s] for s in serials])}


def visual_history(context,run,step_number,obs,role):
    if role not in ('tabletop','overhead'):raise ValueError('FIXED_CAMERA_ROLE')
    result=copy.deepcopy(context)
    meta={'base_profile':None,'visual_history_mode':'previous_fixed_before','fixed_camera_role':role,
          'status':'MISSING_FIRST_STEP' if step_number==1 else 'MISSING_PREVIOUS_BEFORE','attachment_count':3}
    if step_number>1:
        previous=run/('step-%02d'%(step_number-1));before_path=previous/'pre-execution/observation.json';transition_path=previous/'transition.json'
        if before_path.is_file() and transition_path.is_file():
            before=read_json(before_path);t=read_json(transition_path)
            if (t.get('step')!=step_number-1 or t.get('episode_id')!=context['episode_id']
                or t['timestamps']['completed_at']>ready_time(obs) or t['timestamps']['after'] is None
                or t['timestamps']['after']>obs['captured_at'] or before.get('captured_at')!=t['timestamps']['dispatch_before']
                or before['captured_at']>t['timestamps']['after']):raise ValueError('HISTORY_FUTURE_OR_TRANSITION_MISMATCH')
            current=next(c for c in obs['cameras'] if c['role']==role)
            matches=[c for c in before.get('cameras',[]) if (c.get('serial'),c.get('role'))==(current['serial'],role)]
            if len(matches)!=1:raise ValueError('HISTORY_FIXED_CAMERA_IDENTITY')
            camera=matches[0];record=image_record(camera,before.get('observation_id'))
            if not record['available'] or camera['captured_at']>obs['captured_at'] or camera['captured_at']>t['timestamps']['completed_at']:
                raise ValueError('HISTORY_IMAGE_INTEGRITY_OR_FUTURE')
            if before.get('observation_id') in (obs['observation_id'],t.get('after_observation_id')):raise ValueError('HISTORY_IS_CURRENT_OR_AFTER')
            image={k:camera.get(k) for k in ('serial','role','role_confirmed','image_path','captured_at')}
            image.update(input_index=4,temporal_role='previous_action_before',observation_id=before['observation_id'],sha256=camera['sha256'])
            result['images_in_attachment_order'].append(image)
            meta.update(status='AVAILABLE',attachment_count=4,source_step=step_number-1,source_observation_id=before['observation_id'],source_transition=str(transition_path),source_image=record)
    result['visual_history_experiment']=meta
    result['evidence_rules']=result['evidence_rules'].replace('Only the three current images are attached; historical camera references are identifiers, not supplied images. Do not claim to have seen earlier images.', 'The first three attached images are current. Other historical references remain identifiers except the explicitly attached fourth historical image.')
    result['evidence_rules'] += ' Independent visual-history condition: attachments 1–3 remain current views; attachment 4, when present, is explicitly past fixed-camera evidence before the previous completed action, never the current state. Missing history is not fabricated.'
    return result


def prepare_controls(run,step_number,output,*,base_profile='H5D1',annotation=None,visual_history_mode='none',fixed_camera='tabletop',infer=False):
    if visual_history_mode not in ('none','previous_fixed_before'):raise ValueError('VISUAL_HISTORY_MODE')
    if visual_history_mode!='none' and annotation is not None:raise ValueError('KEEP_CONTROLS_INDEPENDENT')
    obs=decision_observation(run/('step-%02d'%step_number))
    facts=verified_facts(obs,annotation) if annotation is not None else None
    new_run(output)
    # Reuse the same strict fixed-prefix replay builder and original validators unchanged.
    prepare(run,step_number,output/'baseline',profiles=[base_profile])
    original=read_json(output/'baseline'/base_profile/'model_input.json')
    variants={'original':copy.deepcopy(original)}
    if facts:
        variants['verified_visual_positions']=dict(copy.deepcopy(original),verified_current_visual_positions={k:facts[k] for k in ('observer','observation_id','visual_positions')})
        variants['verified_current_task_state']=dict(copy.deepcopy(original),verified_current_task_state={k:facts[k] for k in ('observer','observation_id','task_state')})
        write_json(output/'human_verification.json',annotation)
    if visual_history_mode!='none':
        variants={'three_current_plus_previous_fixed':visual_history(original,run,step_number,obs,fixed_camera)}
        variants['three_current_plus_previous_fixed']['visual_history_experiment']['base_profile']=base_profile
    manifest={'base_profile':base_profile,'visual_history_mode':visual_history_mode,'decision_step':step_number,'observation_id':obs['observation_id'],
              'variants':list(variants),'model_calls':0,'executor_present':False,'rollout':False,'synthetic':obs.get('source','').startswith('SYNTHETIC'),
              'annotation_policy':'current-image facts only; post-hoc failure markers and final outcomes never included'}
    if visual_history_mode!='none':manifest['visual_history']=variants['three_current_plus_previous_fixed']['visual_history_experiment']
    for name,context in variants.items():
        folder=new_run(output/name);write_json(folder/'model_input.json',context);decision=new_run(folder/'decision')
        if infer:
            from left_terminal import call_astra
            schema=schema_path(base_profile)
            raw=call_astra(context,decision,read_json(ROOT/'config/decision_backend.json'),'gpt-6-astra',threading.Event(),lambda *v:print(*v,flush=True),schema_path=schema,decoder=lambda raw:decode(raw,base_profile)[1])
            (folder/'raw_proposal.txt').write_text(raw);diag,action=decode(raw,base_profile)
            write_json(folder/'parsed_action.json',action)
            if diag:write_json(folder/'diagnostics.json',diag)
            manifest['model_calls']+=1
        else:
            (decision/'prompt.txt').write_text(json.dumps(context,ensure_ascii=False,allow_nan=False))
            write_json(decision/'attachments.json',context['images_in_attachment_order'])
            write_json(decision/'backend_result.json',{'backend':'PREPARED_ONLY_NO_MODEL','model_calls':0})
    write_json(output/'controls_manifest.json',manifest)
    from replay_evidence import evidence_zip
    (output/'prepared-evidence.zip').write_bytes(evidence_zip(output))
    return dict(manifest,evidence_zip=str(output/'prepared-evidence.zip'))
