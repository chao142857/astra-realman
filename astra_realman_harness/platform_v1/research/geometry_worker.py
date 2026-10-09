"""Replaceable PUBLIC geometry worker. No scene, simulator, score or SDK imports."""
import argparse
import hashlib
import json
import math
import contextlib
import sys
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from rgb import detect


def estimate(views, calibration):
    out = {'status': 'unknown', 'point_world_m': None, 'uncertainty_radius_m': None,
           'identity_status': 'hypothesis_not_verified', 'sources': views,
           'uncertainty_semantics': 'heuristic lower bound, not calibrated probability or collision clearance'}
    if len({v['camera'] for v in views}) < 2: return dict(out, reason='INSUFFICIENT_CURRENT_VIEWS')
    rays = []
    for v in views:
        c = calibration[v['camera']]; k = np.asarray(c['intrinsic']); pose = c['pose_world_xyz_wxyz']
        if k.shape != (3, 3) or not np.isfinite(k).all() or k[0,0] <= 0 or k[1,1] <= 0:
            return dict(out, reason='INVALID_CALIBRATION')
        rotation = Rotation.from_quat([*pose[4:], pose[3]]).as_matrix()
        u, pixel_v = v['pixel']; ray = rotation @ np.array([1., -(u-k[0,2])/k[0,0], -(pixel_v-k[1,2])/k[1,1]])
        rays.append((np.asarray(pose[:3]), ray/np.linalg.norm(ray)))
    baseline = max(math.acos(min(1., abs(float(a[1] @ b[1])))) for a in rays for b in rays)
    if baseline < math.radians(15): return dict(out, reason='DEGENERATE_RAYS')
    matrices = [np.eye(3)-np.outer(v,v) for _,v in rays]
    point = np.linalg.lstsq(sum(matrices), sum(m @ ray[0] for m,ray in zip(matrices,rays)), rcond=None)[0]
    residual = max(float(np.linalg.norm(m @ (point-ray[0]))) for m,ray in zip(matrices,rays))
    if not np.isfinite(point).all() or residual > .015 or any((point-p) @ ray <= 0 for p,ray in rays):
        return dict(out, reason='INCONSISTENT_OR_BEHIND_CAMERA', residual_m=residual)
    return dict(out, status='coarse', point_world_m=point.tolist(), residual_m=residual,
                uncertainty_radius_m=max(.02, 2*residual), reason='CENTROID_CORRESPONDENCE_ASSUMPTION')


def compute(wire):
    if wire['backend'] == 'da3_small_v1':
        from da3_geometry import compute as learned_compute
        # Model library logging must not corrupt the single JSON stdout result.
        with contextlib.redirect_stdout(sys.stderr): return learned_compute(wire)
    current = wire['observations'][-1]; oid = current['observation_id']; detected = {}
    for camera, file in current['images'].items(): detected[camera] = detect('/input/'+file)
    groups = {}
    if wire['backend'] == 'legacy_rgb_rays_v1':
        for camera, d in detected.items():
            for key, identity in (('object','red_task_object'), ('goal','green_goal')):
                groups.setdefault(identity, [])
                if d[key]['status'] == 'visible':
                    groups[identity].append({'observation_id':oid,'camera':camera,'pixel':d[key]['centroid'],
                        'captured_monotonic':current['captured_monotonic'],'source':'CURRENT_RGB_COMPONENT_NOT_GT'})
    elif wire['backend'] == 'bbox_rays_v1':
        for region in wire['regions']:
            identity = region['entity_id']; groups.setdefault(identity, [])
            if region['observation_id'] != oid: continue # Historical boxes are not current object state.
            if region['clipped_in_selected_image']: continue
            box = region['bbox']; camera = region['camera']; width,height = current['calibration'][camera]['resolution']
            if box[0] <= 0 or box[1] <= 0 or box[2] >= 1 or box[3] >= 1: continue
            if not detected[camera]['healthy']: continue
            groups[identity].append({'observation_id':oid,'camera':camera,
                'pixel':[(box[0]+box[2])*width/2,(box[1]+box[3])*height/2],
                'captured_monotonic':current['captured_monotonic'],'source':'MODEL_BBOX_CENTER_HYPOTHESIS'})
    else: raise ValueError('WORLD_BACKEND')
    entities = {k:estimate(v,current['calibration']) for k,v in groups.items()}
    return {'backend':wire['backend'], 'observation_id':oid, 'captured_monotonic':current['captured_monotonic'],
            'scene_healthy':any(d['healthy'] for d in detected.values()), 'entities':entities,
            'robot_state':current['state'], 'history_semantics':'read-only observations; old bbox never asserted current',
            'geometry_only':True, 'task_identity_verified':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--sha256',required=True);a=p.parse_args()
    # Deliberate sandbox assertions cover private workspace absence without opening it.
    if Path('/home/alex/astra-realman_ws').exists() or Path('/private').exists(): raise RuntimeError('GEOMETRY_ISOLATION')
    data=Path('/input/world_input.json').read_bytes()
    if hashlib.sha256(data).hexdigest()!=a.sha256: raise ValueError('FROZEN_WORLD_INPUT_HASH')
    w=json.loads(data)
    for o in w['observations']:
        for camera,name in o['images'].items():
            if Path(name).name != name: raise ValueError('IMAGE_PATH')
            if hashlib.sha256(Path('/input',name).read_bytes()).hexdigest()!=o['image_sha256'][camera]: raise ValueError('IMAGE_HASH')
    print(json.dumps({'binding':w['binding'],'state':compute(w)},allow_nan=False),flush=True)
if __name__=='__main__':main()
