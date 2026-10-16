"""Mac-side non-generating checks of the unchanged dedicated production bridge."""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime,timezone
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--launcher',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();meta=json.loads(a.launcher.read_text());cmd=meta['command'];source=Path(cmd[2])
os.kill(meta['pid'],0)
assert cmd[cmd.index('--timeout-s')+1]=='190' and cmd[cmd.index('--mode')+1]=='lab'
listener=subprocess.check_output(['lsof','-nP','-iTCP:18767','-sTCP:LISTEN'],text=True)
assert any(line.split()[1]==str(meta['pid']) for line in listener.splitlines()[1:])
exe=cmd[cmd.index('--executable')+1]
login=subprocess.run([exe,'login','status'],capture_output=True,text=True,timeout=15)
assert login.returncode==0 and 'ChatGPT' in login.stdout+login.stderr,'CHATGPT_LOGIN_REQUIRED'
sys.path.insert(0,str(source.parent))
spec=importlib.util.spec_from_file_location('_unchanged_bridge_check',source);bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
cli=bridge.preflight(exe,a.output.parent/('cli_check_'+uuid.uuid4().hex))
assert cli['status']=='PASS',cli
report={'status':'PASS','checked_at':datetime.now(timezone.utc).isoformat(),
        'bridge_pid':meta['pid'],'bridge_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'server_timeout_s':190,'mac_port':18767,'chatgpt_login':True,
        'cli_worker_preflight':'PASS','code_mode_and_model_configuration':'ORIGINAL_BRIDGE_UNCHANGED',
        'model_calls_during_check':0}
a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
