"""All nine episodes through fake HTTP + real PhysX; never a model result."""
import argparse
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from transfer_gate import save,sha,now
from action_interface import SCHEMA
from pilot02_runtime import bridge_module
from .contract import ROOT,ORDER
from .gate import prepare


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fault',choices=['none','403'],default='none');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);requests=[];ep=-1;step=0
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            nonlocal ep,step
            assert self.path=='/decide'
            assert self.headers['Authorization']=='Bearer mock-campaign-no-real-authentication'
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            bridge_module().validate_payload(body);c=body['context'];requests.append(body)
            assert body['authoritative_schema']==SCHEMA
            if a.fault=='403':self.send_response(403);self.end_headers();return
            if not c['recent_history']:
                ep+=1;step=0
                assert c['task_policy']['condition_id']==ORDER['order'][ep]['condition_id']
            public=c['task_policy'];first,second=public['visit_order']
            # PRIVATE TEST RESPONSES. These engineering actions are never added
            # to a real model context or dispatcher; only this fake server has them.
            targets=[(second,public['initial_ready_world_wxyz'][second]),(first,public[first+'_goal_world_wxyz']),
                     (first,public['initial_ready_world_wxyz'][first]),(second,public[second+'_goal_world_wxyz'])]
            if ep==0 and step==0:
                side,goal='right',[1.5,0,.2,1,0,0,0]
            elif step-(1 if ep==0 else 0)<4:
                side,goal=targets[step-(1 if ep==0 else 0)]
            else:side=goal=None
            answer={'done':side is None,'execution':'sequential','actions':[] if side is None else [
                {'arm':side,'kind':'tcp','pose_world_wxyz':goal,'opening_fraction':None}]}
            step+=1;n=len(requests);run=Path('/offline/campaign')/str(n)
            events=[{'type':'thread.started','thread_id':'fake-campaign-independent-'+str(n)},
                    {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]
            result={'raw':json.dumps(answer),'events':'\n'.join(map(json.dumps,events)),'stderr':'','error':None,'return_code':0,
                    'command':bridge_module().command(run,[run/'input_only'/f'image-{i}.png' for i in range(4)])}
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        token=a.output/'MOCK_TOKEN_NOT_CREDENTIAL.txt';token.write_text('mock-campaign-no-real-authentication')
        config=a.output/'mock_config.json';save(config,{'endpoint':'http://127.0.0.1:'+str(server.server_port),'token_file':str(token.resolve())})
        # A dedicated fixture scope is required; a REAL ledger cannot enter the
        # offline path and this port cannot connect to production Bridge ports.
        campaign=ROOT/'evidence/coordination_campaigns'/('MOCK_'+a.output.name)
        state=prepare(campaign,offline=True)
        grant=json.loads((campaign/'authorization_REQUEST_NOT_GRANTED.json').read_text())
        grant.update(max_dispatches=50,offline_fixture=True)
        auth=campaign/'MOCK_PERMISSION_NOT_USER_AUTHORIZATION.json';save(auth,grant)
        check={'status':'PASS','campaign_id':state['campaign_id'],'source_hashes':state['source_hashes'],
               'freeze_sha256':state['freeze_sha256'],'actual_hostname':'Ubuntu-Robot','bridge_config_sha256':sha(config),
               'non_generating_auth_and_tunnel_check':True,'client_timeout_s':180,'server_timeout_s':190,
               'model':'gpt-6-astra','reasoning':'medium','workers':1,'checked_at':now()}
        pre=campaign/'MOCK_PREFLIGHT_NOT_PRODUCTION.json';save(pre,check)
        command=[sys.executable,'-m','coordination_batch01.run','--budget-root',str(campaign),'--authorization',str(auth),
                 '--preflight',str(pre),'--mock-bridge-config',str(config)]
        proc=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        (a.output/'stdout.log').write_text(proc.stdout);(a.output/'stderr.log').write_text(proc.stderr)
        ledger=json.loads((campaign/'ledger.json').read_text());summary=json.loads((campaign/'summary.json').read_text())
        if a.fault=='none':
            assert proc.returncode==0 and ledger['status']=='FINISHED',proc.stderr
            assert ledger['reserved_budget']==46 and len(requests)==46
            assert all(e['status']=='SUCCESS' for e in ledger['episodes'])
            for e in ledger['episodes']:
                report=json.loads((campaign/e['episode_id']/'episode.json').read_text())
                assert report['model_history_at_reset']==[]
                assert report['score']==json.loads((campaign/e['episode_id']/'independent_score.json').read_text())
                assert report['terminal_hold_end_step']-report['terminal_hold_start_step']==500
            first=json.loads((campaign/'ep01/episode.json').read_text())
            assert first['numeric_refusals']==1 and first['corrections_after_refusal'][0]['changed_proposal']
            assert first['corrections_after_refusal'][0]['accepted']
            assert sum(not r['context']['recent_history'] for r in requests)==9
        else:
            assert ledger['status']=='STOPPED' and ledger['reserved_budget']==len(requests)==1
            assert ledger['episodes'][0]['status']=='INFRASTRUCTURE_FAILURE'
            assert all(e['status']=='NOT_STARTED' for e in ledger['episodes'][1:])
        report={'status':'PASS','source':'MOCK_NOT_ASTRA','real_generation_requests':0,'production_connections':0,
                'fault':a.fault,'fake_dispatches':len(requests),'campaign':str(campaign),'summary':summary,
                'note':'Fake responses plus actual PhysX verify wiring; no Astra capability claim.'}
        save(a.output/'acceptance.json',report);print(json.dumps({k:report[k] for k in ('status','fault','fake_dispatches','real_generation_requests')}))
    finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
