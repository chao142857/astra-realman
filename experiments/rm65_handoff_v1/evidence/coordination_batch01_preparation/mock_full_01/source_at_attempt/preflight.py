"""Campaign-bound non-generating Ubuntu check; never POST /decide."""
import argparse
import json
import socket
from datetime import datetime,timezone
from pathlib import Path
from action_interface import MacBridgeConfig,transport
from transfer_gate import sha,now,save
from .gate import hashes
from .contract import HERE


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--budget-root',type=Path,required=True);p.add_argument('--bridge-config',type=Path,required=True)
    p.add_argument('--mac-proof',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();state=json.loads((a.budget_root/'ledger.json').read_text());mac=json.loads(a.mac_proof.read_text())
    if a.output.exists():raise ValueError('NEW_PREFLIGHT_OUTPUT_REQUIRED')
    assert socket.gethostname()=='Ubuntu-Robot' and state['status']=='DRAFT'
    assert state['source_hashes']==hashes() and state['freeze_sha256']==sha(HERE/'freeze.json')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(mac['checked_at'])).total_seconds()
    assert 0<=age<=900 and mac['campaign_id']==state['campaign_id'] and mac['status']=='PASS'
    assert mac['chatgpt_login'] and mac['server_timeout_s']==190 and mac['bridge_source_sha256']==hashes()['production/codex_astra_mac_bridge.py']
    cfg=MacBridgeConfig.load(a.bridge_config);assert cfg.endpoint=='http://127.0.0.1:18766'
    token=cfg.token_file.read_text().strip();assert len(token)>=16 and '\n' not in token and '\r' not in token
    http=transport.MacBridgeAdapter(cfg,offline_test=False,timeout_limit_s=180)
    statuses=[]
    for credential in (token,'deliberately-wrong-nonsecret-token'):
        status,_=http._post('/rm65-transfer-auth-check',b'{}',credential,5);statuses.append(status)
    assert statuses==[404,403],statuses
    report={'status':'PASS','campaign_id':state['campaign_id'],'checked_at':now(),
            'source_hashes':hashes(),'freeze_sha256':state['freeze_sha256'],'actual_hostname':socket.gethostname(),
            'bridge_config_sha256':sha(a.bridge_config),'mac_proof_sha256':sha(a.mac_proof),
            'non_generating_auth_and_tunnel_check':True,'auth_probe_path':'/rm65-transfer-auth-check',
            'authenticated_http_status':404,'wrong_auth_http_status':403,'client_timeout_s':180,
            'server_timeout_s':190,'model':'gpt-6-astra','reasoning':'medium','workers':1,'real_requests':0}
    save(a.output,report);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
