#!/usr/bin/env python3
"""Export only captured RGB/state/calibration and safe feedback from closed run.
Does not read result/score/private trace/engineering plans. No process/model launch.
"""
import argparse,copy,json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engineering.public_view import observation,execution

def export(run,output):
    output.mkdir(parents=True,exist_ok=False);records=[]
    for line in (run/'episode/timeline.jsonl').read_text().splitlines():
        e=json.loads(line)
        if e['kind']=='OBSERVATION':
            data=copy.deepcopy(e['data'])
            # Raw logs retain the actual original paths. Resolve only known
            # scene/obs_NNNN images relative to this archive after relocation.
            for camera,path in data['images'].items():
                old=Path(path)
                if old.name!=camera+'.png' or not re.fullmatch(r'obs_\d+',old.parent.name):
                    raise ValueError('ARCHIVE_IMAGE_PATH')
                data['images'][camera]=str(run/'scene'/old.parent.name/old.name)
            name='obs-%04d'%len(records);o=observation(data,output/name)
            records.append({'kind':'observation','file':name+'/observation.json','observation_id':o['observation_id']})
        elif e['kind']=='CHUNK_END':records.append({'kind':'execution','wall_monotonic':e['wall_monotonic'],
            'physics_step':e['physics_step'],'feedback':execution(e['data']['result'])})
    (output/'index.json').write_text(json.dumps({'source':'ENGINEERING_REFERENCE_CAPTURE','records':records,
      'expert_proposals_exported':False,'private_score_exported':False,'raw_errors_location':'retained in private source archive; only public error codes exported',
      'model_input_policy':'No automatic model binding. Only RGB/proprioception/calibration/safe feedback; engineering answers never exported.'},indent=2)+'\n')
    print(json.dumps({'output':str(output),'records':len(records),'model_calls':0,'hardware_calls':0}))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();export(a.run,a.output)
