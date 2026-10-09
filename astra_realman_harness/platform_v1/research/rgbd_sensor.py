"""Optional render-sensor adapter. Never reads actor poses or segmentation buffers.

It reads Position from the SAME cached take_picture as the original RGB capture.
Depth is OpenCV optical-axis z in metres, not Euclidean ray range.
"""
import copy
import hashlib
import io
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image
from sim_skills.full_pnp.backend import FullTaskBackend

VERSION='astra.shared.observation.rgbd.v2'

def sha(data):return hashlib.sha256(data).hexdigest()


class RGBDObservationBackend(FullTaskBackend):
    """Only observe is extended. Inherited physics/execution/safety are unchanged."""
    def observe(self):
        step_before=self.steps;started=time.monotonic()
        observation=super().observe()
        if self.steps!=step_before:raise ValueError('RENDER_CAPTURE_PHYSICS_ADVANCED')
        records=[]
        for camera in ('assembly','fixed','wrist'):
            cam=self.s.cameras[camera]
            # No take_picture here: read the already captured RGB-D render result.
            position=np.asarray(cam.get_picture('Position'),dtype=np.float32)
            color=np.asarray(cam.get_picture('Color'))
            rgb=(np.clip(color[:,:,:3],0,1)*255).astype(np.uint8)
            rgb_path=Path(observation['images'][camera])
            if not np.array_equal(rgb,np.array(Image.open(rgb_path).convert('RGB'))):
                raise ValueError('RGB_DEPTH_RENDER_BINDING_FAILED')
            if position.shape!=(480,640,4):raise ValueError('RENDER_POSITION_SHAPE')
            depth=-position[:,:,2]
            valid=np.isfinite(position).all(2)&(position[:,:,3]<1)&(depth>=.01)&(depth<5)
            depth=np.where(valid,depth,0).astype('<f4')
            dp=rgb_path.with_suffix('.depth.npy');vp=rgb_path.with_suffix('.valid.png')
            np.save(dp,depth,allow_pickle=False);Image.fromarray(valid.astype(np.uint8)*255).save(vp)
            records.append({'camera':camera,'depth_path':str(dp),'validity_path':str(vp),
                'unit':'m','depth_convention':'opencv_optical_z','dtype':'float32','resolution':[640,480],
                'frame_id':observation['observation_id']+'/'+camera,
                'captured_monotonic':observation['captured_monotonic'],
                'capture_interval_monotonic':[started,observation['captured_monotonic']],
                'readback_completed_monotonic':time.monotonic(),
                'sensor_timestamp':self.steps*self.dt,'timestamp_domain':'simulation_seconds',
                'simulation_step':self.steps,'same_physics_step_three_views':True,
                'depth_sha256':sha(dp.read_bytes()),'validity_sha256':sha(vp.read_bytes()),
                'raw_position_buffer_sha256':sha(position.tobytes()),'rgb_sha256':sha(rgb_path.read_bytes()),
                'alignment':{'kind':'same_render_pixel_grid','depth_to_rgb':'identity','crop':None,
                    'resize':None,'intrinsics':observation['calibration'][camera]['intrinsic'],
                    'T_depth_to_rgb':np.eye(4).tolist()},
                'source':'SAPIEN_RENDER_POSITION_Z_ONLY','sensor_exposure_timestamp':None})
        observation['depth']=records
        return observation


def export_depth(raw, destination, rgb):
    """Whitelist public sensor fields; never forward arbitrary backend dictionaries."""
    records=raw['depth']
    if len(records)!=3 or {r['camera'] for r in records}!={'assembly','fixed','wrist'}:
        raise ValueError('THREE_DEPTH_CAMERAS_REQUIRED')
    output=[]
    allowed=('camera','unit','depth_convention','dtype','resolution','frame_id','captured_monotonic',
        'capture_interval_monotonic','readback_completed_monotonic','sensor_timestamp','timestamp_domain',
        'simulation_step','same_physics_step_three_views','raw_position_buffer_sha256','alignment',
        'source','sensor_exposure_timestamp')
    for rec in records:
        item={k:copy.deepcopy(rec[k]) for k in allowed};c=rec['camera']
        if rec['source']!='SAPIEN_RENDER_POSITION_Z_ONLY':raise ValueError('UNSUPPORTED_SENSOR_PRODUCER')
        expected={'kind':'same_render_pixel_grid','depth_to_rgb':'identity','crop':None,'resize':None,
            'intrinsics':raw['calibration'][c]['intrinsic'],'T_depth_to_rgb':np.eye(4).tolist()}
        if rec['alignment']!=expected:raise ValueError('UNSUPPORTED_SENSOR_ALIGNMENT')
        if rec['simulation_step']!=raw['state']['sim_step']:raise ValueError('SENSOR_STEP_BINDING')
        source=next(x for x in rgb if x['camera']==c)
        if rec['rgb_sha256']!=source['sha256']:raise ValueError('RGBD_HASH_BINDING')
        for key,suffix in [('depth','.depth.npy'),('validity','.valid.png')]:
            data=Path(rec[key+'_path']).read_bytes()
            if len(data)>8*1024*1024 or sha(data)!=rec[key+'_sha256']:raise ValueError('DEPTH_SOURCE_HASH')
            name=c+suffix;(Path(destination)/name).write_bytes(data)
            item[key]={'file':name,'sha256':sha(data),'relative_to':'matching_rgb_directory'}
        item['aligned_rgb_sha256']=source['sha256'];output.append(item)
    return output


