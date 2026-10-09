"""Semantic bbox -> current sensor mask. Classical geometry, zero model calls.

This is a binding/measurement adapter for WorldHead.build_rgbd, not a second
estimator. A bbox is a prompt, never a mask or a measured object center.
"""
import io
import time
import numpy as np
import jsonschema
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from .contracts import clone, digest
from .da3_geometry import CAMERAS, calibrated_cameras
from .fusion import semantic_schema
from .object_world import encode_mask

METHOD = 'bbox_current_rgbd_components_v1'
PARAMETERS = {'min_points': 12, 'public_table_band_m': .005,
              'adjacent_3D_distance_max_m': .01}


def component_mask(depth, valid, ext, intrinsic, box, plane):
    """Unique 4-neighbor metric component above a public oriented plane.

    Reject clipped/ROI-truncated support. No largest-component tie breaking.
    Exposed separately for adversarial array tests, not alternate geometry.
    """
    normal=np.asarray(plane['normal'],float)
    if normal.shape!=(3,) or not np.isfinite(normal).all() or abs(np.linalg.norm(normal)-1)>1e-6 or not np.isfinite(plane['offset']):
        raise ValueError('PUBLIC_UNIT_PLANE_REQUIRED')
    if len(box)!=4 or not np.isfinite(box).all() or not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:
        raise ValueError('REGION_BBOX')
    info={'status':'unknown','reason':'CLIPPED_BBOX','qualifying_components':0}
    if box[0]==0 or box[1]==0 or box[2]==1 or box[3]==1:return None,info
    height,width=depth.shape
    x0,y0=np.floor(np.array(box[:2])*[width,height]).astype(int)
    x1,y1=np.ceil(np.array(box[2:])*[width,height]).astype(int)
    yy,xx=np.mgrid[y0:y1,x0:x1]
    rays=np.stack([xx,yy,np.ones_like(xx)],axis=-1)@np.linalg.inv(intrinsic).T
    local=rays*depth[y0:y1,x0:x1,None];pose=np.linalg.inv(ext)
    points=local@pose[:3,:3].T+pose[:3,3]
    support=(valid[y0:y1,x0:x1] & np.isfinite(points).all(axis=2) &
             (points@normal+plane['offset']>PARAMETERS['public_table_band_m']))
    count=int(support.sum());info.update(roi_xyxy_pixels=[int(x0),int(y0),int(x1),int(y1)],foreground_pixels=count)
    if count<PARAMETERS['min_points']:
        info['reason']='INSUFFICIENT_FOREGROUND_DEPTH';return None,info
    index=np.full(support.shape,-1,int);index[support]=np.arange(count)
    edges=[]
    for a,b in [((slice(None,-1),slice(None)),(slice(1,None),slice(None))),
                ((slice(None),slice(None,-1)),(slice(None),slice(1,None)))]:
        good=support[a]&support[b]&(np.linalg.norm(points[a]-points[b],axis=-1)<=PARAMETERS['adjacent_3D_distance_max_m'])
        edges.append((index[a][good],index[b][good]))
    rows=np.concatenate([e[0] for e in edges]);cols=np.concatenate([e[1] for e in edges])
    graph=coo_matrix((np.ones(len(rows),np.uint8),(rows,cols)),shape=(count,count)).tocsr()
    total,labels=connected_components(graph,directed=False)
    sizes=np.bincount(labels,minlength=total);candidates=np.flatnonzero(sizes>=PARAMETERS['min_points'])
    info.update(component_sizes=sorted(sizes.tolist(),reverse=True),qualifying_components=len(candidates))
    if len(candidates)!=1:
        info['reason']='NO_UNIQUE_FOREGROUND_COMPONENT';return None,info
    mask_roi=np.zeros(support.shape,np.uint8);mask_roi[support]=(labels==candidates[0]).astype(np.uint8)
    if mask_roi[0].any() or mask_roi[-1].any() or mask_roi[:,0].any() or mask_roi[:,-1].any():
        info['reason']='COMPONENT_TRUNCATED_BY_BBOX';return None,info
    mask=np.zeros(depth.shape,np.uint8);mask[y0:y1,x0:x1]=mask_roi
    info.update(status='measured_mask_hypothesis',reason='UNIQUE_CURRENT_METRIC_COMPONENT',mask_pixels=int(mask.sum()))
    return mask,info


