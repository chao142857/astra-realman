import hashlib,json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
lock=json.loads((ROOT/'aspire_realman_phase05/upstream.lock.json').read_text())
for name,sha in lock['runtime_source_sha256'].items():
    if hashlib.sha256((ROOT/'.cache/ASPIRE'/name).read_bytes()).hexdigest()!=sha:
        raise SystemExit('PINNED_UPSTREAM_CHANGED:'+name)
sys.path[:0]=[str(ROOT/'aspire_realman_phase1a/src'),str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src')]
def guard(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ['127.0.0.1','::1']:
        raise PermissionError('ONLY_LOOPBACK_ALLOWED')
sys.addaudithook(guard)
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'aspire_realman_phase1a/tests')))
print(json.dumps({'ok':r.wasSuccessful(),'tests':r.testsRun,'upstream_runtime_hashes_verified':len(lock['runtime_source_sha256']),
                  'unit_fixture_is_not_live_evidence':True,'hardware_imported':'pyrealsense2' in sys.modules}))
sys.exit(not r.wasSuccessful())
