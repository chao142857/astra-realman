"""Run identical no-model probes with production bwrap mounts and controlled envs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'astra_realman_harness'))
from sim_skills.full_pnp.infer_process import InferConfig,sandbox_command
from scripts.codex_astra_mac_bridge import worker_environment

PROXY_CANDIDATES=('HTTPS_PROXY','https_proxy','NO_PROXY','no_proxy')


def run(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    config=InferConfig();probe=Path(__file__).with_name('network_probe.py')
    base=worker_environment(config.executable,output)
    candidate=dict(base);candidate.update({k:os.environ[k] for k in PROXY_CANDIDATES if k in os.environ})
    rows=[]
    for name,env,sandbox in (('host_current',dict(os.environ),False),('host_filtered',base,False),
                             ('worker_filtered',base,True),('worker_https_proxy_candidate',candidate,True)):
        folder=output/name;folder.mkdir();(folder/'input_only').mkdir();(folder/'runtime').mkdir()
        if sandbox:
            command,_=sandbox_command(folder,config)
            (folder/'worker_code/network_probe.py').write_bytes(probe.read_bytes())
            index=command.index('--chdir')
            command=command[:index]+['--chdir','/input','--setenv','TMPDIR','/tmp',sys.executable,'-B','/code/network_probe.py']
        else:command=[sys.executable,'-B',str(probe)]
        # Record keys only. Values may contain credentials and must never be persisted.
        meta={'name':name,'sandbox':sandbox,'command':command,'environment_keys':sorted(env),'inference_requests':0}
        started=time.monotonic()
        try:
            proc=subprocess.run(command,capture_output=True,text=True,env=env,cwd=folder/'input_only',timeout=45)
            (folder/'stdout.json').write_text(proc.stdout);(folder/'stderr.log').write_text(proc.stderr)
            meta.update(return_code=proc.returncode)
            if proc.returncode==0:meta['result']=json.loads(proc.stdout)
        except subprocess.TimeoutExpired:meta.update(error='PROBE_TIMEOUT')
        meta['wall_latency_s']=time.monotonic()-started
        (folder/'probe.json').write_text(json.dumps(meta,indent=2));rows.append(meta)
        print(name,meta.get('return_code'),[(r['kind'],r.get('host') or r.get('url'),r['status'],r.get('http_status')) for r in meta.get('result',{}).get('probes',[])],flush=True)
    (output/'comparison.json').write_text(json.dumps({'inference_requests':0,'cases':rows},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output)
