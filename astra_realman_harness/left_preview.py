"""Loopback, read-only three-view preview; never accepts actuator requests."""
import html, io, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

class Preview:
    def __init__(self, configs, port=8765, session=None, mode="DRY_RUN_ONLY"):
        self.configs=configs;self.session=session;self.images={};self.lock=threading.Lock()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                path=urlparse(self.path).path
                if path=='/':
                    cards=''.join('<figure><figcaption>'+html.escape(c['role']+' | '+c['serial'])+'</figcaption><img width="480" data-url="/view/'+str(i)+'"></figure>' for i,c in enumerate(configs))
                    body=('<!doctype html><meta charset="utf-8"><title>Left dry-run cameras</title><h2>READ ONLY CAMERA VIEW</h2><p>MODE: ' + html.escape(mode) + '</p><p>Live preview when connected; archive replay otherwise. No actuator controls.</p>'+cards+'<script>setInterval(()=>document.querySelectorAll("img").forEach(x=>{x.src=x.dataset.url+"?t="+Date.now()}),500)</script>').encode()
                    kind='text/html; charset=utf-8'
                elif path in ['/view/'+str(i) for i in range(3)]:
                    i=int(path.rsplit('/',1)[1]); serial=configs[i]['serial']
                    try:
                        if owner.session:
                            from PIL import Image
                            with owner.session.condition:
                                item=dict(owner.session.latest[serial])
                                if serial in owner.session.errors:raise ValueError('camera error')
                            if time.monotonic()-item['host_received_monotonic']>1:raise ValueError('stale frame')
                            h,w,_=item['shape'];image=Image.frombytes('RGB',(w,h),item['_pixels'],'raw','RGB',item['_stride'])
                            output=io.BytesIO();image.save(output,format='JPEG');body=output.getvalue();kind='image/jpeg'
                        else:
                            with owner.lock:body=owner.images[serial]
                            kind='image/png'
                    except Exception:
                        self.send_error(503,'frame unavailable');return
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def update(self, observation):
        from pathlib import Path
        with self.lock:self.images={c['serial']:Path(c['image_path']).read_bytes() for c in observation['cameras']}
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
