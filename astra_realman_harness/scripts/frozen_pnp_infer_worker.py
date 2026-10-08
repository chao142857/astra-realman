"""Standalone 90s frozen diagnostic. Existing bridge/Stop; no full-task worker main."""
import argparse
import hashlib
import json
from pathlib import Path
import signal
import time
from bridge import infer
from infer_worker import Stop


def main():
    p=argparse.ArgumentParser();p.add_argument('--executable',required=True)
    p.add_argument('--payload-sha256',required=True);p.add_argument('--deadline',type=float,required=True);a=p.parse_args()
    stop=Stop();signal.signal(signal.SIGTERM,stop.set);signal.signal(signal.SIGINT,stop.set)
    result={'raw':'','events':'','stderr':'','error':None,'return_code':None}
    try:
        data=Path('/input/payload.json').read_bytes()
        if hashlib.sha256(data).hexdigest()!=a.payload_sha256:raise ValueError('FROZEN_PAYLOAD_HASH')
        payload=json.loads(data)
        remaining=min(90.,a.deadline-time.monotonic())
        if remaining<=0 or stop.is_set():raise RuntimeError('CANCELLED_OR_NO_BUDGET')
        Path('/output/infer_started.json').write_text(json.dumps({'started_monotonic':time.monotonic(),'timeout_s':remaining,'payload_sha256':a.payload_sha256}))
        result=infer(payload,stop,executable=a.executable,run_root='/output/bridge',timeout_s=remaining)
    except Exception as exc:result['error']=type(exc).__name__+':'+str(exc)
    finally:
        Path('/output/worker_record.json').write_text(json.dumps(result,allow_nan=False)+'\n')
        print(json.dumps(result,allow_nan=False),flush=True)


if __name__=='__main__':main()
