"""Whitelist export. Never reads snapshot, capture, private specs or segmentation arrays."""
import argparse, hashlib, json, shutil
from pathlib import Path
import numpy as np
SCENES=('p02_b_open_minus','p02_b_open_plus','p02_c_slot_030','p02_c_slot_120')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def export(suite,out):
 out.mkdir(parents=True,exist_ok=False);manifest=[]
 for scene in SCENES:
  src=suite/scene; dst=out/scene;dst.mkdir()
  context=src/'model_inputs/RGB_MULTI_VIEW/context.json';c=json.loads(context.read_text());assert c['geometry'] is None
  shutil.copyfile(context,dst/'context.json')
  for i,a in enumerate(c['attachments']):
   cam=a['camera_id'];rgb=src/'model_inputs/RGB_MULTI_VIEW'/a['file'];assert sha(rgb)==a['sha256'];shutil.copyfile(rgb,dst/f'image-{i}.png')
   with np.load(src/'assets'/f'{cam}_rgbd.npz',allow_pickle=False) as z:
    np.save(dst/f'depth-{i}.npy',z['depth_m']);np.save(dst/f'valid-{i}.npy',z['valid'])
  manifest.extend({'file':str(p.relative_to(out)),'sha256':sha(p)} for p in sorted(dst.iterdir()))
 (out/'manifest.json').write_text(json.dumps({'version':'public_rgbd.v1','files':manifest,'npz_members_read':['depth_m','valid'],'segmentation_used':False},indent=2)+'\n')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();export(a.suite,a.output)
