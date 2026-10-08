"""Isolated stdlib-only adapter to the unmodified, verified bridge.infer()."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import signal
import threading
import time
from bridge import infer,preflight


class Stop:
    def __init__(self):self.event=threading.Event()
    def is_set(self):return self.event.is_set() or Path('/output/CANCEL').exists()
    def set(self,*_):self.event.set()
    def wait(self,seconds):self.event.wait(seconds);return self.is_set()


def main():
    p=argparse.ArgumentParser();p.add_argument('--executable',required=True)
    p.add_argument('--sha256');p.add_argument('--payload-sha256');p.add_argument('--deadline',type=float)
    p.add_argument('--preflight',action='store_true');a=p.parse_args()
    if a.preflight:
        record=preflight(a.executable,Path('/output/preflight'))
        print(json.dumps(record),flush=True);return 0 if record['status']=='PASS' else 1
    stop=Stop();signal.signal(signal.SIGTERM,stop.set);signal.signal(signal.SIGINT,stop.set)
    record={'raw':'','events':'','error':None,'return_code':None,'usage':None,'usage_events':[],
            'worker_started_monotonic':None,'worker_finished_monotonic':None,
            'server_model':'unknown','server_effort':'unknown','server_internal_retries':'unknown'}
    try:
        raw=Path('/input/wire.json').read_bytes();payload_bytes=Path('/input/payload.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=a.sha256:raise ValueError('FROZEN_WIRE_HASH')
        if hashlib.sha256(payload_bytes).hexdigest()!=a.payload_sha256:raise ValueError('FROZEN_PAYLOAD_HASH')
        wire=json.loads(raw);payload=json.loads(payload_bytes)
        if payload['context']!=wire:raise ValueError('WIRE_CONTEXT_MISMATCH')
        if len(payload['images'])!=len(wire['attachments']):raise ValueError('IMAGE_COUNT')
        for item,blob in zip(wire['attachments'],payload['images']):
            if Path(item['file']).name!=item['file']:raise ValueError('IMAGE_PATH')
            data=Path('/input',item['file']).read_bytes()
            if data!=base64.b64decode(blob,validate=True) or hashlib.sha256(data).hexdigest()!=item['sha256']:
                raise ValueError('FROZEN_IMAGE_HASH')
        remaining=min(30.,a.deadline-time.monotonic())
        if remaining<=0 or stop.is_set():raise RuntimeError('NO_REQUEST_BUDGET_OR_CANCELLED')
        record['worker_started_monotonic']=time.monotonic()
        Path('/output/infer_started.json').write_text(json.dumps({'started_monotonic':record['worker_started_monotonic'],
            'timeout_s':remaining,'deadline_monotonic':a.deadline,'payload_sha256':a.payload_sha256}))
        result=infer(payload,stop,executable=a.executable,run_root='/output/bridge',timeout_s=remaining)
        record.update(result)
        # Preserve every returned usage object separately; never add nested token fields.
        for line in result.get('events','').splitlines():
            try:event=json.loads(line)
            except (ValueError,TypeError):continue  # raw event stream remains untouched
            if isinstance(event,dict) and 'usage' in event:record['usage_events'].append(event)
        if len(record['usage_events'])==1:record['usage']=record['usage_events'][0]['usage']
    except Exception as exc:record['error']=type(exc).__name__+':'+str(exc)
    finally:
        record['worker_finished_monotonic']=time.monotonic()
        Path('/output/worker_record.json').write_text(json.dumps(record,allow_nan=False)+'\n')
        print(json.dumps(record,allow_nan=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
