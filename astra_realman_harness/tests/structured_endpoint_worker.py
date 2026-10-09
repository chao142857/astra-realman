"""TEST ONLY, run inside --unshare-all. No real auth, external route or model.

The only transport substitution is test CA + loopback CONNECT proxy at the
bridge child environment boundary. Worker, bridge, CLI and provider argv stay
production code. Every actual POST schema is checked before any fixture reply.
"""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0,'/code')
from structured_outputs import check_provider, sha
import bridge

out=Path('/output');case=json.loads(Path('/test/case.json').read_text())
Path.home().joinpath('.codex').mkdir(parents=True,exist_ok=True)
assert not Path.home().joinpath('.codex/auth.json').exists()
assert not any(os.environ.get(k) for k in ('OPENAI_API_KEY','CODEX_API_KEY','AZURE_OPENAI_API_KEY'))
payload=json.loads(Path('/input/payload.json').read_text()); posts=[]; connects=[]

def unpack(raw, encoding):
    if encoding!='zstd':return raw
    z=ctypes.CDLL('libzstd.so.1');z.ZSTD_decompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t];z.ZSTD_decompress.restype=ctypes.c_size_t
    buf=ctypes.create_string_buffer(16*1024*1024);n=z.ZSTD_decompress(buf,len(buf),raw,len(raw))
    assert n<len(buf);return buf.raw[:n]

def nested_parts(v):
    if isinstance(v,dict):
        if v.get('type') in ('input_image','input_text'):yield v
        for x in v.values():yield from nested_parts(x)
    elif isinstance(v,list):
        for x in v:yield from nested_parts(x)

def event(t,**kw):return ('event: '+t+'\ndata: '+json.dumps({'type':t,**kw})+'\n\n').encode()

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def respond(self,status,body,ctype='application/json'):
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Connection','close');self.end_headers()
        self.wfile.write(body);self.close_connection=True
    def do_CONNECT(self):
        connects.append(self.path)
        self.send_response(200,'Connection established');self.end_headers();self.wfile.flush()
        self.connection=tls.wrap_socket(self.connection,server_side=True)
        self.rfile=self.connection.makefile('rb');self.wfile=self.connection.makefile('wb')
        self.close_connection=False;self.handle_one_request();self.close_connection=True
    def do_GET(self):self.respond(200,b'{"models":[]}')
    def do_POST(self):
        index=len(posts);record={'index':index,'path':self.path,'fixture_only':True}
        posts.append(record)
        try:
            raw=unpack(self.rfile.read(int(self.headers.get('Content-Length','0'))),self.headers.get('Content-Encoding'))
            (out/f'request-{index}.body.json').write_bytes(raw)
            body=json.loads(raw);schema=body['text']['format']['schema']
            audit=check_provider(schema)
            record.update(schema_sha256=sha(schema),schema_audit=audit)
            assert body['text']['format']['strict'] is True
            assert schema==payload['schema'],'ACTUAL_REQUEST_SCHEMA_MISMATCH'
            assert body['model']=='gpt-6-astra'
            assert body['reasoning']['effort']=='medium'
            parts=list(nested_parts(body['input']))
            images=[p['image_url'] for p in parts if p['type']=='input_image']
            record['image_hashes']=[hashlib.sha256(base64.b64decode(v.split(',',1)[1])).hexdigest() for v in images]
            assert record['image_hashes']==[a['sha256'] for a in payload['context']['attachments']]
            expected=json.dumps(payload['context'],ensure_ascii=False,allow_nan=False)
            text_parts=[p['text'] for p in parts if p['type']=='input_text']
            assert any(expected in t for t in text_parts),'FROZEN_PROMPT_NOT_PRESENT'
            record['prompt_sha256']=hashlib.sha256(expected.encode()).hexdigest()
            record['image_count']=len(images);record['validation']='PASS'
            if case['mode']=='http503':self.respond(503,b'{"error":{"message":"OFFLINE_503","type":"server_error"}}');return
            response={'id':'resp_OFFLINE_ONLY','object':'response','created_at':1,'status':'in_progress','model':'gpt-6-astra','output':[]}
            data=event('response.created',response=response)
            if case['mode']=='stream_truncated':self.respond(200,data,'text/event-stream');return
            raw_answer=case['raw']
            part={'type':'output_text','text':raw_answer,'annotations':[]}
            item={'id':'msg_OFFLINE_ONLY','type':'message','role':'assistant','status':'completed','content':[part]}
            data+=event('response.output_item.added',output_index=0,item={**item,'status':'in_progress','content':[]})
            data+=event('response.content_part.added',item_id=item['id'],output_index=0,content_index=0,part={**part,'text':''})
            data+=event('response.output_text.delta',item_id=item['id'],output_index=0,content_index=0,delta=raw_answer)
            data+=event('response.output_text.done',item_id=item['id'],output_index=0,content_index=0,text=raw_answer)
            data+=event('response.content_part.done',item_id=item['id'],output_index=0,content_index=0,part=part)
            data+=event('response.output_item.done',output_index=0,item=item)
            response.update(status='completed',output=[item])
            # Deliberately omit API usage to test unknown, never fabricate zero.
            data+=event('response.completed',response=response)
            self.respond(200,data,'text/event-stream')
        except Exception as exc:
            record.update(validation='FAIL',error=repr(exc))
            self.respond(400,json.dumps({'error':{'message':'OFFLINE_STRICT_SCHEMA_REJECTION:'+str(exc),'type':'invalid_request_error','code':'invalid_json_schema'}}).encode())
        finally:(out/'ENDPOINT_AUDIT.json').write_text(json.dumps(posts,indent=2))

tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain('/test/leaf.pem','/test/leaf-key.pem')
server=ThreadingHTTPServer(('127.0.0.1',18080),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
original=bridge.worker_environment
def offline_environment(executable,run):
    env=original(executable,run)
    env.update(HTTPS_PROXY='http://127.0.0.1:18080',HTTP_PROXY='http://127.0.0.1:18080',
        CODEX_CA_CERTIFICATE='/test/cert.pem',SSL_CERT_FILE='/test/cert.pem')
    return env
bridge.worker_environment=offline_environment
sys.argv=['/code/infer_worker.py',*sys.argv[1:]]
try:runpy.run_path('/code/infer_worker.py',run_name='__main__')
finally:
    server.shutdown()
    (out/'ENDPOINT_AUDIT.json').write_text(json.dumps(posts,indent=2))
    (out/'ISOLATION.json').write_text(json.dumps({'external_network':False,'real_credentials':False,
        'real_model_calls':0,'synthetic_response':True,'connects':connects,
        'network_interfaces':Path('/proc/net/dev').read_text(),'network_routes':Path('/proc/net/route').read_text()},indent=2))
