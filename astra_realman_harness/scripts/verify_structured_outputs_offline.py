#!/usr/bin/env python3
"""Offline ONLY: production Broker/worker/bridge/CLI with loopback TLS endpoint.

Requires frozen S1 artifacts and the accepted CLI prefix. Uses --unshare-all,
no auth mount, no real calls. Refuses to reuse an output directory. Synthetic
world/responses remain FAKE_MODEL_RAW and never reach an Owner/Supervisor.
"""
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE),str(BASE/'tests')]
from platform_v1.research.broker import Broker
from platform_v1.research.public_store import PublicStore
from platform_v1.research import fusion
from sim_skills.full_pnp.infer_process import InferConfig
from scripts.structured_outputs import encoded, sha
from strict_schema_fixtures import prepare, complete, semantic_answer, synthetic_world, action_request, action_answer

LAUNCHER_SHA='29235c85a8d99f3423cde184aa4653341a70a815bc0abb6a5ae78cea7539945b'
CLI_SHA='9a820c17865fa825d04db416818679a9d63bd72e50835c396f496e5684626c9c'
def read(p):return json.loads(p.read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_bytes(encoded(v))

def tls_fixture(root):
    root.mkdir()
    def run(args):subprocess.run(['/usr/bin/openssl',*args],check=True,capture_output=True)
    run(['req','-x509','-newkey','rsa:2048','-sha256','-days','2','-nodes',
        '-keyout',str(root/'key.pem'),'-out',str(root/'cert.pem'),'-subj','/CN=OFFLINE SCHEMA TEST CA',
        '-addext','basicConstraints=critical,CA:TRUE'])
    run(['req','-newkey','rsa:2048','-nodes','-keyout',str(root/'leaf-key.pem'),
        '-out',str(root/'leaf.csr'),'-subj','/CN=api.openai.com'])
    (root/'extensions.txt').write_text('subjectAltName=DNS:api.openai.com,DNS:chatgpt.com\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
    run(['x509','-req','-in',str(root/'leaf.csr'),'-CA',str(root/'cert.pem'),'-CAkey',str(root/'key.pem'),
        '-CAcreateserial','-out',str(root/'leaf.pem'),'-days','2','-sha256','-extfile',str(root/'extensions.txt')])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen-attempt',type=Path,required=True)
    p.add_argument('--launcher',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cases',nargs='+',default=['e0','action_h4','local_reground','malformed','binding_wrong','http503','stream_truncated'])
    a=p.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    assert digest(a.launcher)==LAUNCHER_SHA
    assert digest(a.launcher.parent.parent/'libexec/codex')==CLI_SHA
    assert subprocess.check_output([str(a.launcher.parent.parent/'libexec/codex'),'--version'],text=True).strip()=='codex-cli 0.161.0'
    tls=a.output/'tls';tls_fixture(tls);results=[]
    old=read(a.frozen_attempt/'broker/broker-001/input_only/payload.json')
    obs=read(a.frozen_attempt/'rgb_only/OBSERVATION.json')
    request=read(a.frozen_attempt/'REQUEST.json');request['output_schema']=fusion.semantic_schema()
    assert obs['observation_id']=='rm65:0002' and len(old['images'])==3
    for name in a.cases:
        folder=a.output/name;folder.mkdir()
        case_obs=copy.deepcopy(obs)
        if name.startswith('action_h'):
            # E0 staging correctly has NO robot state. Action schema tests use
            # an explicitly synthetic archived state, never a live planning input.
            case_obs['state']=read(BASE/'tests/fixtures/research_public_rgb/observation.json')['state']
            save(folder/'SYNTHETIC_OBSERVATION.json',case_obs)
        store=PublicStore(a.frozen_attempt/'rgb_only',obs['episode_id']);store.observe(case_obs,obs['execution_epoch'])
        b=Broker(folder/'broker',store,InferConfig(str(a.launcher),fixture=True),deadline=time.monotonic()+90,
            epoch=lambda:obs['execution_epoch'],allowance=lambda:1,baseline_busy=lambda:False,emit=lambda *_:None)
        req=copy.deepcopy(request)
        if name.startswith('action_h'):
            H=int(name.split('action_h')[1]);fake=store.evidence_record('SYNTHETIC-E0','semantic_e0',{},'FAKE_MODEL_RAW',[obs['observation_id']],[])
            world=synthetic_world(store,case_obs,fake['evidence_id']);req=action_request(world,case_obs,H)
            save(folder/'SYNTHETIC_WORLD.json',world)
        elif name=='local_reground':req['role']='local_reground'
        row,job=prepare(b,req);answer=action_answer(row) if req['role']=='action' else semantic_answer(row)
        payload=read(job.folder/'input_only/payload.json')
        if name in ('e0','malformed','binding_wrong','http503','stream_truncated'):
            assert payload['context']==old['context'],'FROZEN_S1_PROMPT_CHANGED'
            assert payload['images']==old['images'],'FROZEN_S1_RGB_CHANGED'
        if name=='binding_wrong':answer['binding']['world_id']='FORGED'
        raw='{broken' if name=='malformed' else json.dumps(answer)
        fixture=folder/'endpoint';fixture.mkdir()
        for f in ('cert.pem','leaf.pem','leaf-key.pem'):shutil.copyfile(tls/f,fixture/f)
        shutil.copyfile(BASE/'tests/structured_endpoint_worker.py',fixture/'endpoint_worker.py')
        save(fixture/'case.json',{'mode':name,'raw':raw,'source':'SYNTHETIC_OFFLINE_NOT_ASTRA'})
        cmd=list(job.command);pos=cmd.index('--chdir')
        cmd[pos:pos]=['--ro-bind',str(fixture),'/test','--dir',str(Path.home()/'.codex')]
        cmd[cmd.index('/code/infer_worker.py')]='/test/endpoint_worker.py'
        cmd[cmd.index('--deadline')+1]=str(time.monotonic()+35)
        assert '--unshare-all' in cmd and '--share-net' not in cmd and not any('auth.json' in x for x in cmd)
        save(folder/'OFFLINE_COMMAND.json',cmd)
        start=time.monotonic()
        with (folder/'worker.stdout').open('wb') as out,(folder/'worker.stderr').open('wb') as err:
            proc=subprocess.run(cmd,env=job.env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,timeout=42)
        output=job.folder/'infer_output'
        record=read(output/'worker_record.json') if (output/'worker_record.json').exists() else None
        if record is not None:complete(b,job,record=record)
        endpoint=read(output/'ENDPOINT_AUDIT.json') if (output/'ENDPOINT_AUDIT.json').exists() else []
        argv=read(output/'effective_cli_argv.json') if (output/'effective_cli_argv.json').exists() else []
        settings=[argv[i+1] for i,x in enumerate(argv[:-1]) if x=='-c']
        for setting in ('model_provider="s1_openai_no_retry"','model_providers.s1_openai_no_retry.request_max_retries=0',
            'model_providers.s1_openai_no_retry.stream_max_retries=0','features.unbounded_connection_retries=false'):
            assert setting in settings,setting
        expect='READY' if name in ('e0','local_reground') or name.startswith('action_h') else 'FAILED'
        result={'case':name,'source':'SYNTHETIC_OFFLINE_NOT_ASTRA','expected':expect,
            'broker_status':row['status'],'broker_error':row.get('error'),'wall_s':time.monotonic()-start,
            'worker_return_code':proc.returncode,'local_posts':len(endpoint),'endpoint_validated':bool(endpoint) and all(x.get('validation')=='PASS' for x in endpoint),
            'usage_raw':row.get('usage_raw'),'schema_sha256':sha(payload['schema']),
            'authoritative_sha256':sha(payload['authoritative_schema']),
            'real_model_calls':0,'physics_calls':0,'hardware_calls':0,'actions_executed':0}
        result['pass']=row['status']==expect and len(endpoint)==1 and result['endpoint_validated'] and record is not None and row.get('usage_raw') is None
        save(folder/'RESULT.json',result);results.append(result);save(a.output/'RESULTS.json',results)
        print(json.dumps(result),flush=True)
        if not result['pass']:return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
