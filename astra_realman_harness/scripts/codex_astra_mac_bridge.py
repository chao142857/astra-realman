#!/usr/bin/env python3
"""Run on Mac. Loopback-only model service plus SSH reverse tunnel; no robot SDK."""
import argparse, base64, hashlib, hmac, json, os, shutil, signal, subprocess, threading, time, uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
try:
    from scripts.structured_outputs import compile_schema, encoded, validate_local
except ModuleNotFoundError:
    from structured_outputs import compile_schema, encoded, validate_local

DISABLED=('shell_tool unified_exec code_mode code_mode_host code_mode_only multi_agent multi_agent_v2 apps plugins hooks remote_plugin shell_snapshot browser_use browser_use_external computer_use in_app_browser image_generation view_image workspace_dependencies skill_search skill_mcp_dependency_install memories goals realtime_conversation daemon_auto_start').split()
ROOT='/home/tongji/alex/astra_realman_harness'
JOBS={};MUTEX=threading.Lock();BUSY=threading.Lock()
ENV_ALLOWLIST=('HOME','USER','LOGNAME','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR')
SYSTEM_PATH=('/usr/bin','/bin')

def worker_environment(executable,run):
    """Keep the configured launcher directory ahead of its symlink target directory."""
    launcher=Path(executable).expanduser().absolute()
    env={k:v for k,v in os.environ.items() if k in ENV_ALLOWLIST}
    paths=dict.fromkeys((str(launcher.parent),str(launcher.resolve().parent),*SYSTEM_PATH))
    env.update(PATH=os.pathsep.join(paths),TMPDIR=str(run/'runtime'))
    return env

def worker_paths(executable,run,env):
    launcher=Path(executable).expanduser().absolute()
    node=shutil.which('node',path=env['PATH'])
    return {'launcher':str(launcher),'resolved_script':str(launcher.resolve()),
            'node':node,'resolved_node':str(Path(node).resolve()) if node else None,
            'cwd':str(run/'input_only'),'PATH':env['PATH'],'TMPDIR':env['TMPDIR'],
            'environment_keys':sorted(env)}

