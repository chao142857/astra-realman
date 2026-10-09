#!/usr/bin/env python3
"""Offline contracts / read-only environment preflight. No real-model or physics mode."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('offline','preflight'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    report={'real_astra_calls':0,'hardware_calls':0,'new_physics_episodes':0,
        'learned_forward_passes':0,'native_subagent_acceptance':'NOT_VERIFIED'}
    if a.mode=='preflight':
        target_python=sys.executable
        if a.config:
            cfg=json.loads(a.config.read_text());target_python=str(Path(cfg['venv'])/'bin/python')
        report['dependency_python']=target_python
        try:
            probe=subprocess.run([target_python,'-I','-c',
                "import importlib.util,json; print(json.dumps({x:bool(importlib.util.find_spec(x)) for x in ('torch','depth_anything_3','safetensors','huggingface_hub')}))"],capture_output=True,text=True,timeout=10)
            report['dependencies']=json.loads(probe.stdout) if probe.returncode==0 else {'configured_python':False}
        except (OSError,ValueError): report['dependencies']={'configured_python':False}
        gpu=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,memory.used,driver_version','--format=csv,noheader'],capture_output=True,text=True)
        report['gpu']={'exit_code':gpu.returncode,'stdout':gpu.stdout,'stderr':gpu.stderr}
        report['learned_inference']='NOT_RUN';report['latency_s']=None;report['peak_vram_bytes']=None
        report['blockers']=[]
        if not all(report['dependencies'].values()):report['blockers'].append('MISSING_DEPENDENCIES')
        if gpu.returncode:report['blockers'].append('GPU_NOT_VISIBLE_IN_THIS_CONTEXT')
        if a.config:
            from platform_v1.research.learned_runtime import validate_config
            try:validate_config(json.loads(a.config.read_text()))
            except Exception as exc:report['blockers'].append(str(exc))
        else:report['blockers'].append('NO_PINNED_WEIGHT_AND_RUNTIME_CONFIG')
        report['status']='BLOCKED_PREREQUISITES' if report['blockers'] else 'PREFLIGHT_ONLY_NOT_MODEL_ACCEPTANCE'
    else:
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(BASE)+os.pathsep+str(BASE/'tests')}
        command=[sys.executable,'-m','unittest','test_lwh_integration','test_research_adapters','test_platform_v1','-v']
        start=time.monotonic()
        with (a.output/'tests.log').open('w') as log:
            result=subprocess.run(command,cwd=BASE,env=env,stdout=log,stderr=subprocess.STDOUT)
        report.update(command=command,test_exit_code=result.returncode,wall_s=time.monotonic()-start,
            source='SYNTHETIC_CONTRACT_FIXTURES_FAKE_MODEL_EXECUTOR_DEPTH_NOT_PHYSICAL_OR_LEARNED_PERFORMANCE')
        before=json.loads((BASE/'docs/lwh_integration/protected_before.json').read_text())
        changed=[name for name,h in before['files'].items() if not Path(name).is_file() or hashlib.sha256(Path(name).read_bytes()).hexdigest()!=h]
        report['protected_file_count']=len(before['files']);report['protected_changed']=changed
        report['status']='PASS' if result.returncode==0 and not changed else 'FAIL'
        diff=subprocess.run(['git','diff','--check'],cwd=BASE,capture_output=True,text=True)
        report['git_diff_check']=diff.stdout+diff.stderr
        if diff.returncode:report['status']='FAIL'
    (a.output/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
