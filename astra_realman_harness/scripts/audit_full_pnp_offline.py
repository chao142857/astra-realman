#!/usr/bin/env python3
"""Read-only source/wire/cost audit and static timing figures; never launches a worker."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import jsonschema
import numpy as np
from PIL import Image
from sim_skills.async_v1 import sha
from sim_skills.full_pnp.wire import existing_infer_payload
from sim_skills.full_pnp.rgb import detect


def audit(root):
    """Inventory every attempt, including preparation failure, partial raw and cancellation.

    Audit completeness and episode success are deliberately separate claims.
    """
    from sim_skills.full_pnp.wire import strict_json,parse_actual_raw
    root=Path(root);issues=[]
    def read(path):
        try:return strict_json(path.read_text())
        except Exception as exc:
            issues.append({'file':str(path.relative_to(root)),'error':type(exc).__name__+':'+str(exc)});return None
    result=read(root/'result.json') or {};summary=result.get('episode') or {}
    events=[];timeline=root/'episode/timeline.jsonl'
    if timeline.exists():
        for i,line in enumerate(timeline.read_text().splitlines()):
            try:events.append(strict_json(line))
            except Exception as exc:issues.append({'timeline_line':i+1,'error':repr(exc)})
    observations={e['data']['observation_id']:e['data'] for e in events if e['kind']=='OBSERVATION'}
    packets={};requests=[];failure=[];visibility=[]
    for directory in sorted((root/'episode/workers').glob('request-*')):
        row={'request':directory.name,'usage_raw':None,'candidate':None,'record_errors':[],
             'files_sha256':{str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()}}
        attempt=read(directory/'attempt.json') if (directory/'attempt.json').exists() else None
        row['attempt']=attempt;row['stages']=list(attempt['stages']) if attempt else []
        wire=None;answer=None;record=None
        wire_path=directory/'input_only/wire.json'
        if wire_path.exists():
            try:
                payload=existing_infer_payload(directory/'input_only');wire=payload['context']
                if payload!=strict_json((directory/'input_payload.json').read_text()):raise ValueError('FINAL_PAYLOAD_MISMATCH')
                raw=json.dumps(wire)
                for key in ('object_pose_gt','final_object_pose','private_score','script_answers','correct_grasp_pose','correct_release_pose','sim_rm65_targets','PRIVATE_ENGINEERING_ANSWERS','contact_latch'):
                    if key in raw:raise ValueError('FORBIDDEN:'+key)
                source=observations[wire['binding']['source_observation_id']]
                source_hash=sha({'id':source['observation_id'],'state':source['state'],
                    'images':{k:hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in source['images'].items()}})
                if source_hash!=wire['binding']['source_observation_sha256']:raise ValueError('SOURCE_HASH')
                if wire['binding']['source_step']!=source['state']['sim_step']:raise ValueError('SOURCE_STEP')
                if any(e['completed_monotonic']>wire['history']['cutoff_monotonic'] for e in wire['history']['completed_transitions']):raise ValueError('FUTURE_HISTORY')
                if wire['expected_join']['status']!='PREDICTED_NOT_MEASURED':raise ValueError('PREDICTION_LABEL')
                if wire['role']=='A' and (wire['evidence_packet_hash'] not in packets or wire['evidence_packet']!=packets.get(wire['evidence_packet_hash'])):raise ValueError('E_PACKET_DEPENDENCY')
                for rec,blob in zip(wire['attachments'],payload['images']):
                    original=observations[rec['source_observation_id']];path=Path(original['images'][rec['camera']])
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=rec['source_sha256']:raise ValueError('ORIGINAL_IMAGE_HASH')
                    if rec['captured_monotonic']>source['captured_monotonic']:raise ValueError('FUTURE_IMAGE')
                    im=Image.open(path).convert('RGB')
                    if rec['representation']=='roi':im=im.crop(rec['transform']['bbox_pixels'])
                    if wire['role']=='E':im=im.resize((320,240),Image.Resampling.BILINEAR)
                    if not np.array_equal(np.asarray(im),np.asarray(Image.open(directory/'input_only'/rec['file']))):raise ValueError('DERIVED_IMAGE')
                    if hashlib.sha256(base64.b64decode(blob)).hexdigest()!=rec['sha256']:raise ValueError('WIRE_PNG')
                row['wire_status']='PASS'
            except Exception as exc:
                row['wire_status']='FAILED_OR_INCOMPLETE';row['record_errors'].append('WIRE:'+type(exc).__name__+':'+str(exc))
        else:row['wire_status']='NOT_PREPARED'
        if wire:
            row.update(role=wire['role'],source_observation_id=wire['binding']['source_observation_id'],
                       attachment_hashes=[v['sha256'] for v in wire['attachments']],
                       input_payload_sha256=row['files_sha256'].get('input_payload.json'),wire_sha256=row['files_sha256'].get('input_only/wire.json'))
        raw_path=directory/'worker.json'
        if raw_path.exists():
            row['raw_bytes']=raw_path.stat().st_size
            try:
                record=strict_json(raw_path.read_bytes())
                if isinstance(record,dict):row['usage_raw']=record.get('usage')
                if not wire:raise ValueError('NO_WIRE_FOR_RAW_VALIDATION')
                answer=parse_actual_raw(json.dumps(record['candidate'],allow_nan=False),wire)
                row['candidate']=answer;row['parse_status']='PASS'
                if wire['role']=='E' and (not attempt or attempt['status']=='READY'):packets[sha(answer)]=answer
            except Exception as exc:
                row['parse_status']='FAILED';row['record_errors'].append('RAW:'+type(exc).__name__+':'+str(exc))
        else:row['parse_status']='NO_OUTPUT'
        if attempt:
            row['status']=attempt['status']
            if row['usage_raw'] is None:row['usage_raw']=attempt.get('usage_raw')
        else:row['status']='LEGACY_OR_INCOMPLETE'
        index=int(directory.name.split('-')[-1]);digest=row.get('wire_sha256')
        for e in events:
            d=e['data']
            if (d.get('request')==index and e['kind'] in ('REQUEST_START','REQUEST_END','REQUEST_CANCELLED')) or (digest and d.get('candidate_id')==digest):
                row['stages'].append({'stage':e['kind'],'monotonic':e['wall_monotonic'],'data':d})
        row['stages'].sort(key=lambda x:x['monotonic'])
        row['phase_duration_s']={}
        phases={'preparation':('PREPARING',('PREPARED','FAILED')),'launch':('LAUNCHING',('STARTED','FAILED')),
                'await_return':('STARTED',('RETURNED','CANCELLED')),'parse':('PARSING',('PARSED','PARSE_FAILED')),
                'submit':('CANDIDATE_SUBMIT_BEGIN',('CANDIDATE_ADOPTED','CANDIDATE_DISCARDED'))}
        for name,(begin,ends) in phases.items():
            start=next((v['monotonic'] for v in row['stages'] if v['stage']==begin),None)
            end=next((v['monotonic'] for v in row['stages'] if v['stage'] in ends and start is not None and v['monotonic']>=start),None)
            row['phase_duration_s'][name]=end-start if end is not None else None
        requests.append(row)
    active=set();max_active=0
    for e in events:
        d=e['data']
        if e['kind']=='REQUEST_START':
            if active:failure.append('CONCURRENT_WORKER')
            active.add(d['request']);max_active=max(max_active,len(active))
        elif e['kind'] in ('REQUEST_END','REQUEST_CANCELLED'):active.discard(d['request'])
    if active:issues.append({'unfinished_requests':sorted(active)})
    if summary and summary.get('candidate_generated',0)!=summary.get('candidate_adopted',0)+summary.get('candidate_discarded',0):failure.append('CANDIDATE_ACCOUNTING')
    for observation in observations.values():
        for camera,path in observation['images'].items():
            try:
                f=detect(path);visibility.append({'observation':observation['observation_id'],'camera':camera,'reason':observation['reason'],'object':f['object'],'goal':f['goal']})
            except Exception as exc:issues.append({'image':path,'error':repr(exc)})
    out={'status':'COMPLETE_WITH_FAILURES' if failure or issues or result.get('status')!='PASS' or any(r['record_errors'] for r in requests) else 'PASS',
         'audit_complete':True,'episode_status':result.get('status','UNKNOWN'),'source':'OFFLINE_AUDIT_NOT_MODEL_ACCEPTANCE',
         'failure':failure,'artifact_issues':issues,'condition':result.get('condition','UNKNOWN'),'commit':result.get('git_commit'),
         'requests':requests,'max_in_flight_reconstructed':max_active,'visibility_rgb_only':visibility,
         'real_model_calls':result.get('real_model_calls',0),'hardware_calls':result.get('hardware_calls',0)}
    try:
        if events:plot(root,events,dict(condition=out['condition'],wall_s=max(e['wall_elapsed_s'] for e in events),adopted_inference_execution_overlap_s=summary.get('adopted_inference_execution_overlap_s',0)))
    except Exception as exc:out['artifact_issues'].append({'plot_error':repr(exc)});out['status']='COMPLETE_WITH_FAILURES'
    (root/'wire_audit.json').write_text(json.dumps(out,indent=2)+'\n')
    return out


def plot(root,events,summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(13,6),gridspec_kw={'height_ratios':[3,1]},layout='constrained')
    ax=axes[0];started=events[0]['wall_monotonic'];opened={}
    lanes={'EXEC':0,'GRIPPER':0,'HOLD':1,'REQUEST_B':2,'REQUEST_E':2,'REQUEST_A':3}
    colors={'EXEC':'#218c52','GRIPPER':'#cc7430','HOLD':'#909aa2','REQUEST_B':'#3e74bd','REQUEST_E':'#8356aa','REQUEST_A':'#3e74bd'}
    for e in events:
        k=e['kind'];t=e['wall_monotonic']-started;d=e['data']
        if k in ('PHYSICAL_EXEC_ENTER','PHYSICAL_GRIPPER_ENTER'):opened[k.split('_')[1]]=t
        elif k in ('PHYSICAL_EXEC_EXIT','PHYSICAL_GRIPPER_EXIT'):
            typ=k.split('_')[1];lo=opened.pop(typ,None)
            if lo is not None:ax.broken_barh([(lo,t-lo)],(lanes[typ]-.3,.6),facecolors=colors[typ])
        elif k=='HOLD_BEGIN':opened['HOLD']=t
        elif k=='HOLD_END':
            lo=opened.pop('HOLD',t);ax.broken_barh([(lo,t-lo)],(.7,.6),facecolors=colors['HOLD'])
        elif k=='REQUEST_START':opened['role']=d['role']
        elif k=='REQUEST_END' and d.get('record') and all(key in d['record'] for key in ('worker_started_monotonic','worker_finished_monotonic')):
            typ='REQUEST_'+opened['role'];r=d['record'];lo=r['worker_started_monotonic']-started;hi=r['worker_finished_monotonic']-started
            ax.broken_barh([(lo,hi-lo)],(lanes[typ]-.3,.6),facecolors=colors[typ])
        elif k in ('CANDIDATE_GENERATED','CANDIDATE_ADOPTED','CANDIDATE_DISCARDED'):
            ax.scatter(t,4,marker={'CANDIDATE_GENERATED':'o','CANDIDATE_ADOPTED':'v','CANDIDATE_DISCARDED':'x'}[k],s=25,color='black')
    ax.set_yticks(range(5),['Motion / gripper','Wait drives retained','B or E stub compute','A stub compute','Ready o / adopted v'])
    ax.set_title(f"{summary['condition']} offline only | wall {summary['wall_s']:.3f}s | adopted overlap {summary['adopted_inference_execution_overlap_s']:.3f}s")
    ax.grid(axis='x',alpha=.2);ax.set_xlim(0,summary['wall_s'])
    axes[1].plot([e['wall_monotonic']-started for e in events],[e['physics_elapsed_s'] for e in events],color='#218c52')
    axes[1].set(xlabel='Episode wall time (s); initialization excluded',ylabel='Physics time (s)',xlim=(0,summary['wall_s']))
    axes[1].grid(alpha=.2);fig.savefig(root/'timeline.png',dpi=160);fig.savefig(root/'timeline.svg');plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('episode',type=Path);a=p.parse_args()
    report=audit(a.episode);print(json.dumps({k:report[k] for k in ('status','condition','failure','max_in_flight_reconstructed')}))
    raise SystemExit(0 if report['audit_complete'] else 1)
