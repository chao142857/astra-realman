"""Task/batch-bound non-generation readiness. No /decide or model dispatch."""
import argparse,json,socket,subprocess,sys,os,importlib.util
from datetime import datetime,timezone
from pathlib import Path
from full_task_gate import ROOT,hashes,sha,save,PARAMETERS


def check_mac(batch_id,service_path,tunnel_path):
    service=json.loads(Path(service_path).read_text());tunnel=json.loads(Path(tunnel_path).read_text())
    cmd=service['command'];source=Path(cmd[2]);exe=cmd[cmd.index('--executable')+1]
    assert sha(source)==hashes()['production/codex_astra_mac_bridge.py'],'BRIDGE_SOURCE_CHANGED'
    for pid in (service['pid'],tunnel['pid']):os.kill(pid,0)
    actual=subprocess.check_output(['ps','-p',str(service['pid']),'-o','command='],text=True)
    actual_tunnel=subprocess.check_output(['ps','-p',str(tunnel['pid']),'-o','command='],text=True)
    assert str(source) in actual and '--timeout-s 190' in actual and '--port 18767' in actual
    assert '127.0.0.1:18766:127.0.0.1:18767' in actual_tunnel and 'yanglab' in actual_tunnel
    with socket.create_connection(('127.0.0.1',18767),2):pass
    sys.path.insert(0,str(source.parent));spec=importlib.util.spec_from_file_location('_original_full_check',source)
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    # Existing CLI preflight invokes only login status, version and help.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='rm65-full-cli-preflight-') as tmp:
        worker=Path(tmp)/'worker'
        cli=bridge.preflight(exe,worker);assert cli['status']=='PASS'
        login=subprocess.run([exe,'login','status'],env=bridge.worker_environment(exe,worker),cwd=worker/'input_only',
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15)
        assert login.returncode==0 and 'ChatGPT' in login.stdout+login.stderr,'CHATGPT_LOGIN_REQUIRED'
    return {'status':'PASS','batch_id':batch_id,'checked_at':datetime.now(timezone.utc).isoformat(),
        'chatgpt_login':True,'server_timeout_s':190,'bridge_pid':service['pid'],'tunnel_pid':tunnel['pid'],
        'bridge_source_sha256':sha(source),'execution_host':'yanglab','real_requests':0}


def check_host(root,config,proof):
    from action_interface import MacBridgeConfig
    from coordination_batch01.preflight import auth_probe
    state=json.loads((root/'ledger.json').read_text());mac=json.loads(proof.read_text())
    assert socket.gethostname()=='tongji-Precision-3680' and state['status']=='DRAFT'
    assert state['source_hashes']==hashes() and state['parameters']==PARAMETERS
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(mac['checked_at'])).total_seconds()
    assert 0<=age<=900 and mac['batch_id']==state['batch_id'] and mac['status']=='PASS'
    assert mac['chatgpt_login'] and mac['server_timeout_s']==190 and mac['execution_host']=='yanglab'
    assert mac['bridge_source_sha256']==hashes()['production/codex_astra_mac_bridge.py']
    cfg=MacBridgeConfig.load(config);assert cfg.endpoint=='http://127.0.0.1:18766'
    assert auth_probe(cfg)==[404,403],'AUTH_OR_TUNNEL_FAILED'
    return {'status':'PASS','batch_id':state['batch_id'],'checked_at':datetime.now(timezone.utc).isoformat(),
        'source_hashes':hashes(),'actual_hostname':socket.gethostname(),'bridge_config_sha256':sha(config),
        'mac_proof_sha256':sha(proof),'client_timeout_s':180,'server_timeout_s':190,'model':'gpt-6-astra',
        'reasoning':'medium','workers':1,'non_generating_auth_and_tunnel_check':True,'real_requests':0}


def main():
    p=argparse.ArgumentParser();p.add_argument('side',choices=['mac','host']);p.add_argument('--batch-id')
    p.add_argument('--service',type=Path);p.add_argument('--tunnel',type=Path)
    p.add_argument('--budget-root',type=Path);p.add_argument('--bridge-config',type=Path);p.add_argument('--mac-proof',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('NEW_PREFLIGHT_OUTPUT_REQUIRED')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        report=check_mac(a.batch_id,a.service,a.tunnel) if a.side=='mac' else check_host(a.budget_root,a.bridge_config,a.mac_proof)
    except Exception as e:
        save(a.output,{'status':'FAIL','checked_at':datetime.now(timezone.utc).isoformat(),'reason':repr(e),'real_requests':0});raise
    save(a.output,report);print(json.dumps(report,indent=2))


if __name__=='__main__':main()
