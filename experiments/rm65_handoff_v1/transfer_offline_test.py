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

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--task',choices=['handoff_transfer_only','shared_workspace_yield_v1'],default='handoff_transfer_only');a=p.parse_args();workspace=a.task=='shared_workspace_yield_v1'
a.output.mkdir(parents=True,exist_ok=False);requests=[];mode='shadow'
from workspace_task import INSTRUCTION as WI, CRITERIA

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        assert self.path=='/decide'
        assert self.headers.get('Authorization')=='Bearer offline-transfer-fixture-token'
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        bridge_module().validate_payload(body)
        assert body['context']['instruction']==(WI if workspace else TRANSFER_INSTRUCTION) and body['authoritative_schema']==SCHEMA
        requests.append(body);n=len(requests)
        tcp=body['context']['observations']['arms']['right']['actual_grasp_center_world'].copy();tcp[2]+=.005
        q=body['context']['observations']['arms']['right']['flange_pose_world'][3:]
        pose=[1.5,0,.2,1,0,0,0] if n==1 else tcp+q
        answer={'done':False,'execution':'sequential','actions':[{'arm':'right','kind':'tcp','pose_world_wxyz':pose,'opening_fraction':None}]}
        if workspace and mode=='execute':
            ready_left=[-0.009191693272374193,0.01447982376295278,0.21545517067657338,-2.2741733118891716e-06,1.0,1.4905555190125597e-06,3.965629730373621e-06]
            policy=body['context']['task_policy']
            targets={2:('left',ready_left),3:('right',policy['right_goal_world_wxyz']),4:('right',policy['initial_right_ready_world_wxyz']),5:('left',policy['left_goal_world_wxyz'])}
            if n in targets:
                side,goal=targets[n];answer={'done':False,'execution':'sequential','actions':[{'arm':side,'kind':'tcp','pose_world_wxyz':goal,'opening_fraction':None}]}
            if n==6:
                actions=[]
                for side in ('left','right'):
                    state=body['context']['observations']['arms'][side]
                    position=state['actual_grasp_center_world'].copy();position[2]+=.003
                    actions.append({'arm':side,'kind':'tcp','pose_world_wxyz':position+state['flange_pose_world'][3:],'opening_fraction':None})
                answer={'done':False,'execution':'parallel','actions':actions}
            if n==7:answer={'done':True,'execution':'sequential','actions':[]}
        elif mode=='execute' and n==3:answer={'done':True,'execution':'sequential','actions':[]}
        events=[{'type':'thread.started','thread_id':'fixture-'+mode+'-'+str(n)},
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
            '--task',a.task,'--output',str(out),'--mock-bridge-config',str(config),
            '--mode',mode,'--max-decisions',('7' if workspace else '3')],capture_output=True,text=True)
        (a.output/(mode+'_stdout.log')).write_text(proc.stdout);(a.output/(mode+'_stderr.log')).write_text(proc.stderr)
        episode=json.loads((out/'episode.json').read_text())
        assert episode['status']==('SHADOW_VALID_NO_EXECUTION' if mode=='shadow' else 'MODEL_STOP_REQUEST_NOT_AUTOMATIC_SUCCESS'),episode
        assert len(requests)==(1 if mode=='shadow' else (7 if workspace else 3))
        for d in sorted(out.glob('decision_*')):
            timing=json.loads((d/'timing.json').read_text());assert timing['inference_physics_steps']==0
        first=json.loads((out/'decision_000/receipt.json').read_text())
        assert not first['executed']
        if mode=='execute':
            proposal=json.loads((out/'decision_000/proposal.json').read_text());assert proposal['actions'][0]['pose_world_wxyz'][0]==1.5
            assert 'TCP_WORKSPACE' in json.dumps(first)
            second=json.loads((out/'decision_001/receipt.json').read_text());assert second['ok'] and second['executed'],second
            assert requests[1]['context']['recent_history'][0]['proposal']==proposal
        if workspace and mode=='execute':
            assert episode['terminal_hold_end_step']-episode['terminal_hold_start_step']==500
            assert episode['private_physical_assessment']['pass'],episode['private_physical_assessment']
            for group in sorted(out.glob('group_*/receipt.json')):
                receipt=json.loads(group.read_text())
                if receipt['ok']:assert receipt['post_numeric_observation']['duration_s']>=.5
            from decision4_trace import read_rows
            from evaluate_workspace import assess
            public=json.loads((out/'workspace_public_policy.json').read_text());rows=[r for r in read_rows(out) if r['step']>=episode['task_start_step']]
            score=assess(rows,.004,public);assert score==episode['private_physical_assessment']
            (out/'independent_workspace_score.json').write_text(json.dumps(score,indent=2)+'\n')
            parallel=json.loads((out/'decision_005/receipt.json').read_text())
            assert parallel['ok'] and parallel['post_numeric_observation']['duration_s']>=.5
            import numpy as np
            group=out/'group_007'
            with np.load(group/'left_trajectory.npz') as l,np.load(group/'right_trajectory.npz') as r:
                assert parallel['end_step']-parallel['start_step']==max(len(l['position']),len(r['position']))+125
        report[mode]={'status':'PASS','fake_decisions':len(requests),'episode_status':episode['status']}
    report['status']='PASS';(a.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
finally:server.shutdown();server.server_close();thread.join()
