#!/usr/bin/env python3
"""Astra all-in-one local GUI. Default opens shared read-only cameras; experiments start only from UI."""
import argparse
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from astra_gui import Console, make_server


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8877)
    p.add_argument('--demo',action='store_true',help='Synthetic offline GUI; no SDK, cameras or model calls.')
    p.add_argument('--demo-cameras',type=int,choices=range(5),default=4)
    p.add_argument('--cameras-only',action='store_true',help='Read-only 2x2 camera monitor; start endpoint disabled.')
    p.add_argument('--python',default=sys.executable,help='Python interpreter for existing experiment runners.')
    p.add_argument('--lock-path',type=Path,default=Path('/home/tongji/alex/astra_realman_harness/logs/auto-pick.lock'))
    p.add_argument('--open-browser',action='store_true')
    a=p.parse_args()
    if not 0<=a.port<=65535:p.error('port must be 0..65535')
    console=Console(demo=a.demo,cameras_only=a.cameras_only,demo_count=a.demo_cameras,python=a.python,lock_path=a.lock_path)
    server=make_server(console,a.port);server.timeout=.2
    console.camera.start()
    closing=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:closing.set());signal.signal(signal.SIGTERM,lambda *_:closing.set())
    if hasattr(signal,'SIGHUP'):signal.signal(signal.SIGHUP,lambda *_:closing.set())
    print('ASTRA GUI → '+console.url+' | '+('SYNTHETIC DEMO: no hardware/model' if a.demo else 'LOCAL CAMERA + EXPERIMENT CONSOLE'),flush=True)
    if a.open_browser:webbrowser.open(console.url)
    asked=False
    try:
        while True:
            server.handle_request()
            if closing.is_set():
                if not asked:
                    asked=True;console.closing=True;console.stop()
                    print('GUI shutdown requested; waiting for owned experiment to finish readback. No forced hardware termination.',flush=True)
                if not console.active:break
    finally:
        console.close();server.server_close()

if __name__=='__main__':main()
