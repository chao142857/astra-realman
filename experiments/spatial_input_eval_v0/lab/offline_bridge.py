"""Ephemeral test server using the unchanged production HTTP Handler, never its infer.

Each fixture gets an isolated module with a stub assigned BEFORE serving. Its stub
validates generic payload/schema and emits the V0 smoke prediction without GT.
No token or Authorization header is recorded. Production ports are prohibited.
"""
from contextlib import contextmanager
import hashlib
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import threading
import uuid

from spatial_eval.adapter import HARNESS, mock_raw
from spatial_eval.mac_bridge import MacBridgeAdapter, MacBridgeConfig


@contextmanager
def fake_bridge(temp):
    if str(HARNESS) not in sys.path:sys.path.insert(0,str(HARNESS))
    spec=importlib.util.spec_from_file_location('offline_bridge_'+uuid.uuid4().hex,
                                              HARNESS/'scripts/codex_astra_mac_bridge.py')
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    state={'mode':'success','decide_calls':0,'cancel_calls':0,'stub_calls':0,'payloads':[],
           'real_model_calls':0,'original_infer_never_called':True}
    def stub(payload,stop,**unused):
        state['stub_calls']+=1
        schema,audit,decoded=bridge.validate_payload(payload)
        state['payloads'].append(payload)
        mode=state['mode']
        if mode=='timeout':
            if not stop.wait(5):raise RuntimeError('FIXTURE_CANCEL_NOT_RECEIVED')
            return {'raw':'','events':'','stderr':'','return_code':1,'error':'FIXTURE_CANCELLED'}
        raw=mock_raw(payload['context']) if mode!='invalid-output' else 'not JSON'
        cmd=bridge.command(Path('/offline-fixture'),[Path('/offline-fixture')/f'image-{i}.png' for i in range(3)])
        if mode=='parameter-drift':cmd[cmd.index('--model')+1]='forbidden-fixture-model'
        error=None
        try:bridge.validate_local(json.loads(raw),payload['authoritative_schema'],schema)
        except Exception as exc:error='LOCAL_OUTPUT_VALIDATION:'+type(exc).__name__
        return {'raw':raw,'events':'','stderr':'','return_code':0,'error':error,'command':cmd,
                'local_log':'OFFLINE_FIXTURE_NO_MODEL','latency_s':0}
    bridge.infer=stub
    class Handler(bridge.Handler):
        def do_POST(self):
            if self.path=='/decide':state['decide_calls']+=1
            if self.path=='/cancel':state['cancel_calls']+=1
            if state['mode']=='malformed-response' and self.path=='/decide':
                size=int(self.headers['Content-Length']);self.rfile.read(size)
                data=b'{"raw":1,"return_code":0}'
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            elif state['mode']=='trickle' and self.path=='/decide':
                size=int(self.headers['Content-Length']);self.rfile.read(size)
                self.send_response(200);self.send_header('Content-Length','100');self.end_headers()
                import time
                try:
                    for _ in range(100):self.wfile.write(b' ');self.wfile.flush();time.sleep(.05)
                except (BrokenPipeError,ConnectionResetError):pass
            else:super().do_POST()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    assert server.server_port not in (18766,18767)
    token=secrets.token_hex(32);token_path=Path(temp)/'fixture.token';token_path.write_text(token);token_path.chmod(0o600)
    server.token=token
    config=MacBridgeConfig('http://127.0.0.1:'+str(server.server_port),token_path)
    adapter=MacBridgeAdapter(config,offline_test=True)
    state.update(adapter=adapter,config=config,busy_lock=bridge.BUSY,token_file=token_path)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield state
    finally:
        with bridge.MUTEX:
            for event in bridge.JOBS.values():event.set()
        server.shutdown();server.server_close();thread.join(timeout=2)


def audit(state):
    return {k:state[k] for k in ('decide_calls','cancel_calls','stub_calls','real_model_calls','original_infer_never_called')}
