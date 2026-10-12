"""Verify saved actual render RGB-D binding and collider-derived GT, no model."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from spatial_eval.inputs import load_snapshot
from spatial_eval.sapien_scenes import truth_from_state


def validate(root):
    results=[]
    manifest=json.loads((root/'manifest.json').read_text())
    for entry in manifest['scenes']:
        folder=root/entry['scene_id']; scene=load_snapshot(folder/'snapshot.json')
        gt=truth_from_state(json.loads((folder/'physics_state.json').read_text()))
        if gt!=scene['ground_truth'] or gt!=scene['geometry']['oracle']:
            raise ValueError('COLLIDER_GT_MISMATCH')
        views=[]
        for depth in scene['observations']['depth']:
            camera=depth['camera_id']; rgb=next(v for v in scene['observations']['rgb'] if v['camera_id']==camera)
            if depth['aligned_rgb_sha256']!=rgb['sha256']:
                raise ValueError('ALIGNMENT_HASH')
            for key in ('depth','validity'):
                data=(folder/depth[key]['file']).read_bytes()
                if hashlib.sha256(data).hexdigest()!=depth[key]['sha256']:raise ValueError('DEPTH_HASH')
            pixels=np.asarray(Image.open(rgb['path']))
            values=np.load(folder/depth['depth']['file'],allow_pickle=False)
            valid=np.asarray(Image.open(folder/depth['validity']['file']))==255
            if (pixels.shape[:2]!=values.shape or values.shape!=valid.shape
                or values.dtype!=np.dtype('<f4') or not np.isfinite(values).all()
                or not np.all(values[~valid]==0) or not valid.any()
                or not np.all((values[valid]>.01)&(values[valid]<5))
                or int(valid.sum())!=depth['valid_pixel_count']):
                raise ValueError('RGBD_SEMANTICS')
            views.append({'camera_id':camera,'valid_pixels':int(valid.sum()),
                          'depth_range_m':[float(values[valid].min()),float(values[valid].max())],
                          'rgb_std':float(pixels.std()),'shape':list(values.shape),'status':'PASS'})
        results.append({'scene_id':entry['scene_id'],'views':views,'task_count':len(scene['task']),
                        'gt_matches_live_collider_export':True})
    return {'status':'PASS','real_model_calls':0,'scene_count':len(results),
            'rgbd_count':sum(len(r['views']) for r in results),'scenes':results}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('REFUSE_OVERWRITE')
    result=validate(args.captures)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS scenes=%d RGBD=%d model_calls=0'%(result['scene_count'],result['rgbd_count']))
