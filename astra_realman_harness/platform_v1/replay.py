"""Read-only conversion of existing full-task evidence into the public v1 stream."""
import copy,hashlib,json,re
from pathlib import Path
from engineering.public_view import observation,execution,error_code
from platform_v1.client import VERSION

def build(run,output,source='ENGINEERING_REFERENCE'):
    run=Path(run);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    timeline=run/'episode/timeline.jsonl';events=[];camera_poses=[];image_quality=[]
    def add(e,kind,data):
        events.append({'version':VERSION,'sequence':len(events)+1,'episode_id':'archive:'+run.name,
          'kind':kind,'source':source,'monotonic':e['wall_monotonic'],'physics_step':e['physics_step'],'data':data})
    for line in timeline.read_text().splitlines():
        e=json.loads(line);d=e['data']
        if e['kind']=='OBSERVATION':
            raw=copy.deepcopy(d)
            for camera,path in raw['images'].items():
                old=Path(path)
                if old.name!=camera+'.png' or not re.fullmatch(r'obs_\d+',old.parent.name):raise ValueError('ARCHIVE_PATH')
                raw['images'][camera]=str(run/'scene'/old.parent.name/old.name)
            folder='o-%04d'%len(camera_poses);out=observation(raw,output/folder)
            for im in out['rgb']:im['file']=folder+'/'+im['file']
            out.update(version=VERSION,episode_id='archive:'+run.name,source=source);add(e,'observation',out)
            camera_poses.append(out['calibration']['wrist']['pose_world_xyz_wxyz'])
            from sim_skills.full_pnp.rgb import features
            f=features(raw)
            image_quality.append({'observation_id':raw['observation_id'],'RGB_component_evidence':f,
                 'meaning':'measured color visibility/ambiguity only, not GT occlusion or identity'})
        elif e['kind']=='CHUNK_END':
            raw=d['result'];out=execution(raw)
            out['actions']=[{'action':({'type':x['action']['type'],'parameters':'REDACTED_ENGINEERING_REFERENCE'} if source=='ENGINEERING_REFERENCE' else x['action']),
                              'completed':x['result'].get('ok') is True} for x in raw.get('results',[])]
            add(e,'execution',out)
        elif e['kind'] in ('FAULT','STOP'):
            add(e,'error',{'code':error_code(d.get('error') or d.get('reason'))})
        elif e['kind']=='TERMINAL':add(e,'closed',{'closed':True,'score':'PRIVATE_NOT_EXPORTED'})
    if any(a['monotonic']>b['monotonic'] for a,b in zip(events,events[1:])):raise ValueError('NONMONOTONIC_ARCHIVE')
    (output/'events.jsonl').write_text(''.join(json.dumps(e,allow_nan=False)+'\n' for e in events))
    files={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file()}
    (output/'index.json').write_text(json.dumps({'version':VERSION,'mode':'READ_ONLY_REPLAY','source':source,'files':files,
       'score_included':False,'original_timeline_sha256':hashlib.sha256(timeline.read_bytes()).hexdigest(),
       'camera_motion_available':len({tuple(p) for p in camera_poses})>1,'action_parameters':'redacted for engineering reference; real executed feedback retained'},indent=2))
    return {'events':len(events),'observations':len(camera_poses),'wrist_pose_variants':len({tuple(p) for p in camera_poses}),'image_quality':image_quality}
