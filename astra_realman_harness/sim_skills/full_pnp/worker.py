#!/usr/bin/env python3
"""Sandboxed RGB heuristic+delay stub; no imports or mounts of scene, score or answers."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ENTRY=time.monotonic()
import numpy as np
from rgb import detect,pixel_world_on_plane


def decide(s):
    # Only attached full current images; ROI/past are separately identified.
    fs={a['camera']:detect(a['file']) for a in s['attachments'] if a['temporal_role']=='current' and a['representation']=='full'}
    role=s['role'];binding=s['binding']
    if role=='E':
        # E thumbnails have rescaled calibration; bbox remains normalized.
        choices=[c for c in ('fixed','wrist') if fs[c]['object']['status']=='visible']
        camera=max(choices,key=lambda c:fs[c]['object']['visible_pixels']) if choices else 'fixed'
        obj=fs[camera]['object']
        return {'kind':'evidence','binding':binding,'selected_camera':camera,'bbox':obj.get('bbox_normalized'),
                'claims':{'object_visible':obj['status'],'identity':'unique_color_hypothesis_not_verified','holding':'unknown'},
                'evidence_refs':[a['id'] for a in s['attachments']],'source':'RGB_HEURISTIC_STUB'}
    n=s['progress']['completed_chunks']
    if s['execution']['status']=='executing':n+=1  # explicitly a predicted parent completion
    pose=s['expected_join']['pad_pose']
    move=lambda xyz:{'type':'move_pose','pose':[float(x) for x in xyz]+[0,1,0,0]}
    def estimate(key,z):
        values=[]
        for c,f in fs.items():
            if f[key]['status']=='visible':
                try:values.append(pixel_world_on_plane(f[key],s['observation']['calibration'][c],z))
                except ValueError:pass
        if not values:raise ValueError('RGB_ESTIMATE_UNKNOWN:'+key)
        return np.median(values,axis=0).tolist()
    requirements=['scene_healthy'];operation='chunk';verdict=None
    if n==0:
        x,y,_=estimate('object',.025)
        actions=[move([x,y,.18]),move([x,y,.08]),move([x,y,.04])];requirements+=['object_static']
    elif n==1:actions=[{'type':'gripper','opening':.45}];requirements+=['object_static']
    elif n==2:
        actions=[move([pose[0],pose[1],pose[2]+.08]),{'type':'hold','seconds':1.2}]
        # A cautious probe lift after a fresh post-closure observation, NOT a held assertion.
    elif n==3:
        x,y,_=estimate('goal',0.)
        actions=[move([x,y,.12])];requirements+=['goal_static','object_near_tool']
    elif n==4:
        actions=[move([pose[0],pose[1],.04])];requirements+=['goal_static','object_near_tool']
    elif n==5:actions=[{'type':'gripper','opening':1.}];requirements+=['goal_static','object_near_tool']
    elif n==6:actions=[move([pose[0],pose[1],.12])];requirements+=['goal_static']
    else:
        actions=[];operation='finish';verdict='done';requirements+=['object_at_goal']
    return {'kind':'candidate','binding':binding,'operation':operation,'actions':actions,
            'requirements':requirements,'evidence_refs':[a['id'] for a in s['attachments']],
            'parent_evidence_hash':s.get('evidence_packet_hash'),'verdict':verdict,
            'reason':'OFFLINE_RGB_HEURISTIC_STUB_NOT_ASTRA; planned action is not measured success'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--sha256',required=True);p.add_argument('--delay-s',type=float,required=True)
    a=p.parse_args();data=Path('wire.json').read_bytes()
    if hashlib.sha256(data).hexdigest()!=a.sha256:raise ValueError('WIRE_HASH')
    s=json.loads(data)
    for record in s['attachments']:
        if hashlib.sha256(Path(record['file']).read_bytes()).hexdigest()!=record['sha256']:raise ValueError('IMAGE_HASH')
    ready=time.monotonic();time.sleep(a.delay_s)
    try:answer=decide(s)
    except ValueError as exc:
        if s['role']=='E':raise
        answer={'kind':'candidate','binding':s['binding'],'operation':'observe','actions':[],
                'requirements':['scene_healthy'],'evidence_refs':[v['id'] for v in s['attachments']],
                'parent_evidence_hash':s.get('evidence_packet_hash'),'verdict':None,'reason':str(exc)}
    if hashlib.sha256(Path('wire.json').read_bytes()).hexdigest()!=a.sha256:raise ValueError('WIRE_CHANGED')
    print(json.dumps({'source':'RGB_DELAYED_STUB_NOT_ASTRA','candidate':answer,'worker_entry_monotonic':ENTRY,
                      'worker_started_monotonic':ready,'worker_finished_monotonic':time.monotonic(),
                      'model_calls':0,'usage':None}),flush=True)

if __name__=='__main__':main()
