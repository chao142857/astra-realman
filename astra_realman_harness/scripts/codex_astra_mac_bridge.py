#!/usr/bin/env python3
"""Run on Mac. Loopback-only model service plus SSH reverse tunnel; no robot SDK."""
import base64, hmac, json, os, signal, subprocess, threading, time, uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DISABLED=('shell_tool unified_exec code_mode code_mode_host code_mode_only multi_agent multi_agent_v2 apps plugins hooks remote_plugin shell_snapshot browser_use browser_use_external computer_use in_app_browser image_generation view_image workspace_dependencies skill_search skill_mcp_dependency_install memories goals realtime_conversation daemon_auto_start').split()
ROOT='/home/tongji/alex/astra_realman_harness'
JOBS={};MUTEX=threading.Lock();BUSY=threading.Lock()

def command(run,images):
    cmd=['/opt/homebrew/bin/codex','exec','--ignore-user-config','--ignore-rules','--sandbox','read-only',
         '--ephemeral','--skip-git-repo-check','--cd',str(run/'input_only'),'--color','never','--json',
         '--model','gpt-6-astra','--output-schema',str(run/'schema.json'),'--output-last-message',str(run/'last_message.json')]
    config={'approval_policy':'never','web_search':'disabled','project_doc_max_bytes':0,
            'shell_environment_policy.inherit':'none','history.persistence':'none','log_dir':str(run/'runtime'),
            'sqlite_home':str(run/'runtime'),'model_reasoning_effort':'low','mcp_servers':{},
            'features.skip_host_skill_discovery':True,'analytics.enabled':False,'feedback.enabled':False,
            'model_provider':'openai'}
    for k,v in config.items():cmd+=['-c',k+'='+('{}' if v=={} else json.dumps(v))]
    for f in DISABLED:cmd+=['--disable',f]
    for p in images:cmd+=['--image',str(p)]
    return cmd+['-']

def infer(payload,stop):
    run=Path('/private/tmp/codex-astra-bridge')/uuid.uuid4().hex
    run.mkdir(parents=True);(run/'runtime').mkdir();(run/'input_only').mkdir()
    (run/'prompt.json').write_text(json.dumps(payload['context'],ensure_ascii=False,allow_nan=False))
    (run/'schema.json').write_text(json.dumps(payload['schema'],allow_nan=False))
    blobs=payload['images']
    if not 1<=len(blobs)<=4:raise ValueError('IMAGE_COUNT')
    images=[]
    for i,b in enumerate(blobs):
        data=base64.b64decode(b,validate=True)
        if len(data)>8*1024*1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('IMAGE_INVALID')
        p=run/('image-%d.png'%i);p.write_bytes(data);images.append(p)
    cmd=command(run,images);(run/'command.json').write_text(json.dumps(cmd))
    env={k:v for k,v in os.environ.items() if k in ('HOME','USER','LOGNAME','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR')}
    env.update(PATH='/opt/homebrew/bin:/usr/bin:/bin',TMPDIR=str(run/'runtime'))
    start=time.monotonic();proc=None;error=None
    try:
        with (run/'prompt.json').open() as inp,(run/'events.jsonl').open('w') as out,(run/'stderr.log').open('w') as err:
            proc=subprocess.Popen(cmd,stdin=inp,stdout=out,stderr=err,env=env,cwd=run/'input_only')
            while proc.poll() is None:
                if stop.wait(.1):raise RuntimeError('CANCELLED')
                if time.monotonic()-start>120:raise TimeoutError('MODEL_TIMEOUT')
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
            try:response=infer(payload,stop)
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
    # No credentials copied: auth stays in the Mac's existing CODEX_HOME.
    token=subprocess.check_output(['ssh','yanglab','cat '+ROOT+'/config/codex_astra_bridge.token'],text=True).strip()
    server=ThreadingHTTPServer(('127.0.0.1',18767),Handler);server.token=token
    tunnel=subprocess.Popen(['ssh','-N','-T','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15',
                             '-o','ServerAliveCountMax=2','-R','127.0.0.1:18766:127.0.0.1:18767','yanglab'])
    stop=threading.Event()
    def halt(*args):stop.set()
    signal.signal(signal.SIGINT,halt);signal.signal(signal.SIGTERM,halt)
    server.timeout=.5
    print('CodexAstraBackend bridge ready | official ChatGPT | gpt-6-astra | no robot control',flush=True)
    try:
        while not stop.is_set():
            if tunnel.poll() is not None:raise RuntimeError('SSH_TUNNEL_EXITED')
            server.handle_request()
    finally:
        with MUTEX:
            for event in JOBS.values():event.set()
        server.server_close();tunnel.terminate()
        try:tunnel.wait(timeout=3)
        except subprocess.TimeoutExpired:tunnel.kill();tunnel.wait()

if __name__=='__main__':main()
