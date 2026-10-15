"""Two decisions through local fake HTTP bridge and real PhysX. Zero generation."""
import argparse,json,subprocess,sys,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from action_interface import SCHEMA,validate_context
from pilot02_runtime import bridge_module
p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();a.output.mkdir(exist_ok=False);requests=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));bridge_module().validate_payload(body)
  if self.path!='/decide' or self.headers.get('Authorization')!='Bearer mock-only-not-real-authentication':self.send_response(403);self.end_headers();return
  assert body['authoritative_schema']==SCHEMA
  requests.append(body)
  answer={'done':False,'execution':'parallel','actions':[{'arm':'right','kind':'gripper','pose_world_wxyz':None,'opening_fraction':1.}]} if len(requests)==1 else {'done':True,'execution':'sequential','actions':[]}
  root=Path('/offline/fake')/str(len(requests));events=[{'type':'thread.started','thread_id':'fake-independent-'+str(len(requests))},{'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]
  result={'raw':json.dumps(answer),'events':'\n'.join(map(json.dumps,events)),'stderr':'','error':None,'return_code':0,'command':bridge_module().command(root,[root/'input_only'/f'image-{i}.png' for i in range(4)])}
  self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
try:
 token=a.output/'fake_token.txt';token.write_text('mock-only-not-real-authentication');config=a.output/'fake_config.json';config.write_text(json.dumps({'endpoint':'http://127.0.0.1:'+str(server.server_port),'token_file':str(token.resolve())}))
 proc=subprocess.run([sys.executable,'run_episode.py','--output',str(a.output/'episode'),'--mock-bridge-config',str(config),'--max-decisions','2'],capture_output=True,text=True)
 (a.output/'stdout.log').write_text(proc.stdout);(a.output/'stderr.log').write_text(proc.stderr)
 episode=json.loads((a.output/'episode/episode.json').read_text());assert episode['status']=='MODEL_STOP_REQUEST_NOT_SUCCESS' and episode['decisions']==2
 assert len(requests)==2 and requests[0]['context']['recent_history']==[] and len(requests[1]['context']['recent_history'])==1
 report={'status':'PASS','real_model_calls':0,'fake_requests':len(requests),'physics_executed':True,'handoff_success_claim':False,'episode':episode}
 (a.output/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
finally:server.shutdown();server.server_close();t.join()
