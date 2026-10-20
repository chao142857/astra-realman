"""Read-only provenance checks + lightweight index; leaves raw evidence in place."""
import argparse,hashlib,json,platform,sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.resolve().relative_to(ROOT)
    if a.output.exists():raise SystemExit('REFUSE_OVERWRITE_ARCHIVE_INDEX')
    lock=json.loads((ROOT/'aspire_realman_phase05/upstream.lock.json').read_text())
    source=ROOT/'.cache/ASPIRE'
    expected=dict(lock['runtime_source_sha256'])
    expected['src/cap_harness/providers/curobo/service.py']='358566689740eb2b8557b886ffdc704195f5f30c16013fcd04e9793424d8be6a'
    bad=[name for name,value in expected.items() if sha(source/name)!=value]
    cr=ROOT/'.cache/curobo';cl=json.loads((cr/'SOURCE_LOCK.json').read_text());compat=json.loads((cr/'PHASE2A_COMPAT_LOCK.json').read_text())
    cbad=[]
    for row in cl['files']:
        path=cr/row['path'];data=path.read_bytes()
        if row['path'] in compat:
            okay=hashlib.sha256(data).hexdigest()==compat[row['path']]['patched_sha256']
        else:okay=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==row['sha']
        if not okay:cbad.append(row['path'])
    models=[]
    for path in sorted((ROOT/'evidence').glob('model-*/model.json')):
        m=json.loads(path.read_text());cfg=yaml.safe_load(Path(m['config']['path']).read_text())['robot_cfg']['kinematics']
        paths=list(m['source_sha256']);old=next(x for x in paths if x.endswith('curobo.yml'))
        policy=yaml.safe_load(Path(old).read_text())['robot_cfg']['kinematics']['self_collision_ignore']
        exact={arm+'_'+k:[arm+'_'+v for v in values] for arm in ('left','right') for k,values in policy.items()}
        models.append({'manifest':str(path),'sha256':sha(path),'sphere_count':sum(map(len,cfg['collision_spheres'].values())),
            'original_ignore_pairs_unchanged':cfg['self_collision_ignore']==exact,
            'artifact_hashes_match':all(sha(m[k]['path'])==m[k]['sha256'] for k in ('urdf','config')),
            'original_assets_hashes_match':all(sha(p)==h for p,h in {**m['source_sha256'],**m['source_mesh_sha256']}.items()),
            'layout':m['layout'],'actual_grasp_tcp':m['actual_grasp_tcp'],'finger_configuration':m.get('finger_configuration',{'kind':'HISTORICAL_LOCKED_VALUES'})})
    outputs=[]
    for path in sorted((ROOT/'evidence').rglob('*')):
        if not path.is_file() or 'downloads' in path.parts or path.resolve()==a.output.resolve():continue
        if path.name.startswith(('phase2a-evidence-index','phase2a-delivery')) or path.name=='archive-summary.log':continue
        outputs.append({'path':str(path),'bytes':path.stat().st_size,'sha256':sha(path)})
    result={'baseline_realman':'24e71b77fb4686bed526ec04b0b1ea5014d5a50a','aspire_commit':lock['commit'],'aspire_files_verified':len(expected),
        'aspire_unexpected_changes':bad,'curobo_commit':cl['commit'],'curobo_files_verified':len(cl['files']),
        'curobo_compatibility_patch_files':compat,'curobo_unexpected_changes':cbad,'models':models,'raw_evidence':outputs,
        'integration_source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'aspire_realman_phase2a').rglob('*')) if p.is_file() and not p.name.startswith('._') and 'evidence' not in p.parts and p.suffix in ('.py','.sh','.patch','.txt')},
        'python':sys.version,'executable':sys.executable,'base_prefix':sys.base_prefix,'platform':platform.platform(),
        'safety':'No additional ignore pairs; all hardware dispatch hard-disabled. Raw evidence remains on execution host.'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2))
    okay=not bad and not cbad and all(m['original_ignore_pairs_unchanged'] and m['artifact_hashes_match'] and m['original_assets_hashes_match'] for m in models)
    print(json.dumps({'provenance_ok':okay,'raw_evidence_files':len(outputs),'models':len(models),'index':str(a.output),'sha256':sha(a.output)}))
    raise SystemExit(0 if okay else 1)
if __name__=='__main__':main()
