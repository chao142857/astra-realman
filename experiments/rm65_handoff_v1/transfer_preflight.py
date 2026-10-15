"""Bind current yanglab production readiness to one new transfer episode. No /decide."""
import argparse
import http.client
import json
import socket
import uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from action_interface import MacBridgeConfig
from transfer_gate import hashes,sha,ROOT,now

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--task',choices=['handoff_transfer_only','shared_workspace_yield_v1'],default='handoff_transfer_only')
p.add_argument('--budget-root',type=Path,required=True);p.add_argument('--bridge-config',type=Path,required=True)
p.add_argument('--mac-proof',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();state=json.loads((a.budget_root/'ledger.json').read_text());mac=json.loads(a.mac_proof.read_text())
if a.task=='shared_workspace_yield_v1':
    from workspace_gate import hashes
    expected_host='Ubuntu-Robot'
    assert state['task']==a.task and mac.get('batch_id')==state['batch_id'],'NEW_WORKSPACE_BATCH_BINDING_REQUIRED'
else:expected_host='tongji-Precision-3680'
assert socket.gethostname()==expected_host,'EXECUTION_HOST_MISMATCH'
assert state['source_hashes']==hashes(),'SOURCE_CHANGED'
age=(datetime.now(timezone.utc)-datetime.fromisoformat(mac['checked_at'])).total_seconds()
source=ROOT.parents[1]/'astra_realman_harness/scripts/codex_astra_mac_bridge.py'
assert 0<=age<=900 and mac['status']=='PASS' and mac['chatgpt_login'] and mac['server_timeout_s']==190 and mac['bridge_source_sha256']==sha(source),'FRESH_MAC_PROOF_REQUIRED'
cfg=MacBridgeConfig.load(a.bridge_config)
assert cfg.endpoint=='http://127.0.0.1:18766','PRODUCTION_LOOPBACK_PORT_REQUIRED'
token=cfg.token_file.read_text().strip()
assert len(token)>=16 and '\n' not in token and '\r' not in token,'TOKEN_INVALID'
statuses=[]
for credential in (token,'deliberately-wrong-nonsecret-token'):
    conn=http.client.HTTPConnection('127.0.0.1',urlsplit(cfg.endpoint).port,timeout=5)
    try:
        # This unknown path reaches only the original handler's authenticated 404.
        # It never enters infer(), BUSY, or /decide. Wrong credential must be 403.
        conn.request('POST','/rm65-transfer-auth-check',body=json.dumps({'request_id':uuid.uuid4().hex}),
                     headers={'Authorization':'Bearer '+credential,'Content-Type':'application/json'})
        response=conn.getresponse();statuses.append(response.status);response.read()
    finally:conn.close()
assert statuses==[404,403],statuses
report={'status':'PASS','checked_at':now(),'batch_id':state['batch_id'],'source_hashes':hashes(),
        'actual_hostname':socket.gethostname(),'bridge_config_sha256':sha(a.bridge_config),
        'client_timeout_s':180,'server_timeout_s':190,'model':'gpt-6-astra','reasoning':'medium',
        'ephemeral':True,'workers':1,'non_generating_auth_and_tunnel_check':True,
        'auth_probe_path':'/rm65-transfer-auth-check','authenticated_http_status':404,
        'wrong_auth_http_status':403,'mac_proof_sha256':sha(a.mac_proof),'real_requests':0}
a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
