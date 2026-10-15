"""Local fake HTTP + actual paused PhysX; no production endpoint, zero generation."""
import argparse
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from action_interface import SCHEMA,TRANSFER_INSTRUCTION,validate_context
from pilot02_runtime import bridge_module

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False);requests=[];mode='shadow'

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        assert self.path=='/decide'
        assert self.headers.get('Authorization')=='Bearer offline-transfer-fixture-token'
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        bridge_module().validate_payload(body)
        assert body['context']['instruction']==TRANSFER_INSTRUCTION and body['authoritative_schema']==SCHEMA
        requests.append(body);n=len(requests)
        tcp=body['context']['observations']['arms']['right']['actual_grasp_center_world'].copy();tcp[2]+=.005
        q=body['context']['observations']['arms']['right']['flange_pose_world'][3:]
        pose=[1.5,0,.2,1,0,0,0] if n==1 else tcp+q
        answer={'done':False,'execution':'sequential','actions':[{'arm':'right','kind':'tcp','pose_world_wxyz':pose,'opening_fraction':None}]}
        if mode=='execute' and n==3:answer={'done':True,'execution':'sequential','actions':[]}
        events=[{'type':'thread.started','thread_id':'fixture-transfer-'+str(n)},
                {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]
        run=Path('/offline/fake')/str(n)
        result={'raw':json.dumps(answer),'events':'\n'.join(map(json.dumps,events)),
                'stderr':'','error':None,'return_code':0,
                'command':bridge_module().command(run,[run/'input_only'/f'image-{i}.png' for i in range(4)])}
        self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    token=a.output/'fixture_token.txt';token.write_text('offline-transfer-fixture-token')
    config=a.output/'fixture_config.json';config.write_text(json.dumps({'endpoint':'http://127.0.0.1:'+str(server.server_port),'token_file':str(token.resolve())}))
    report={'real_generation_requests':0,'production_connections':0,'scope':'Fake proposals test transport/executor, never Astra capability.'}
    for mode in ('shadow','execute'):
        requests.clear();out=a.output/mode
        proc=subprocess.run([sys.executable,str(Path(__file__).with_name('run_episode.py')),
            '--task','handoff_transfer_only','--output',str(out),'--mock-bridge-config',str(config),
            '--mode',mode,'--max-decisions','3'],capture_output=True,text=True)
        (a.output/(mode+'_stdout.log')).write_text(proc.stdout);(a.output/(mode+'_stderr.log')).write_text(proc.stderr)
        episode=json.loads((out/'episode.json').read_text())
        assert episode['status']==('SHADOW_VALID_NO_EXECUTION' if mode=='shadow' else 'MODEL_STOP_REQUEST_NOT_AUTOMATIC_SUCCESS'),episode
        assert len(requests)==(1 if mode=='shadow' else 3)
        for d in sorted(out.glob('decision_*')):
            timing=json.loads((d/'timing.json').read_text());assert timing['inference_physics_steps']==0
        first=json.loads((out/'decision_000/receipt.json').read_text())
        assert not first['executed']
        if mode=='execute':
            proposal=json.loads((out/'decision_000/proposal.json').read_text());assert proposal['actions'][0]['pose_world_wxyz'][0]==1.5
            assert 'TCP_WORKSPACE' in json.dumps(first)
            second=json.loads((out/'decision_001/receipt.json').read_text());assert second['ok'] and second['executed'],second
            assert requests[1]['context']['recent_history'][0]['proposal']==proposal
        report[mode]={'status':'PASS','fake_decisions':len(requests),'episode_status':episode['status']}
    report['status']='PASS';(a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
finally:server.shutdown();server.server_close();thread.join()
