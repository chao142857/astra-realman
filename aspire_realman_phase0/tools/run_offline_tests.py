"""Dependency-free test entry point. Optional --aspire-source uses existing NumPy.
Never downloads dependencies, launches services or connects to hardware.
"""
import argparse,hashlib,json,pathlib,subprocess,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--aspire-source',type=pathlib.Path)
a=p.parse_args()
sys.path.insert(0,str(ROOT/'src'))
if a.aspire_source:
    lock=json.loads((ROOT/'evidence/upstream_lock.json').read_text())
    revision=subprocess.check_output(['git','--no-optional-locks','-C',str(a.aspire_source),'rev-parse','HEAD'],text=True).strip()
    if revision!=lock['commit']:raise SystemExit('ASPIRE_COMMIT_MISMATCH')
    for name,expected in lock['files'].items():
        if hashlib.sha256((a.aspire_source/name).read_bytes()).hexdigest()!=expected:
            raise SystemExit('ASPIRE_FILE_HASH_MISMATCH: '+name)
    sys.path.insert(0,str(a.aspire_source/'src'))
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
r=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'tests_run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),
 'skipped':len(r.skipped),'ok':r.wasSuccessful(),'python':sys.version,'executable':sys.executable,
 'native_source':str(a.aspire_source) if a.aspire_source else None,
 'hardware_commands_sent':0,'camera_pipelines_opened':0,'model_requests':0,
 'scope':'software/mock/replay only; not physical accuracy, transport, model or safety certification'},indent=2))
sys.exit(not r.wasSuccessful() or bool(a.aspire_source and r.skipped))
