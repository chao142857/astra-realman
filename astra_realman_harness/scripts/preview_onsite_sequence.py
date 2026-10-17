#!/usr/bin/env python3
"""Loopback preview of a recorder's saved images. No camera/SDK/model imports."""
import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROLES = ('wrist', 'fixed', 'assembly')
PAGE = '''<!doctype html><meta charset="utf-8"><title>Calibration recorder preview</title>
<style>body{font:18px sans-serif;background:#171b20;color:#eee;margin:24px}main{display:flex;flex-wrap:wrap;gap:16px}figure{margin:0}img{width:640px;max-width:95vw}figcaption{margin:10px 0}#status{padding:12px;background:#273238}</style>
<h2>标定记录 · 只读画面</h2><p>复用记录器最新保存的图片；不另开相机，不提供执行按钮。显示时间为文件保存时间，非曝光时间。</p>
<p id="status">等待图片…</p><main id="views"></main>
<script>
const labels={wrist:'左腕',fixed:'桌面',assembly:'上方'};
const cards={};
for(const role of Object.keys(labels)){const f=document.createElement('figure'),cap=document.createElement('figcaption'),im=document.createElement('img');cap.textContent=labels[role];f.append(cap,im);document.getElementById('views').append(f);cards[role]={cap,im};}
let current=null;
async function refresh(){try{
 const r=await fetch('/latest.json',{cache:'no-store'});if(!r.ok)throw Error('尚无完整观测');const d=await r.json();
 const stop=d.stop_reason?(' · 记录已结束：'+d.stop_reason):(d.age_s>3?' · 新画面延迟，记录状态尚未确认':' · 正在更新');
 document.getElementById('status').textContent='观测 '+d.index+' | 保存于 '+new Date(d.saved_at*1000).toLocaleTimeString()+' | '+d.age_s.toFixed(1)+' 秒前'+stop;
 if(current!==d.index){await Promise.all(Object.keys(labels).map(async role=>{
 const url='/image/'+d.index+'/'+role+'.png',buffer=new Image();buffer.src=url;await buffer.decode();
 cards[role].im.src=url;cards[role].cap.textContent=labels[role]+' | '+(d.corners[role]?.status||'角点检测尚未写入');}));current=d.index;}
 }catch(e){document.getElementById('status').textContent=String(e);}finally{setTimeout(refresh,100);}}
refresh();</script>'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sequence', required=True, type=Path)
    parser.add_argument('--arm', choices=['left','right'], default='left')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    root = args.sequence.resolve()
    observations = root / 'observations'
    if not observations.is_dir():
        parser.error('sequence observations directory does not exist')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/':
                body, kind = PAGE.replace("wrist:'左腕'", "wrist:'右腕'" if args.arm=='right' else "wrist:'左腕'").encode(), 'text/html; charset=utf-8'
            elif path == '/latest.json':
                latest = None
                for folder in sorted(observations.iterdir(), reverse=True):
                    if not re.fullmatch(r'\d{6}', folder.name):
                        continue
                    state = folder / 'observation.json'
                    try:
                        json.loads(state.read_text())
                        if not all((folder / (role + '.png')).is_file() for role in ROLES):
                            continue
                        stamp = state.stat().st_mtime
                        corners = json.loads((folder / 'board_corners.json').read_text())
                        latest = {'index': folder.name, 'saved_at': stamp,
                                  'age_s': max(0, time.time() - stamp), 'corners': corners}
                        summary = root / 'summary.json'
                        if summary.exists():
                            try:
                                latest['stop_reason'] = json.loads(summary.read_text())['stop_reason']
                            except (OSError, ValueError, KeyError):
                                pass
                        error = json.loads(state.read_text()).get('state', {}).get('canonical_states', {}).get(args.arm, {}).get('system_error')
                        latest['robot_error'] = error
                        break
                    except (OSError, ValueError):
                        continue
                if latest is None:
                    self.send_error(503, 'No complete observation'); return
                body, kind = json.dumps(latest).encode(), 'application/json'
            else:
                match = re.fullmatch(r'/image/(\d{6})/(wrist|fixed|assembly)\.png', path)
                if not match:
                    self.send_error(404); return
                image = observations / match[1] / (match[2] + '.png')
                if not image.resolve().is_relative_to(root):
                    self.send_error(403); return
                try:
                    body = image.read_bytes()
                except OSError:
                    self.send_error(404); return
                kind = 'image/png'
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    print('READ_ONLY_PREVIEW http://127.0.0.1:%d | %s' % (args.port, root), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
