"""Lossless Git copies; leave original per-step raw files untouched on yanglab."""
import gzip,hashlib,json
from pathlib import Path
D=Path(__file__).resolve().parent
entries=[]
for p in sorted((D/'evidence').rglob('*.jsonl')):
 data=p.read_bytes();compressed=gzip.compress(data,compresslevel=6,mtime=0);out=p.with_suffix(p.suffix+'.gz');out.write_bytes(compressed)
 assert gzip.decompress(out.read_bytes())==data
 entries.append({'raw':str(p.relative_to(D)),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'archive':str(out.relative_to(D)),'archive_sha256':hashlib.sha256(compressed).hexdigest()})
(D/'evidence/raw_archive_manifest.json').write_text(json.dumps({'policy':'All original raw files retained on yanglab. Git carries byte-identical decompressed copies, including fake CLI events. No old experiment files touched.','entries':entries},indent=2))
print(len(entries),'lossless raw archives')
