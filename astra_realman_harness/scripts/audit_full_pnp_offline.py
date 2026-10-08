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
    result=json.loads((root/'result.json').read_text());summary=result['episode']
    events=[json.loads(line) for line in (root/'episode/timeline.jsonl').read_text().splitlines()]
    observations={e['data']['observation_id']:e['data'] for e in events if e['kind']=='OBSERVATION'}
    packets={};requests=[];failure=[];visibility=[]
    def require(ok,reason):
        if not ok:failure.append(reason)
    for directory in sorted((root/'episode/workers').glob('request-*')):
        payload=existing_infer_payload(directory/'input_only');w=payload['context']
        stored=json.loads((directory/'input_payload.json').read_text())
        require(payload==stored,directory.name+':FINAL_PAYLOAD_MISMATCH')
        record=json.loads((directory/'worker.json').read_text());answer=record['candidate']
        jsonschema.validate(answer,payload['schema'])
        raw=json.dumps(w)
        for key in ('object_pose_gt','final_object_pose','private_score','script_answers','correct_grasp_pose','correct_release_pose','sim_rm65_targets','PRIVATE_ENGINEERING_ANSWERS','contact_latch'):
            require(key not in raw,directory.name+':FORBIDDEN:'+key)
        source=observations[w['binding']['source_observation_id']]
        source_hash=sha({'id':source['observation_id'],'state':source['state'],
                         'images':{k:hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in source['images'].items()}})
        require(source_hash==w['binding']['source_observation_sha256'],directory.name+':SOURCE_HASH')
        require(w['binding']['source_step']==source['state']['sim_step'],directory.name+':SOURCE_STEP')
        require(all(e['completed_monotonic']<=w['history']['cutoff_monotonic'] for e in w['history']['completed_transitions']),directory.name+':FUTURE_HISTORY')
        require(w['expected_join']['status']=='PREDICTED_NOT_MEASURED',directory.name+':PREDICTION_LABEL')
        require(record['model_calls']==0 and record['usage'] is None,directory.name+':STUB_LABEL')
        if w['role']=='E':packets[sha(answer)]=answer
        if w['role']=='A':
            require(w['evidence_packet_hash'] in packets,directory.name+':E_DEPENDENCY')
            require(w['evidence_packet']==packets.get(w['evidence_packet_hash']),directory.name+':E_PACKET_MUTATED')
        for rec,blob in zip(w['attachments'],payload['images']):
            original=observations[rec['source_observation_id']]
            data=Path(original['images'][rec['camera']]).read_bytes()
            require(hashlib.sha256(data).hexdigest()==rec['source_sha256'],directory.name+':ORIGINAL_IMAGE_HASH')
            require(rec['captured_monotonic']<=source['captured_monotonic'],directory.name+':FUTURE_IMAGE')
            original_image=Image.open(original['images'][rec['camera']]).convert('RGB')
            transform=rec['transform']
            if rec['representation']=='roi':original_image=original_image.crop(transform['bbox_pixels'])
            if w['role']=='E':original_image=original_image.resize((320,240),Image.Resampling.BILINEAR)
            require(np.array_equal(np.asarray(original_image),np.asarray(Image.open(directory/'input_only'/rec['file']))),directory.name+':DERIVED_IMAGE')
            require(hashlib.sha256(base64.b64decode(blob)).hexdigest()==rec['sha256'],directory.name+':WIRE_PNG')
        requests.append({'request':directory.name,'role':w['role'],'source_observation_id':w['binding']['source_observation_id'],
            'input_payload_sha256':hashlib.sha256((directory/'input_payload.json').read_bytes()).hexdigest(),
            'wire_sha256':hashlib.sha256((directory/'input_only/wire.json').read_bytes()).hexdigest(),
            'attachment_hashes':[v['sha256'] for v in w['attachments']],
            'attachment_bytes':sum((directory/'input_only'/v['file']).stat().st_size for v in w['attachments']),
            'context_utf8_bytes':len(json.dumps(w,ensure_ascii=False).encode()),
            'usage_raw':record['usage'],'worker_compute_s':record['worker_finished_monotonic']-record['worker_started_monotonic'],
            'history_events':len(w['history']['completed_transitions']),'hypothesis_items':len(w['history']['visual_hypotheses'])})
    open_request=None;max_active=0
    for e in events:
        if e['kind']=='REQUEST_START':
            require(open_request is None,'CONCURRENT_WORKER');open_request=e['data'];max_active=1
        if e['kind'] in ('REQUEST_END','REQUEST_CANCELLED'):
            require(open_request is not None,'END_WITHOUT_START')
            if open_request:
                r=next(x for x in requests if x['request']=='request-%03d'%open_request['request'])
                r.update(latency_s=e['data']['latency_s'],preparation_s=open_request['preparation_s'])
            open_request=None
    require(open_request is None,'UNACCOUNTED_WORKER')
    require(summary['candidate_generated']==summary['candidate_adopted']+summary['candidate_discarded'],'CANDIDATE_ACCOUNTING')
    for observation in observations.values():
        for camera,path in observation['images'].items():
            f=detect(path)
            visibility.append({'observation':observation['observation_id'],'camera':camera,'reason':observation['reason'],
                               'object':f['object'],'goal':f['goal']})
    out={'status':'PASS' if not failure else 'FAIL','source':'OFFLINE_WIRE_AUDIT_NOT_MODEL_ACCEPTANCE',
         'failure':failure,'condition':summary['condition'],'commit':result['git_commit'],'git_status':result['git_status'],
         'requests':requests,'max_in_flight_reconstructed':max_active,'visibility_rgb_only':visibility,
         'all_worker_usage_raw':None,'real_model_calls':0,'hardware_calls':0}
    (root/'wire_audit.json').write_text(json.dumps(out,indent=2)+'\n')
    plot(root,events,summary)
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
        elif k=='REQUEST_END' and d.get('record'):
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
    raise SystemExit(0 if report['status']=='PASS' else 1)
