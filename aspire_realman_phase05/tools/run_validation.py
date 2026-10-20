"""Run software-only native CAP and real loopback MCP HTTP tests.
The process rejects outbound connections outside loopback and never imports an SDK.
"""
import argparse,datetime,hashlib,importlib.metadata,json,pathlib,subprocess,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--aspire-source',type=pathlib.Path,default=ROOT/'.cache/ASPIRE')
a=p.parse_args()
revision=subprocess.check_output(['git','--no-optional-locks','-C',str(a.aspire_source),'rev-parse','HEAD'],text=True).strip()
if revision!='fa00f0ef2bc1d91d594b9aa502c22133c9f538f7':raise SystemExit('ASPIRE_PIN_MISMATCH')
lock=json.loads((ROOT/'aspire_realman_phase05/upstream.lock.json').read_text())
for name,expected in lock['runtime_source_sha256'].items():
    if hashlib.sha256((a.aspire_source/name).read_bytes()).hexdigest()!=expected:raise SystemExit('UPSTREAM_RUNTIME_HASH_MISMATCH:'+name)
def network_guard(event,args):
    if event=='socket.connect':
        address=args[1]
        if isinstance(address,tuple) and address[0] not in ['127.0.0.1','::1']:
            raise PermissionError('Validation permits loopback connections only')
sys.addaudithook(network_guard)
sys.path[:0]=[str(ROOT/'aspire_realman_phase05/src'),str(a.aspire_source/'src')]
suite=unittest.defaultTestLoader.discover(str(ROOT/'aspire_realman_phase05/tests'))
r=unittest.TextTestRunner(verbosity=2).run(suite)
import test_mcp_http
bad=[n for n in sys.modules if n=='pyrealsense2' or n.startswith('Robotic_Arm')]
result={'timestamp':datetime.datetime.now().astimezone().isoformat(),'tests_run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'ok':r.wasSuccessful() and not bad,
 'python':sys.version,'executable':sys.executable,'upstream_commit':revision,'environment':{n:importlib.metadata.version(n) for n in ['numpy','mcp','fastapi','uvicorn','httpx','jsonschema','pillow']},
 'hardware_modules_loaded':bad,'physical_commands_sent':0,'camera_pipelines_opened_by_native_tests':0,'model_requests':0,
 'network_policy':'test interpreter rejects non-loopback socket connections','mcp_wire':test_mcp_http.WIRE_EVIDENCE}
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(not result['ok'])