def load_depth(store, observation_id, camera):
    """Strict, hash-checked depth loading for existing PublicStore."""
    o=store.get(observation_id)
    if o.get('schema')!=VERSION:raise ValueError('RGBD_OBSERVATION_REQUIRED')
    if len(o.get('depth',[]))!=3 or {x['camera'] for x in o['depth']}!={'assembly','fixed','wrist'}:
        raise ValueError('THREE_DEPTH_CAMERAS_REQUIRED')
    rec=next((x for x in o.get('depth',[]) if x['camera']==camera),None)
    rgb=next((x for x in o['rgb'] if x['camera']==camera),None)
    if rec is None or rgb is None:raise ValueError('MISSING_DEPTH_CAMERA')
    if rec['unit']!='m' or rec['depth_convention']!='opencv_optical_z' or rec['dtype']!='float32':
        raise ValueError('DEPTH_UNITS_OR_CONVENTION')
    if rec['aligned_rgb_sha256']!=rgb['sha256']:raise ValueError('DEPTH_RGB_HASH_BINDING')
    alignment=rec['alignment'];cal=o['calibration'][camera]
    if alignment!={'kind':'same_render_pixel_grid','depth_to_rgb':'identity','crop':None,'resize':None,
        'intrinsics':cal['intrinsic'],'T_depth_to_rgb':np.eye(4).tolist()}:
        raise ValueError('DEPTH_ALIGNMENT_NOT_SUPPORTED')
    if rec['resolution']!=cal['resolution'] or rec['captured_monotonic']!=o['captured_monotonic']:
        raise ValueError('DEPTH_TIME_OR_RESOLUTION')
    if rec['simulation_step']!=o['state']['sim_step'] or rec['same_physics_step_three_views'] is not True:
        raise ValueError('DEPTH_SYNC_UNVERIFIED')
    if rec['frame_id']!=observation_id+'/'+camera:raise ValueError('DEPTH_FRAME_BINDING')
    start,end=rec['capture_interval_monotonic']
    if not np.isfinite([start,end,rec['readback_completed_monotonic'],rec['sensor_timestamp']]).all():
        raise ValueError('DEPTH_NONFINITE_TIMESTAMPS')
    if not start<=end==o['captured_monotonic']<=rec['readback_completed_monotonic']:
        raise ValueError('DEPTH_TIMESTAMPS')
    def read(key):
        entry=rec[key]
        if entry.get('relative_to')!='matching_rgb_directory' or Path(entry['file']).name!=entry['file']:
            raise ValueError('DEPTH_PATH_ESCAPE')
        path=(store.root/Path(rgb['file']).parent/entry['file']).resolve()
        if not path.is_relative_to(store.root):raise ValueError('DEPTH_PATH_ESCAPE')
        data=path.read_bytes()
        if len(data)>8*1024*1024 or sha(data)!=entry['sha256']:raise ValueError('DEPTH_HASH')
        return data
    depth=np.load(io.BytesIO(read('depth')),allow_pickle=False)
    raw_mask=np.asarray(Image.open(io.BytesIO(read('validity'))))
    width,height=cal['resolution']
    if depth.shape!=(height,width) or depth.dtype!=np.dtype('float32') or raw_mask.shape!=depth.shape:
        raise ValueError('DEPTH_ARRAY_SHAPE_DTYPE')
    if not set(np.unique(raw_mask))<={0,255}:raise ValueError('DEPTH_VALIDITY_BINARY')
    valid=raw_mask==255
    if not np.isfinite(depth).all() or np.any(depth[valid]<=0) or np.any(depth[~valid]!=0):
        raise ValueError('DEPTH_VALIDITY_VALUES')
    return depth,valid,copy.deepcopy(rec)
