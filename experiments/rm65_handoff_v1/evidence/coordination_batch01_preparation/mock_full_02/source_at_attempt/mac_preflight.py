"""Run on Mac: login/version/help and actual existing service/tunnel, zero generation."""
import argparse
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--service',type=Path,required=True);p.add_argument('--tunnel',type=Path,required=True)
    p.add_argument('--campaign-id',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('NEW_MAC_PREFLIGHT_OUTPUT_REQUIRED')
    service=json.loads(a.service.read_text());tunnel=json.loads(a.tunnel.read_text());cmd=service['command']
    source=Path(cmd[2]);exe=cmd[cmd.index('--executable')+1]
    frozen=json.loads((Path(__file__).parent/'freeze.json').read_text())['source_hashes']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==frozen['production/codex_astra_mac_bridge.py']
    for pid in (service['pid'],tunnel['pid']):os.kill(pid,0)
    actual=subprocess.check_output(['ps','-p',str(service['pid']),'-o','command='],text=True)
    assert str(source) in actual and '--timeout-s 190' in actual and '--port 18767' in actual
    actual_tunnel=subprocess.check_output(['ps','-p',str(tunnel['pid']),'-o','command='],text=True)
    assert '127.0.0.1:18766:127.0.0.1:18767' in actual_tunnel and 'ubuntu-robot' in actual_tunnel
    s=socket.socket();s.settimeout(2)
    try:assert s.connect_ex(('127.0.0.1',18767))==0
    finally:s.close()
    sys.path.insert(0,str(source.parent));spec=importlib.util.spec_from_file_location('_original_campaign_bridge',source)
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    a.output.parent.mkdir(parents=True,exist_ok=True);worker=a.output.parent/'cli_worker_preflight'
    cli=bridge.preflight(exe,worker);assert cli['status']=='PASS'
    login=subprocess.run([exe,'login','status'],env=bridge.worker_environment(exe,worker),cwd=worker/'input_only',
                         stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15)
    assert login.returncode==0 and 'ChatGPT' in login.stdout+login.stderr
    result={'status':'PASS','campaign_id':a.campaign_id,'checked_at':datetime.now(timezone.utc).isoformat(),
            'chatgpt_login':True,'bridge_pid':service['pid'],'tunnel_pid':tunnel['pid'],'server_timeout_s':190,
            'bridge_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'cli_worker_preflight':'PASS','code_mode_and_model_configuration':'ORIGINAL_BRIDGE_UNCHANGED','real_requests':0}
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