def preflight(executable,output,*,timeout_s=15):
    """Version/help only, with the same isolated environment and cwd layout as infer."""
    run=Path(output).resolve()
    run.mkdir(parents=True,exist_ok=False)
    (run/'runtime').mkdir();(run/'input_only').mkdir()
    env=worker_environment(executable,run)
    report={'status':'INCOMPLETE','model_calls':0,'paths':worker_paths(executable,run,env),'probes':[]}
    try:
        node=report['paths']['node']
        if node is None:raise RuntimeError('NODE_NOT_FOUND_IN_WORKER_PATH')
        launcher=report['paths']['launcher']
        for name,cmd in (('node_version',[node,'--version']),
                         ('codex_version',[launcher,'--version']),
                         ('codex_exec_help',[launcher,'exec','--help'])):
            record={'name':name,'command':cmd}
            report['probes'].append(record)
            start=time.monotonic()
            try:
                probe=subprocess.run(cmd,stdin=subprocess.DEVNULL,capture_output=True,text=True,
                                     env=env,cwd=run/'input_only',timeout=timeout_s)
                record.update(return_code=probe.returncode,stdout=probe.stdout,stderr=probe.stderr)
                if probe.returncode!=0 or not probe.stdout.strip():
                    raise RuntimeError('CLI_PREFLIGHT_PROBE_FAILED:'+name)
            finally:record['latency_s']=time.monotonic()-start
        report['status']='PASS'
    except Exception as exc:
        report.update(status='FAIL',error=type(exc).__name__+':'+str(exc))
    (run/'preflight.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def command(run,images,executable='/opt/homebrew/bin/codex'):
    cmd=[str(executable),'exec','--ignore-user-config','--ignore-rules','--sandbox','read-only',
         '--ephemeral','--skip-git-repo-check','--cd',str(run/'input_only'),'--color','never','--json',
         '--model','gpt-6-astra','--output-schema',str(run/'schema.json'),'--output-last-message',str(run/'last_message.json')]
    config={'approval_policy':'never','web_search':'disabled','project_doc_max_bytes':0,
            'shell_environment_policy.inherit':'none','history.persistence':'none','log_dir':str(run/'runtime'),
            'sqlite_home':str(run/'runtime'),'model_reasoning_effort':'medium','mcp_servers':{},
            'features.skip_host_skill_discovery':True,'analytics.enabled':False,'feedback.enabled':False,
            'model_provider':'openai'}
    for k,v in config.items():cmd+=['-c',k+'='+('{}' if v=={} else json.dumps(v))]
    for f in DISABLED:cmd+=['--disable',f]
    for p in images:cmd+=['--image',str(p)]
    return cmd+['-']

def infer(payload,stop,*,executable='/opt/homebrew/bin/codex',run_root='/private/tmp/codex-astra-bridge',timeout_s=120):
    if stop.is_set():raise RuntimeError('CANCELLED_BEFORE_REQUEST')
    run=Path(run_root).resolve()/uuid.uuid4().hex
    run.mkdir(parents=True);(run/'runtime').mkdir();(run/'input_only').mkdir()
    (run/'input_only'/'context.json').write_text(json.dumps(payload['context'],ensure_ascii=False,allow_nan=False))
    (run/'prompt.json').write_text(json.dumps(payload['context'],ensure_ascii=False,allow_nan=False))
    authoritative = payload.get('authoritative_schema', payload['schema'])
    schema, audit = compile_schema(authoritative)
    if 'authoritative_schema' in payload and schema != payload['schema']:
        raise ValueError('PROVIDER_SCHEMA_MISMATCH_NO_DISPATCH')
    (run/'schema.json').write_bytes(encoded(schema))
    (run/'authoritative_schema.json').write_bytes(encoded(authoritative))
    (run/'schema_audit.json').write_text(json.dumps(audit,indent=2))
    blobs=payload['images']
    if not 1<=len(blobs)<=4:raise ValueError('IMAGE_COUNT')
    images=[]
    for i,b in enumerate(blobs):
        data=base64.b64decode(b,validate=True)
        if len(data)>8*1024*1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('IMAGE_INVALID')
        p=run/'input_only'/('image-%d.png'%i);p.write_bytes(data);images.append(p)
    (run/'attachments.json').write_text(json.dumps([{'index':i+1,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for i,p in enumerate(images)]))
    cmd=command(run,images,executable);(run/'command.json').write_text(json.dumps(cmd))
    env=worker_environment(executable,run)
    (run/'environment.json').write_text(json.dumps(worker_paths(executable,run,env),indent=2)+'\n')
    start=time.monotonic();proc=None;error=None
    try:
        with (run/'prompt.json').open() as inp,(run/'events.jsonl').open('w') as out,(run/'stderr.log').open('w') as err:
            proc=subprocess.Popen(cmd,stdin=inp,stdout=out,stderr=err,env=env,cwd=run/'input_only')
            while proc.poll() is None:
                if stop.wait(.1):raise RuntimeError('CANCELLED')
                if time.monotonic()-start>timeout_s:raise TimeoutError('MODEL_TIMEOUT')
            if stop.is_set():raise RuntimeError('CANCELLED_AFTER_RESPONSE')
    except Exception as exc:error=type(exc).__name__+':'+str(exc)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    def read(n):
        p=run/n
        if p.exists() and p.stat().st_size<=2*1024*1024:return p.read_text()
        return ''
    result={'raw':read('last_message.json'),'events':read('events.jsonl'),'stderr':read('stderr.log'),
            'return_code':proc.returncode if proc else None,'error':error,'command':cmd,
            'latency_s':time.monotonic()-start,'local_log':str(run),'mac_home':str(Path.home())}
    if result['return_code'] == 0 and result['error'] is None:
        try:
            def pairs(items):
                out={}
                for key,value in items:
                    if key in out: raise ValueError('DUPLICATE_JSON_KEY:'+key)
                    out[key]=value
                return out
            answer=json.loads(result['raw'],object_pairs_hook=pairs,
                parse_constant=lambda x: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
            validate_local(answer,authoritative,schema)
        except Exception as exc: result['error']='LOCAL_OUTPUT_VALIDATION:'+type(exc).__name__+':'+str(exc)
    (run/'result.json').write_text(json.dumps(result));return result

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token):
            self.send_error(403);return
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<=48*1024*1024:self.send_error(413);return
        payload=json.loads(self.rfile.read(size));rid=payload.get('request_id')
        if not isinstance(rid,str) or len(rid)!=32:self.send_error(400);return
        if self.path=='/cancel':
            with MUTEX:
                if rid in JOBS:JOBS[rid].set()
            response={'cancelled':True}
        elif self.path=='/decide':
            if not BUSY.acquire(False):self.send_error(409);return
            stop=threading.Event()
            with MUTEX:JOBS[rid]=stop
            try:response=infer(payload,stop,**getattr(self.server,'inference_options',{}))
            except Exception as exc:response={'error':type(exc).__name__+':'+str(exc),'return_code':None}
            finally:
                with MUTEX:JOBS.pop(rid,None)
                BUSY.release()
        else:self.send_error(404);return
        data=json.dumps(response).encode();self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)));self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('lab','local'),default='lab')
    p.add_argument('--executable',default='/opt/homebrew/bin/codex')
    p.add_argument('--run-root',type=Path,default=Path('/private/tmp/codex-astra-bridge'))
    p.add_argument('--port',type=int,default=18767)
    p.add_argument('--token-file',type=Path)
    p.add_argument('--timeout-s',type=float,default=120)
    a=p.parse_args()
    # No credentials copied: auth stays in the Mac's existing CODEX_HOME.
    if a.mode=='local' and a.token_file is None:p.error('--token-file is required for local mode')
    token=(a.token_file.read_text().strip() if a.token_file else
           subprocess.check_output(['ssh','yanglab','cat '+ROOT+'/config/codex_astra_bridge.token'],text=True).strip())
    if len(token)<16:raise ValueError('BRIDGE_TOKEN_TOO_SHORT')
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);server.token=token
    server.inference_options={'executable':a.executable,'run_root':a.run_root,'timeout_s':a.timeout_s}
    tunnel=(subprocess.Popen(['ssh','-N','-T','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15',
                             '-o','ServerAliveCountMax=2','-R',f'127.0.0.1:18766:127.0.0.1:{a.port}','yanglab'])
            if a.mode=='lab' else None)
    stop=threading.Event()
    def halt(*args):stop.set()
    signal.signal(signal.SIGINT,halt);signal.signal(signal.SIGTERM,halt)
    server.timeout=.5
    print('CodexAstraBackend bridge ready | official ChatGPT | gpt-6-astra | no robot control',flush=True)
    try:
        while not stop.is_set():
            if tunnel is not None and tunnel.poll() is not None:raise RuntimeError('SSH_TUNNEL_EXITED')
            server.handle_request()
    finally:
        with MUTEX:
            for event in JOBS.values():event.set()
        server.server_close()
        if tunnel is not None:
            tunnel.terminate()
            try:tunnel.wait(timeout=3)
            except subprocess.TimeoutExpired:tunnel.kill();tunnel.wait()

if __name__=='__main__':main()
