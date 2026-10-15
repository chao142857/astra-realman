"""Local mock only: prove takeover occurs at the table, before any pickup."""
import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from action_interface import SCHEMA
from full_handoff_task import INSTRUCTION,POLICY
from pilot02_runtime import bridge_module


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            assert self.path=='/decide' and self.headers.get('Authorization')=='Bearer full-task-mock-only'
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            bridge_module().validate_payload(body)
            assert body['authoritative_schema']==SCHEMA
            assert body['context']['instruction']==INSTRUCTION and body['context']['task_policy']==POLICY
            requests.append(body);i=len(requests)
            answer=({'done':False,'execution':'sequential','actions':[{'arm':'right','kind':'gripper',
                'pose_world_wxyz':None,'opening_fraction':1.}]} if i==1 else
                {'done':True,'execution':'sequential','actions':[]})
            run=Path('/offline/full-handoff-fixture')/str(i)
            result={'raw':json.dumps(answer),'events':'\n'.join(json.dumps(e) for e in [
                {'type':'thread.started','thread_id':'full-fixture-'+str(i)},
                {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]),
                'stderr':'','error':None,'return_code':0,
                'command':bridge_module().command(run,[run/'input_only'/f'image-{j}.png' for j in range(4)])}
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        token=a.output/'MOCK_token.txt';token.write_text('full-task-mock-only')
        config=a.output/'MOCK_config.json';config.write_text(json.dumps({'endpoint':f'http://127.0.0.1:{server.server_port}',
            'token_file':str(token.resolve())}))
        command=[sys.executable,'run_episode.py','--task','handoff_place_full','--output',str(a.output/'episode'),
            '--mock-bridge-config',str(config),'--max-decisions','2']
        result=subprocess.run(command,capture_output=True,text=True)
        (a.output/'stdout.log').write_text(result.stdout);(a.output/'stderr.log').write_text(result.stderr)
        e=json.loads((a.output/'episode/episode.json').read_text())
        assert e['status']=='MODEL_STOP_NOT_AUTOMATIC_SUCCESS' and e['decisions']==2,e
        assert e['expert_initialization_actions']==0 and e['model_takeover_step']==100
        assert len(requests)==2 and requests[0]['context']['recent_history']==[]
        assert len(requests[1]['context']['recent_history'])==1
        for arm in requests[0]['context']['observations']['arms'].values():assert arm['actual_pad_gap_m']>.085
        rows=[json.loads(x) for x in (a.output/'episode/physics.jsonl').read_text().splitlines()]
        first=next(r for r in rows if r['step']==100)
        assert .024<first['object_pose'][2]<.027 and not any(first['bilateral_contact'].values())
        assert any('table' in c['names'] and 'target_cube' in c['names'] for c in first['contacts'])
        for d in (a.output/'episode').glob('decision_*'):
            assert json.loads((d/'timing.json').read_text())['inference_physics_steps']==0
        assert e['historical_full_process_score_unchanged']['full_process_pass'] is False
        # --real must fail before config access, scene creation or dispatch.
        blocked=a.output/'unauthorized_real_must_not_exist'
        r=subprocess.run([sys.executable,'run_episode.py','--task','handoff_place_full','--real','--output',str(blocked)],capture_output=True,text=True)
        assert r.returncode!=0 and not blocked.exists() and 'no new full' in r.stderr
        report={'status':'PASS','real_generation_requests':0,'mock_requests':2,'production_bridge_connections':0,
            'takeover_before_pickup':True,'four_rgb':len(requests[0]['images'])==4,'expert_initialization_actions':0,
            'full_task_success_claim':False,'unauthorized_real_blocked_before_scene_creation':True}
        (a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
