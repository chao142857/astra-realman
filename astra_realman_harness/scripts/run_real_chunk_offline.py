#!/usr/bin/env python3
"""Offline chunk/GUI migration only. No SDK, real cameras, Bridge or model calls."""
import argparse
import json
import signal
import sys
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from real_chunk_gui import OfflineChunkConsole
from astra_gui import make_server


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proposal',type=Path,help='Optional archived JSON; preserved unchanged, fake execution only.')
    p.add_argument('--once',action='store_true',help='Write one offline fixture/proposal run, then exit.')
    p.add_argument('--port',type=int,default=8886)
    p.add_argument('--three-calibration',type=Path,help='Existing three-camera JSON, verified by frozen SHA256.')
    p.add_argument('--live-cameras',action='store_true',help='Read-only four-camera preview; no robot/model execution.')
    a=p.parse_args();console=OfflineChunkConsole(three_calibration=a.three_calibration,live_cameras=a.live_cameras)
    if a.live_cameras:console.camera.start()
    try:
        if a.proposal or a.once:
            settings={'raw_proposal':a.proposal.read_text()} if a.proposal else {}
            result=console.start(settings);print(json.dumps(result,ensure_ascii=False),flush=True)
        if a.once:return
        server=make_server(console,a.port);server.timeout=.2
        stop=threading.Event()
        signal.signal(signal.SIGINT,lambda *_:stop.set());signal.signal(signal.SIGTERM,lambda *_:stop.set())
        print('OFFLINE CHUNK GUI: '+console.url+' | model=0 robot_motion=0 live_cameras='+str(a.live_cameras),flush=True)
        try:
            while not stop.is_set():server.handle_request()
        finally:server.server_close()
    finally:console.close()

if __name__=='__main__':main()
