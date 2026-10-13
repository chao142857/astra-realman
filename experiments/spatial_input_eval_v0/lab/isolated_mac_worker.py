#!/usr/bin/env python3
"""Dedicated loopback worker using the unchanged original bridge Handler and infer.

Each OS process owns separate JOBS/BUSY state. Authentication follows the original
bridge's in-memory SSH token read; no credential file is copied or archived.
SSH port forwarding is managed separately, never by the original main().
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

BRIDGE_SHA256='922c63556a838a1a9280d76b280e22babba5d517e10073c18c05a033dfce7bae'


def load_bridge(path, name):
    path=Path(path).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest()!=BRIDGE_SHA256:
        raise ValueError('ORIGINAL_BRIDGE_SOURCE_CHANGED')
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bridge-source',type=Path,required=True)
    p.add_argument('--worker',type=int,choices=range(1,5),required=True)
    p.add_argument('--metadata',type=Path,required=True)
    args=p.parse_args()
    bridge=load_bridge(args.bridge_source,'spatial_worker_'+str(args.worker))
    # Exactly the original token-read command and original ChatGPT HOME auth path.
    token=subprocess.check_output(['ssh','yanglab','cat '+bridge.ROOT+'/config/codex_astra_bridge.token'],text=True).strip()
    if len(token)<16 or '\n' in token or '\r' in token:raise ValueError('INVALID_BRIDGE_TOKEN')
    port=18770+args.worker
    server=ThreadingHTTPServer(('127.0.0.1',port),bridge.Handler);server.token=token
    server.inference_options=dict(executable='/opt/homebrew/bin/codex',
        run_root='/private/tmp/codex-astra-bridge',timeout_s=180)
    # Runtime folders are per-request UUIDs created by the original infer implementation.
    metadata=dict(worker=args.worker,pid=os.getpid(),port=port,loopback_only=True,
        bridge_source=str(args.bridge_source.resolve()),bridge_source_sha256=BRIDGE_SHA256,
        server_timeout_s=180,executable='/opt/homebrew/bin/codex',
        authentication='Original SSH token read in memory; original Mac ChatGPT auth',
        original_handler_and_infer=True,credentials_archived=False)
    args.metadata.parent.mkdir(parents=True,exist_ok=True)
    args.metadata.write_text(json.dumps(metadata,indent=2)+'\n')
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    server.timeout=.5
    print(f'isolated worker {args.worker} ready on loopback {port}; timeout=180; no robot control',flush=True)
    try:
        while not stop.is_set():server.handle_request()
    finally:
        with bridge.MUTEX:
            for event in bridge.JOBS.values():event.set()
        server.server_close()


if __name__=='__main__':main()
