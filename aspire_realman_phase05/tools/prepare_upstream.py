"""Apply/verify the five-line patch only inside THIS isolated workspace."""
import argparse,hashlib,json,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=pathlib.Path,default=ROOT/'.cache/ASPIRE');a=p.parse_args()
source=a.source.resolve()
if not source.is_relative_to(ROOT):raise SystemExit('REFUSE_PATCH_OUTSIDE_ISOLATED_WORKSPACE')
lock=json.loads((ROOT/'aspire_realman_phase05/upstream.lock.json').read_text())
rev=subprocess.check_output(['git','--no-optional-locks','-C',str(source),'rev-parse','HEAD'],text=True).strip()
if rev!=lock['commit']:raise SystemExit('ASPIRE_PIN_MISMATCH')
def hashes(names):return {n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in names}
current=hashes(lock['original_sha256'])
if current==lock['original_sha256']:
 patch=ROOT/'aspire_realman_phase05'/lock['patch']
 subprocess.run(['git','-C',str(source),'apply','--unidiff-zero','--check',str(patch)],check=True)
 subprocess.run(['git','-C',str(source),'apply','--unidiff-zero',str(patch)],check=True)
elif current!=lock['patched_sha256']:raise SystemExit('UNEXPECTED_UPSTREAM_FILE_MODIFICATION')
if hashes(lock['runtime_source_sha256'])!=lock['runtime_source_sha256']:raise SystemExit('RUNTIME_SOURCE_HASH_MISMATCH')
print(json.dumps({'commit':rev,'patch_verified':True,'source_files_verified':len(lock['runtime_source_sha256'])}))