def prepare_masks(store, observation_id, semantic_evidence_id, public_plane):
    start=time.monotonic();o=store.get(observation_id);e=store.get_evidence(semantic_evidence_id)
    if public_plane is None:raise ValueError('PUBLIC_PLANE_REQUIRED')
    if e['role']!='semantic_e0' or e['observation_ids']!=[observation_id]:raise ValueError('FROZEN_SEMANTIC_INPUT_REQUIRED')
    jsonschema.validate(e['result'],semantic_schema())
    attachments={a['id']:a for a in e['attachments']}
    if len(e['attachments'])!=3 or len(attachments)!=3 or {a['camera'] for a in attachments.values()}!=set(CAMERAS):
        raise ValueError('THREE_FROZEN_RGB_REQUIRED')
    for a in attachments.values():
        data,r=store.image(observation_id,a['camera']);resolution=o['calibration'][a['camera']]['resolution']
        if a['observation_id']!=observation_id or a['source_sha256']!=r['sha256'] or a['transform']['crop_xyxy_pixels'] is not None:
            raise ValueError('FROZEN_IMAGE_BINDING')
        if a['transform']['source_resolution']!=resolution or list(Image.open(io.BytesIO(data)).size)!=resolution:
            raise ValueError('IMAGE_RESOLUTION_BINDING')
        if ('width' in a and [a['width'],a['height']]!=resolution) or ('selected_intrinsic' in a and a['selected_intrinsic']!=o['calibration'][a['camera']]['intrinsic']):
            raise ValueError('ATTACHMENT_PIXEL_GRID_BINDING')
    if any(c['axes']!='SAPIEN +x forward,+y left,+z up' for c in o['calibration'].values()):raise ValueError('CAMERA_AXES')
    ext,intrinsic=calibrated_cameras(o)
    depths={c:store.depth(observation_id,c) for c in CAMERAS}
    masks={};rows=[];seen=set()
    for entity in e['result']['entities']:
        identity=entity['entity_id']
        if identity in seen:raise ValueError('DUPLICATE_INSTANCE_ID')
        seen.add(identity);cameras=set()
        for view in entity['views']:
            if view['attachment_id'] not in attachments:raise ValueError('UNSEEN_SEMANTIC_VIEW')
            a=attachments[view['attachment_id']];camera=a['camera']
            if camera in cameras:raise ValueError('DUPLICATE_ENTITY_VIEW')
            cameras.add(camera);box=view['bbox']
            if not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:raise ValueError('REGION_BBOX')
            row={'entity_id':identity,'camera':camera,'attachment_id':a['id'],'bbox':clone(box),
                 'status':'unknown','reason':'UNRESOLVED_IDENTITY'}
            if entity['identity_status']!='hypothesis':pass
            elif entity['kind']!='object':row['reason']='BBOX_IS_NOT_REGION_PIXEL_SUPPORT'
            elif view['visibility']!='visible':row['reason']='PARTIAL_OR_UNKNOWN_SEMANTIC_VIEW'
            else:
                i=CAMERAS.index(camera);d,v,meta=depths[camera]
                mask,info=component_mask(d,v,ext[i],intrinsic[i],box,public_plane);row.update(info)
                if mask is not None:
                    encoded=encode_mask(mask)
                    masks[identity,camera]={'entity_id':identity,'camera':camera,'observation_id':observation_id,
                        'mask':encoded,'producer':METHOD,'image_sha256':a['source_sha256'],
                        'bbox_prompt_normalized':clone(box),'semantic_evidence_id':semantic_evidence_id,
                        'semantic_provenance':e['provenance'],'depth_sha256':meta['depth']['sha256'],
                        'validity_sha256':meta['validity']['sha256'],'mask_sha256':digest(encoded),
                        'captured_monotonic':o['captured_monotonic']}
            rows.append(row)
    # Two identity claims for substantially the same pixels stay unresolved.
    conflict=set()
    from .object_world import decode_mask
    keys=list(masks)
    for i,a in enumerate(keys):
        for b in keys[i+1:]:
            if a[1]!=b[1]:continue
            ma,mb=decode_mask(masks[a]['mask']),decode_mask(masks[b]['mask'])
            if (ma&mb).sum()>.25*min(ma.sum(),mb.sum()):conflict.update((a,b))
    for key in conflict:
        del masks[key]
        for row in rows:
            if (row['entity_id'],row['camera'])==key:row.update(status='unknown',reason='INSTANCE_MASK_COMPETITION')
    return masks,{'version':METHOD,'observation_id':observation_id,'semantic_evidence_id':semantic_evidence_id,
        'semantic_provenance':e['provenance'],'parameters':clone(PARAMETERS),'rows':rows,'mask_count':len(masks),
        'wall_s':time.monotonic()-start,'Astra_calls':0,'SAM_calls':0,'DA3_calls':0,'grants_execution':False,
        'limitations':['bbox association remains semantic hypothesis','touching surfaces may form one component',
                      'partial, clipped and planar region bbox support rejected','not an E0 capability evaluation']}
