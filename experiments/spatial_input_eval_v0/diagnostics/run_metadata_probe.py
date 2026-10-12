"""Reproduce non-generation diagnostics in the unchanged production bwrap."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'astra_realman_harness'))
from sim_skills.full_pnp.infer_process import InferConfig,sandbox_command


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',choices=('account-routing','rate-limits','frozen-input','protocol-schema'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frozen-sample',type=Path)
    parser.add_argument('--expected-netns',help='Abort before launching if the outer namespace differs.')
    args=parser.parse_args()
    namespace=os.readlink('/proc/self/ns/net')
    if args.expected_netns and namespace!=args.expected_netns:raise ValueError('WRONG_LAUNCHER_NETWORK_NAMESPACE')
    if args.kind=='frozen-input' and args.frozen_sample is None:parser.error('--frozen-sample required')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'runtime').mkdir()
    if args.kind=='frozen-input':shutil.copytree(args.frozen_sample/'input_only',out/'input_only')
    else:(out/'input_only').mkdir()
    config=InferConfig();cmd,env=sandbox_command(out,config)
    cmd=cmd[:cmd.index('--chdir')]+['--chdir','/input','--setenv','TMPDIR','/tmp']
    if args.kind=='protocol-schema':
        cmd += [config.executable,'app-server','generate-json-schema','--out','/output/protocol_schema','--experimental']
    else:
        name='frozen_input_probe.py' if args.kind=='frozen-input' else 'account_routing_probe.py'
        (out/'worker_code'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
        cmd += [sys.executable,'-B','/code/'+name,config.executable]
        if args.kind=='rate-limits':cmd+=['--rate-limits-only']
    record={'kind':args.kind,'command':cmd,'launcher_network_namespace':namespace,
            'inference_requests':0,'environment_keys':sorted(env)}
    (out/'launcher.json').write_text(json.dumps(record,indent=2)+'\n')
    proc=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=45)
    (out/'stdout.log').write_text(proc.stdout);(out/'stderr.log').write_text(proc.stderr)
    record['return_code']=proc.returncode
    (out/'launcher.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'kind':args.kind,'return_code':proc.returncode,'inference_requests':0}))
    return proc.returncode


if __name__=='__main__':raise SystemExit(main())
