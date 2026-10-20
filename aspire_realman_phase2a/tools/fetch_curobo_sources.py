"""Explicit opt-in fetch of pinned official cuRobo CODE, not robot assets.

Reuses verified local files. Does not fetch tests, examples, meshes or weights.
Read NETWORK-P0 before invoking; remote Phase2A cache is already prepared.
"""
import concurrent.futures,hashlib,json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
COMMIT='a35a708ecfbb26eb9ab2d7ef22c65919c4fae4a9'


def gitsha(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def main():
    out=ROOT/'.cache/curobo';out.mkdir(parents=True,exist_ok=True)
    lock=out/'SOURCE_LOCK.json'
    if lock.exists():
        metadata=json.loads(lock.read_text())
        if metadata['commit']!=COMMIT:raise SystemExit('CUROBO_PIN_MISMATCH')
        rows=metadata['files']
    else:
        url=f'https://api.github.com/repos/NVlabs/curobo/git/trees/{COMMIT}?recursive=1'
        req=urllib.request.Request(url,headers={'User-Agent':'ASPIRE-RealMan-Phase2A-source-fetch'})
        data=json.load(urllib.request.urlopen(req,timeout=30))
        if data.get('truncated'):raise SystemExit('INCOMPLETE_OFFICIAL_TREE')
        roots={'LICENSE','MANIFEST.in','README.md','pyproject.toml','setup.py'}
        excluded=('curobo/content/assets/','curobo/tests/','curobo/examples/')
        rows=[r for r in data['tree'] if r['type']=='blob' and (r['path'] in roots or r['path'].startswith('curobo/') and not r['path'].startswith(excluded))]
    if len(rows)!=443 or sum(r['size'] for r in rows)!=4148067:raise SystemExit('PINNED_SOURCE_INVENTORY_MISMATCH')
    def fetch(row):
        path=out/row['path'];path.resolve().relative_to(out.resolve())
        if path.exists():
            if gitsha(path.read_bytes())==row['sha']:return
            raise ValueError('EXISTING_SOURCE_MODIFIED_NOT_OVERWRITTEN:'+str(path))
        url=f'https://raw.githubusercontent.com/NVlabs/curobo/{COMMIT}/{row["path"]}'
        req=urllib.request.Request(url,headers={'User-Agent':'ASPIRE-RealMan-Phase2A-source-fetch'})
        with urllib.request.urlopen(req,timeout=45) as response:data=response.read(row['size']+1)
        if len(data)!=row['size'] or gitsha(data)!=row['sha']:raise ValueError('OFFICIAL_BLOB_HASH_MISMATCH')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(fetch,rows))
    lock.write_text(json.dumps({'repository':'https://github.com/NVlabs/curobo','commit':COMMIT,'files':rows},indent=2))
    print(json.dumps({'commit':COMMIT,'verified_source_files':len(rows),'source_bytes':sum(r['size'] for r in rows),'robot_assets_downloaded':False}))


if __name__=='__main__':main()
