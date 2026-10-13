"""Offline original HTTP Handler, with infer replaced BEFORE listening. No CLI."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import uuid
from pilot02_runtime import bridge_module, MacBridgeConfig

@contextmanager
def mock_bridge(root):
    bridge=bridge_module();state={'mode':'success','raw':'{}','decide_calls':0,'cancel_calls':0,'stub_calls':0,'payloads':[]}
    def stub(payload,stop,**unused):
        bridge.validate_payload(payload);state['stub_calls']+=1;state['payloads'].append(payload)
        mode=state['mode']
        if mode=='timeout':
            stop.wait(3)
            return dict(raw='',events='',stderr='',return_code=1,error='FIXTURE_CANCELLED')
        raw='{' if mode=='invalid_json' else '' if mode=='empty' else state['raw']
        command=bridge.command(Path('/offline-pilot02'),[Path('/offline-pilot02/input_only')/f'image-{i}.png' for i in range(3)])
        if mode=='parameter_drift':command[command.index('--model')+1]='FIXTURE_FORBIDDEN_MODEL'
        if mode=='code_mode_drift':command.remove('code_mode')
        events=[{'type':'thread.started','thread_id':state.get('fixed_thread_id',uuid.uuid4().hex)}, {'type':'turn.started'}]
        complete={'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':5,'output_tokens_details':{'reasoning_tokens':2}}}
        if mode!='no_completed':events.append(complete)
        if mode=='duplicate_completed':events.append(complete)
        if mode=='failed_event':events.append({'type':'turn.failed'})
        return dict(raw=raw,events='\n'.join(json.dumps(x) for x in events),stderr='',
                    return_code=1 if mode=='return_error' else 0,error='FIXTURE_ERROR' if mode=='transport_error' else None,
                    command=command,local_log='OFFLINE_FIXTURE_ONLY',latency_s=0)
    bridge.infer=stub
    class Handler(bridge.Handler):
        def do_POST(self):
            if self.path=='/decide':state['decide_calls']+=1
            if self.path=='/cancel':state['cancel_calls']+=1
            super().do_POST()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    token=Path(root)/'offline-fixture.token';token.write_text('OFFLINE_FIXTURE_NOT_A_REAL_CREDENTIAL');server.token=token.read_text()
    state.update(config=MacBridgeConfig(f'http://127.0.0.1:{server.server_port}',token),busy=bridge.BUSY)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield state
    finally:
        with bridge.MUTEX:
            for stop in bridge.JOBS.values():stop.set()
        server.shutdown();server.server_close();worker.join(timeout=2)
