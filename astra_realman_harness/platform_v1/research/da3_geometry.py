"""Pretrained depth backend. Pure camera/sample helpers are testable without torch.

Public calibration uses SAPIEN camera axes (+x forward,+y left,+z up).
DA3 consumes OpenCV world-to-camera (+x right,+y down,+z forward).
"""
import time
import numpy as np
from scipy.spatial.transform import Rotation

CAMERAS=('assembly','fixed','wrist')

def calibrated_cameras(observation):
    extrinsics=[];intrinsics=[]
    cv_to_sapien=np.array([[0,0,1],[-1,0,0],[0,-1,0]],dtype=float)
    for name in CAMERAS:
        c=observation['calibration'][name];p=c['pose_world_xyz_wxyz'];k=np.asarray(c['intrinsic'],dtype=float)
        if len(p)!=7 or k.shape!=(3,3) or not np.isfinite(p).all() or not np.isfinite(k).all(): raise ValueError('CALIBRATION')
        if k[0,0]<=0 or k[1,1]<=0 or abs(np.linalg.norm(p[3:])-1)>.002: raise ValueError('CALIBRATION')
        r=Rotation.from_quat([*p[4:],p[3]]).as_matrix()@cv_to_sapien
        c2w=np.eye(4);c2w[:3,:3]=r;c2w[:3,3]=p[:3]
        extrinsics.append(np.linalg.inv(c2w));intrinsics.append(k)
    centers=np.array([np.linalg.inv(e)[:3,3] for e in extrinsics])
    if max(np.linalg.norm(a-b) for a in centers for b in centers)<.01: raise ValueError('UNOBSERVABLE_METRIC_BASELINE')
    return np.array(extrinsics,dtype=np.float32),np.array(intrinsics,dtype=np.float32)

def surface_samples(depth,confidence,ext,intrinsics,observation):
    depth=np.asarray(depth);confidence=np.asarray(confidence)
    if depth.ndim!=3 or depth.shape[0]!=3 or confidence.shape!=depth.shape: raise ValueError('DEPTH_OUTPUT_SHAPE')
    if np.asarray(ext).shape not in ((3,3,4),(3,4,4)) or np.asarray(intrinsics).shape!=(3,3,3): raise ValueError('CAMERA_OUTPUT_SHAPE')
    samples=[]
    for i,camera in enumerate(CAMERAS):
        h,w=depth[i].shape;k=np.asarray(intrinsics[i]);old_k=np.asarray(observation['calibration'][camera]['intrinsic'])
        matrix=np.eye(4);matrix[:3,:]=ext[i][:3,:];c2w=np.linalg.inv(matrix)
        width,height=observation['calibration'][camera]['resolution']
        finite=np.isfinite(confidence[i]) & np.isfinite(depth[i]) & (depth[i]>0)
        if not finite.any(): continue
        threshold=float(np.quantile(confidence[i][finite],.4)) # rank only, not calibrated confidence
        for v in np.unique(np.linspace(0,h-1,24).astype(int)):
            for u in np.unique(np.linspace(0,w-1,24).astype(int)):
                if not finite[v,u] or confidence[i,v,u]<threshold: continue
                ray=np.linalg.solve(k,[u,v,1.]);pixel=old_k@ray;pixel=pixel[:2]/pixel[2]
                if not 0<=pixel[0]<width or not 0<=pixel[1]<height: continue
                point=c2w[:3,:3]@(ray*depth[i,v,u])+c2w[:3,3]
                if not np.isfinite(point).all(): continue
                samples.append({'camera':camera,'pixel':pixel.tolist(),'point_world_m':point.tolist(),
                    'confidence_raw':float(confidence[i,v,u]),'observation_id':observation['observation_id']})
    return samples

def compute(wire):
    import torch
    from depth_anything_3.api import DepthAnything3
    current=wire['observations'][-1];config=wire['learned'];ext,k=calibrated_cameras(current)
    if not torch.cuda.is_available(): raise ValueError('CUDA_UNAVAILABLE_NO_CPU_FALLBACK')
    torch.cuda.reset_peak_memory_stats();start=time.monotonic()
    model=DepthAnything3.from_pretrained('/weights',local_files_only=True).to(config['device']).eval()
    torch.cuda.synchronize();loaded=time.monotonic()
    with torch.inference_mode():
        prediction=model.inference(image=['/input/'+current['images'][c] for c in CAMERAS],
            extrinsics=ext,intrinsics=k,align_to_input_ext_scale=True,infer_gs=False,
            process_res=config['process_res'],process_res_method='upper_bound_resize',export_dir=None)
    torch.cuda.synchronize();inferred=time.monotonic()
    if prediction.conf is None: raise ValueError('DEPTH_CONFIDENCE_MISSING')
    if not np.allclose(prediction.extrinsics,ext[:,:3,:],atol=1e-4): raise ValueError('CAMERA_SCALE_ALIGNMENT_FAILED')
    samples=surface_samples(prediction.depth,prediction.conf,prediction.extrinsics,prediction.intrinsics,current)
    return {'backend':'da3_small_v1','observation_id':current['observation_id'],
        'captured_monotonic':current['captured_monotonic'],'scene_healthy':bool(samples),
        'entities':{},'surface_samples':samples,'robot_state':current['state'],
        'history_semantics':'current frozen three-view pretrained depth; metric scale from calibrated baseline',
        'geometry_only':True,'task_identity_verified':False,
        'resource_metrics':{'load_s':loaded-start,'inference_s':inferred-loaded,
            'worker_compute_s':time.monotonic()-start,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),
            'peak_reserved_bytes':torch.cuda.max_memory_reserved(), 'process_res':config['process_res'],
            'cold_process':True, 'device':torch.cuda.get_device_name(), 'weights_sha256':config['weights_sha256'],
            'source_revision':config['source_revision']}}
