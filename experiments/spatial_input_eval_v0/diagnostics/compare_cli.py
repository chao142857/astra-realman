"""Compare native CLI metadata under original bwrap with only candidate HTTPS vars."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'astra_realman_harness'))
from sim_skills.full_pnp.infer_process import InferConfig,sandbox_command
from scripts.codex_astra_mac_bridge import worker_environment


def main(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False);rows=[]
    config=InferConfig()
    for name,proxy in (('filtered',False),('https_proxy_candidate',True)):
        folder=output/name;folder.mkdir();(folder/'input_only').mkdir();(folder/'runtime').mkdir()
        command,env=sandbox_command(folder,config)
        if proxy:env.update({k:os.environ[k] for k in ('HTTPS_PROXY','https_proxy','NO_PROXY','no_proxy') if k in os.environ})
        (folder/'worker_code/cli_network_probe.py').write_bytes(Path(__file__).with_name('cli_network_probe.py').read_bytes())
        idx=command.index('--chdir');command=command[:idx]+['--chdir','/input','--setenv','TMPDIR','/tmp',sys.executable,'-B','/code/cli_network_probe.py',config.executable]
        proc=subprocess.run(command,capture_output=True,text=True,env=env,timeout=60)
        (folder/'stdout.json').write_text(proc.stdout);(folder/'stderr.log').write_text(proc.stderr)
        record={'case':name,'return_code':proc.returncode,'command':command,'environment_keys':sorted(env),'inference_requests':0}
        if proc.returncode==0:record['result']=json.loads(proc.stdout)
        (folder/'probe.json').write_text(json.dumps(record,indent=2));rows.append(record)
        print(name,proc.returncode,[(r['name'],r['return_code'],r.get('model_count'),r.get('refresh_error_logged')) for r in record.get('result',{}).get('checks',[])],flush=True)
    (output/'comparison.json').write_text(json.dumps({'inference_requests':0,'cases':rows},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
