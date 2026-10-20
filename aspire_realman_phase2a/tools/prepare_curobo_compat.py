"""Patch ONLY function registration in this isolated, pinned cuRobo copy."""
import difflib,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];source=ROOT/'.cache/curobo'
lock=json.loads((source/'SOURCE_LOCK.json').read_text())
if lock['commit']!='a35a708ecfbb26eb9ab2d7ef22c65919c4fae4a9':raise SystemExit('CUROBO_PIN_MISMATCH')
rows={r['path']:r for r in lock['files']};patch=[];proof={}
for filename in ['wp_collision_kernel.py','wp_sweep_collision_kernel.py']:
    name='curobo/_src/geom/collision/'+filename;path=source/name;old=path.read_text()
    if 'ASPIRE_PHASE2A_WARP19_COMPAT' in old:raise SystemExit('ALREADY_PATCHED_USE_EXISTING_COMPAT_LOCK')
    data=old.encode();blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if blob!=rows[name]['sha']:raise SystemExit('PINNED_CUROBO_SOURCE_HASH_REQUIRED')
    new=old.replace('import warp as wp','import warp as wp\n# ASPIRE_PHASE2A_WARP19_COMPAT: registration only; SDF/gradients unchanged\nfrom aspire_realman_phase2a.compat import warp_func')
    count=new.count('wp.func(')
    new=new.replace('wp.func(', 'warp_func(').replace('module=__name__)', 'module=__name__, scope=locals())')
    if count!=(3 if filename=='wp_collision_kernel.py' else 4):raise SystemExit('UNEXPECTED_REGISTRATION_COUNT')
    path.write_text(new)
    patch.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
    proof[name]={'original_sha256':hashlib.sha256(data).hexdigest(),'patched_sha256':hashlib.sha256(new.encode()).hexdigest()}
(ROOT/'aspire_realman_phase2a/patches/0002-curobo-warp19-registration.patch').write_text(''.join(patch))
(source/'PHASE2A_COMPAT_LOCK.json').write_text(json.dumps(proof,indent=2))
print(json.dumps(proof,indent=2))
