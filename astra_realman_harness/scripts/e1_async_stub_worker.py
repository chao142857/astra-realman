#!/usr/bin/env python3
"""Offline delayed worker: reads only a frozen snapshot, never imports a scene or a model API."""
import argparse
import hashlib
import json
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--delay-s',type=float,required=True)
    a=p.parse_args();started=time.monotonic()
    data=a.snapshot.read_bytes()
    if hashlib.sha256(data).hexdigest()!=a.sha256:raise ValueError('SNAPSHOT_HASH')
    snapshot=json.loads(data)
    for image in snapshot['observation']['attachments']:
        if hashlib.sha256(Path(image['file']).read_bytes()).hexdigest()!=image['sha256']:raise ValueError('IMAGE_HASH')
    time.sleep(a.delay_s)
    if hashlib.sha256(a.snapshot.read_bytes()).hexdigest()!=a.sha256:raise ValueError('SNAPSHOT_CHANGED')
    directive=snapshot['public_task_update']['instruction']
    choice=snapshot['offered_skill']
    if choice=='finish_place' and directive=='Keep the item held; do not release it.':choice='hold'
    if directive=='Stop this episode now.':choice='stop'
    candidate={'binding':dict(snapshot['binding'],snapshot_sha256=a.sha256),'choice':choice,
               'applicability':snapshot['applicability']}
    print(json.dumps({'source':'DELAYED_STUB_NOT_ASTRA','candidate':candidate,
        'worker_started_monotonic':started,'worker_finished_monotonic':time.monotonic(),
        'model_calls':0,'usage':None}),flush=True)


if __name__=='__main__':main()
