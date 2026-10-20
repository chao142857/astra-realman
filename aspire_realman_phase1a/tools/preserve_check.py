"""Read-only V17/V19 manifests and source hashes. No robot or camera imports."""
import datetime,hashlib,json
from pathlib import Path
H=Path('/home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness')
OUT=Path('/home/tongji/alex/aspire_realman_phase1a_20261020/evidence/preservation.json')
results=[]
for name in ['parallel-arms-20261018T142729-853ffbe2','parallel-arms-20261018T145818-fd3d3371','parallel-arms-20261018T153025-8a4d5e3b']:
 p=H/'logs'/name/'launch_manifest.json';raw=p.read_bytes();d=json.loads(raw);same=[];different=[];missing=[]
 for path,expected in d['implementation_sha256'].items():
  f=H/path
  if not f.is_file():missing.append(path)
  elif hashlib.sha256(f.read_bytes()).hexdigest()==expected:same.append(path)
  else:different.append(path)
 results.append({'manifest':str(p),'manifest_sha256':hashlib.sha256(raw).hexdigest(),
   'source_count':len(d['implementation_sha256']),'same_count':len(same),'different':different,'missing':missing})
OUT.write_text(json.dumps({'timestamp':datetime.datetime.now().astimezone().isoformat(),'archives':results,
 'scope':'Manifest contents and all named deployed source files; not an exhaustive hash of image/log payloads',
 'writes_to_original_deployment':0},indent=2))
print(OUT.read_text())
