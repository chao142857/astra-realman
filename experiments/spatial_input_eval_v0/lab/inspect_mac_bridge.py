#!/usr/bin/env python3
"""Read-only listener/process/file checks and CLI version/help; never HTTP /decide."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def inspect(original,output):
    output.mkdir(parents=True,exist_ok=False)
    def command(args):
        p=subprocess.run(args,capture_output=True,text=True,timeout=20)
        return {'command':args,'return_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    mac=command(['lsof','-nP','-iTCP:18767','-sTCP:LISTEN'])
    lab=command(['ssh','yanglab','ss -ltnp "sport = :18766"'])
    token=command(['ssh','yanglab','test -r /home/tongji/alex/astra_realman_harness/config/codex_astra_bridge.token'])
    processes=subprocess.run(['ps','-axo','pid=,comm=,args='],capture_output=True,text=True,errors='replace',timeout=10)
    matches=[]
    # Save only PID/executable, never full args that could carry a credential.
    for line in processes.stdout.splitlines():
        parts=line.strip().split(None,2)
        if len(parts)==3 and ('codex_astra_mac_bridge.py' in parts[2] or ('ssh' in parts[1] and '18766:' in parts[2])):
            if any(word in parts[1] for word in ('python','ssh')):matches.append({'pid':parts[0],'executable':parts[1]})
    sys.path.insert(0,str(original.parent.parent))
    spec=importlib.util.spec_from_file_location('readonly_original_bridge',original)
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    preflight=bridge.preflight('/opt/homebrew/bin/codex',output/'original_cli_preflight')
    login=subprocess.run(['/opt/homebrew/bin/codex','login','status'],stdin=subprocess.DEVNULL,
        capture_output=True,text=True,timeout=15,cwd=output/'original_cli_preflight/input_only',
        env=bridge.worker_environment('/opt/homebrew/bin/codex',output/'original_cli_preflight'))
    # Persist only the type, never arbitrary CLI output or credential material.
    login_type='CHATGPT' if login.returncode==0 and 'Logged in using ChatGPT' in (login.stdout+login.stderr) else 'UNCONFIRMED'
    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'mac_listener_18767':mac,
        'lab_listener_18766':lab,'bridge_or_tunnel_processes':matches,'process_check_return_code':processes.returncode,
        'lab_token_file_readable':token['return_code']==0,'token_contents_read_or_copied':False,'original_worker_login_type':login_type,'login_status_return_code':login.returncode,
        'original_bridge_path':str(original),'original_bridge_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
        'cli_version_help_preflight':preflight['status'],'http_endpoint_requests':0,'real_model_calls':0,
        'online_status':'OFFLINE' if mac['return_code']==1 and len(lab['stdout'].splitlines())==1 else 'NEEDS_LISTENER_REVIEW',
        'generation_compatibility':'NOT_VERIFIED; version/help does not prove current Astra generation works'}
    (output/'health.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original-bridge',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();inspect(args.original_bridge,args.output)
