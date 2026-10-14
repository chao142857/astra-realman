"""Relocate copied historical asset roots only; no geometry/physics edits."""
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();p=root/'asset_manifest.json';m=json.loads(p.read_text())
for rel,row in m['files'].items():
 f=root/rel
 if f.suffix in ['.urdf','.yml']:
  s=f.read_text();new=s.replace('/home/alex/astra/vendor',str(root/'vendor'))
  if s!=new:f.write_text(new);row['changes'].append('archived /home/alex/astra/vendor -> isolated asset root; no geometry edits');row['sha256']=hashlib.sha256(f.read_bytes()).hexdigest()
p.write_text(json.dumps(m,indent=2)+'\n')
print('Asset path relocation complete; manifest updated')
