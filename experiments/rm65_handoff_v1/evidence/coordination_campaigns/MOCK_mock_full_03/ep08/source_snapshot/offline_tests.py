import copy,json,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from action_interface import *
from pilot02_runtime import bridge_module
D=Path(__file__).resolve().parent
STOP={'done':True,'execution':'sequential','actions':[]}
class Protocol(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.token=self.root/'token';self.token.write_text('offline-synthetic-token-only')
  folder=D/'evidence/numeric_baseline_01/initial_observation';obs=json.loads((folder/'observation.json').read_text());obs['images']=[str(folder/(name+'.png')) for name in ('overhead','tabletop_front','left_wrist','right_wrist')];self.obs=obs;self.context,self.images=context_from_observation(obs,[])
  self.mode='ok';test=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
    if self.path=='/cancel':self.send_response(200);self.end_headers();self.wfile.write(b'{}');return
    if self.headers.get('Authorization')!='Bearer offline-synthetic-token-only':self.send_response(403);self.end_headers();return
    if test.mode in ['403','409']:self.send_response(int(test.mode));self.end_headers();return
    bridge_module().validate_payload(body);test.assertEqual(body['context'],test.context)
    events=[{'type':'thread.started','thread_id':'offline-independent'}, {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]
    if test.mode=='incomplete':events.pop()
    if test.mode=='reconnect':events.insert(1,{'type':'error','message':'reconnecting'})
    raw=json.dumps(STOP) if test.mode!='bad_json' else '{bad'
    command=bridge_module().command(Path('/fake/run'),[Path('/fake/run/input_only')/f'image-{i}.png' for i in range(4)])
    if test.mode=='drift':command[command.index('--model')+1]='wrong-model'
    response={'raw':raw,'events':'\n'.join(map(json.dumps,events)),'stderr':'','return_code':0,'error':None,'command':command}
    self.send_response(200);self.end_headers();self.wfile.write(json.dumps(response).encode())
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.config=MacBridgeConfig('http://127.0.0.1:'+str(self.server.server_port),self.token)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def infer(self):
  f=self.root/'run';r=HandoffBridgeAdapter(self.config).infer(self.context,self.images,f);self.assertEqual(r['model_calls'],0);return f
 def test_success(self):self.assertEqual(accept_result(self.infer()),STOP)
 def test_protocol_failures(self):
  for mode in ['bad_json','incomplete','reconnect','drift','403','409']:
   with self.subTest(mode=mode):
    self.mode=mode;f=self.root/('run_'+mode);HandoffBridgeAdapter(self.config).infer(self.context,self.images,f)
    with self.assertRaises((ValueError,FileNotFoundError)):accept_result(f)
 def test_auth_failure(self):
  self.token.write_text('wrong-synthetic-token-only');r=HandoffBridgeAdapter(self.config).infer(self.context,self.images,self.root/'bad_auth');self.assertEqual(r['error'],'MAC_BRIDGE_HTTP_403')
 def test_no_real_dispatch(self):
  with self.assertRaises(ValueError):HandoffBridgeAdapter(self.config,offline_test=False)
  with self.assertRaises(ValueError):HandoffBridgeAdapter(self.config).infer(self.context,self.images,self.root/'forbidden',real=True)
 def test_gt_and_image_rejected(self):
  c=copy.deepcopy(self.context);c['observations']['oracle']={}
  with self.assertRaises(ValueError):validate_context(c,self.images)
  c=copy.deepcopy(self.context);c['attachments'][0]['sha256']='x'
  with self.assertRaises(ValueError):validate_context(c,self.images)
 def test_action_validation(self):
  for raw in ['{"done":true,"done":false}',json.dumps(dict(STOP,unexpected=True)),json.dumps({'done':False,'execution':'parallel','actions':[]})]:
   with self.assertRaises((ValueError,jsonschema.ValidationError)):parse_action(raw)
  a={'arm':'left','kind':'tcp','pose_world_wxyz':[.3,0,.2,0,2,0,0],'opening_fraction':None}
  with self.assertRaises(ValueError):parse_action(json.dumps({'done':False,'execution':'parallel','actions':[a]}))
 def test_timeout_cancel_no_retry(self):
  adapter=HandoffBridgeAdapter(self.config);calls=[]
  def post(path,*args):
   calls.append(path)
   if path=='/decide':raise TimeoutError('offline')
   return 200,b'{}'
  adapter._post=post;r=adapter.infer(self.context,self.images,self.root/'timeout')
  self.assertEqual(calls,['/decide','/cancel']);self.assertEqual(r['error'],'MAC_BRIDGE_TIMEOUT_COMPLETION_UNKNOWN')
if __name__=='__main__':unittest.main(verbosity=2)
