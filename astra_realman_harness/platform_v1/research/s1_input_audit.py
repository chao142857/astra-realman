"""Saved public-input audit only. RGB reference masks are scoring annotations.

Never pass these annotations to E0 or use them to construct its World State.
"""
import numpy as np
from .contracts import digest
from .da3_geometry import CAMERAS, calibrated_cameras
from .object_world import decode_mask
from .rgbd_world import backproject
from .model_context import observation_view
from .fusion import semantic_schema

def perception_bundle(store, observation_id, task_instruction):
    """Materialize E0-only public view + selectors; does not dispatch a Broker."""
    o=store.get(observation_id)
    sources=[]
    for c in CAMERAS:
        _,r=store.image(observation_id,c)
        sources.append({'camera':c,'source_sha256':r['sha256'],'observation_id':observation_id})
    request={'backend':'existing_codex_infer','role':'semantic_e0','instruction':task_instruction,
        'images':[{'observation_id':observation_id,'camera':c,'roi':None} for c in CAMERAS],
        'evidence_ids':[],'world_id':None,'output_schema':semantic_schema(),'timeout_s':90}
    return {'version':'astra.s1_e0_input_review.v1','observation':observation_view(o,'semantic_e0'),
        'rgb_sources':sources,'request':request,'request_sha256':digest(request),
        'model_calls':0,'request_status':'PREPARED_NOT_SENT'}

def coverage(store, observation_id, annotation, public_plane):
    o=store.get(observation_id)
    if annotation['version']!='astra.s1_rgb_reference.v1' or annotation['observation_id']!=observation_id or annotation['source']!='INDEPENDENT_CURRENT_RGB_ANNOTATION_NOT_MODEL_INPUT':
        raise ValueError('RGB_REVIEW_BINDING')
    normal=np.asarray(public_plane['normal'],float)
    if normal.shape!=(3,) or not np.isfinite(normal).all() or abs(np.linalg.norm(normal)-1)>1e-6 or not np.isfinite(public_plane['offset']):
        raise ValueError('PUBLIC_PLANE_REQUIRED')
    ext,k=calibrated_cameras(o);seen=set();rows=[];fixed_red=[]
    for e in annotation['entities']:
        identity=e['reference_id']
        if identity in seen:raise ValueError('DUPLICATE_REFERENCE')
        seen.add(identity);views=[];cameras=set()
        for v in e['views']:
            c=v['camera']
            if c in cameras or c not in CAMERAS:raise ValueError('REFERENCE_CAMERA')
            cameras.add(c);_,rgb=store.image(observation_id,c)
            if v['image_sha256']!=rgb['sha256']:raise ValueError('REFERENCE_RGB_HASH')
            mask=decode_mask(v['mask']);d,valid,_=store.depth(observation_id,c)
            if mask.shape!=d.shape:raise ValueError('REFERENCE_PIXEL_GRID')
            points=backproject(d,valid,mask,ext[CAMERAS.index(c)],k[CAMERAS.index(c)])
            foreground=int(np.sum(points@normal+public_plane['offset']>.005))
            y,x=np.where(mask);box=[int(x.min()),int(y.min()),int(x.max()+1),int(y.max()+1)] if len(x) else None
            views.append({'camera':c,'RGB_pixels':int(mask.sum()),'valid_foreground_depth_pixels':foreground,
                'bbox_xyxy_pixels':box,'has_12_pixels':foreground>=12})
            if c=='fixed' and e['appearance']=='red_cuboid' and foreground>=12:fixed_red.append((identity,box))
        for c in CAMERAS:
            if c not in cameras:views.append({'camera':c,'RGB_pixels':None,'valid_foreground_depth_pixels':None,
                'bbox_xyxy_pixels':None,'has_12_pixels':False,'status':'UNKNOWN_NOT_ANNOTATED'})
        rows.append({'reference_id':identity,'appearance':e['appearance'],'cross_view_reference_status':e['cross_view_reference_status'],
            'views':views,'views_with_12_pixels':sum(v['has_12_pixels'] for v in views)})
    red=[r for r in rows if r['appearance']=='red_cuboid'];blue=[r for r in rows if r['appearance']=='blue_cuboid']
    gate=len(red)==2 and len(blue)>=1 and all(r['views_with_12_pixels']>=2 for r in red+blue)
    order=None
    if len(fixed_red)==2:
        a,b=sorted(fixed_red,key=lambda r:r[1][0])
        # Conservative automatic sufficient condition; overlapping boxes require
        # review and stay unknown here, never GT-resolved or silently rearranged.
        if a[1][2]<=b[1][0]:order={'left_reference':a[0],'right_reference':b[0],'source':'fixed RGB disjoint x support'}
    gate=bool(gate and order is not None)
    return {'status':'PERCEPTION_INPUT_ELIGIBLE' if gate else 'DATA_INSUFFICIENT',
        'observation_id':observation_id,'annotation_sha256':digest(annotation),'rows':rows,
        'fixed_red_order':order,'Astra_calls':0,'grants_planning':False,'grants_execution':False,
        'identity_reference_unknowns':[r['reference_id'] for r in rows if r['cross_view_reference_status']!='verified_from_RGB'],
        'not_model_input':True,'next':'separate E0 authorization' if gate else 'stop; no E0, rearrange or retry'}
