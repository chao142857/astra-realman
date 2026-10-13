#!/usr/bin/env python3
"""Read-only software and archived decision evidence. Never imports hardware SDKs."""
import argparse
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from spatial_eval.schema import write, strict_json


def probe(cmd):
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        def sanitize(text):
            return re.sub(r'sk-[A-Za-z0-9_.*-]+','[REDACTED_API_KEY]',text)
        return {'command':cmd,'return_code':p.returncode,'stdout':sanitize(p.stdout),'stderr':sanitize(p.stderr)}
    except (OSError,subprocess.TimeoutExpired) as e:return {'command':cmd,'error':type(e).__name__+':'+str(e)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cli',type=Path)
    p.add_argument('--history-root',type=Path,default=Path('/home/tongji/alex'))
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    packages={}
    for name in ['sapien','numpy','Pillow','jsonschema','opencv-python','transforms3d']:
        try:packages[name]=version(name)
        except PackageNotFoundError:packages[name]=None
    environment={'platform':platform.platform(),'python':sys.version,'executable':sys.executable,
                 'prefix':sys.prefix,'base_prefix':sys.base_prefix,'packages':packages,
                 'system_node':probe(['node','--version']),
                 'gpu':probe(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv']),
                 'bwrap':shutil.which('bwrap'),'native_cli_on_original_path':shutil.which('codex'),
                 'hardware_probes':[],'generation_requests':0}
    if a.cli:
        environment['prepared_native_cli']=probe([str(a.cli),'--version'])
        environment['local_login_status']=probe([str(a.cli),'login','status'])
        for subcmd in [['features','list'],['exec','--help']]:
            r=probe([str(a.cli),*subcmd]);write(a.output/('_'.join(subcmd).replace('--','')+'.json'),r)
    write(a.output/'environment.json',environment)
    records=[]
    for project in ['astra_lab_20261007','astra_parallel_arms_20261007','astra_onsite_1011','acve-p0-1011']:
        root=a.history_root/project
        write(a.output/(project+'_git.json'),{'status':probe(['git','-C',str(root),'status','--short']),
                                              'head':probe(['git','-C',str(root),'rev-parse','HEAD'])})
        for result in sorted(root.rglob('backend_result.json')):
            try:
                metadata=json.loads(result.read_text());raw=result.with_name('astra_raw.txt')
                if metadata.get('status')!='COMPLETE' or metadata.get('model')!='gpt-6-astra' or not raw.exists():continue
                value=strict_json(raw.read_text());events=result.with_name('events.jsonl')
                completed=False
                if events.exists():
                    completed=any(json.loads(line).get('type')=='turn.completed' for line in events.read_text().splitlines() if line.strip())
                if not isinstance(value,dict) or not completed:continue
                records.append({'path':str(result.parent),'model':'gpt-6-astra','backend':metadata.get('backend'),
                                'provider':metadata.get('provider'),'auth_method':metadata.get('auth'),
                                'cli_return_code':metadata.get('cli_return_code'),'strict_json':'PASS',
                                'completed_event':completed,'top_level_keys':sorted(value),
                                'token_usage':metadata.get('token_usage'),'latency_s':metadata.get('cli_latency_s'),
                                'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),
                                'events_sha256':hashlib.sha256(events.read_bytes()).hexdigest()})
            except (ValueError,OSError):continue
    write(a.output/'historical_success.json',{'verified_records':records,'count':len(records),
                                             'generation_requests':0,
                                             'scope':'Archived software evidence only; no hardware connection, no rerun, no claim of spatial-schema acceptance'})
    print('historical verified Astra JSON records=',len(records),'new generation requests=0')


if __name__=='__main__':main()
