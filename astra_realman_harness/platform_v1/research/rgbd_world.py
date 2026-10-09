"""CPU RGB-D object surfels. Measured sensor geometry, never simulator truth.

Dynamic instances are remeasured from current depth and never accumulated in the
static layer. Only verified public-plane support is eligible for static fusion.
Unclassified geometry is current-only; hidden object volume remains unknown.
"""
import time
import cv2
import numpy as np
from .contracts import clone
from .da3_geometry import CAMERAS, calibrated_cameras
from .object_world import decode_mask, encode_mask, project
from .object_tracking import track_view, fk_camera_consistency, appearance_likelihood, bbox

BACKEND='rgbd_object_state_v1'


def reject_identity_conflicts(entities):
    ids=list(entities);ambiguous=set()
    for index,a in enumerate(ids):
        for b in ids[index+1:]:
            for va in entities[a]['views']:
                for vb in entities[b]['views']:
                    if va['camera']!=vb['camera']:continue
                    ma=decode_mask(va['mask']);mb=decode_mask(vb['mask'])
                    if (ma&mb).sum()>.25*max(1,min(ma.sum(),mb.sum())):ambiguous.update((a,b))
    for identity in ambiguous:
        entities[identity].update(status='unknown',point_world_m=None,bounds_world_m=None,
            surface_cloud=[],partial_current_surface_cloud=[],measurement_kind='unknown',reason='INSTANCE_MASK_COMPETITION')


def voxelize(points, size, maximum):
    p=np.asarray(points,float).reshape(-1,3)
    if not len(p):return np.empty((0,3))
    _,ids=np.unique(np.floor(p/size).astype(np.int32),axis=0,return_index=True)
    p=p[ids]
    if len(p)>maximum:p=p[np.linspace(0,len(p)-1,maximum,dtype=int)]
    return p


def backproject(depth, valid, mask, ext, k):
    v,u=np.where(valid & mask.astype(bool))
    if not len(u):return np.empty((0,3))
    rays=np.column_stack([u,v,np.ones(len(u))])@np.linalg.inv(k).T
    local=rays*depth[v,u,None];pose=np.linalg.inv(ext)
    return local@pose[:3,:3].T+pose[:3,3]


def measure_entity(entity,views,observation,depths,cfg,ext,k):
    samples=[];centers=[];evidence=[];usable=[]
    for v in views:
        camera=v['camera'];i=CAMERAS.index(camera);depth,valid,meta=depths[camera]
        mask=decode_mask(v['mask']);mask=cv2.erode(mask,np.ones((3,3),np.uint8))
        count=int((valid & (mask>0)).sum());den=int(mask.sum());fraction=count/max(1,den)
        row={'camera':camera,'observation_id':observation['observation_id'],
            'mask_source':v.get('producer','current_2d_tracking'),'RGB_source_sha256':meta['aligned_rgb_sha256'],
            'depth_sha256':meta['depth']['sha256'],'validity_sha256':meta['validity']['sha256'],
            'captured_monotonic':observation['captured_monotonic'],'mask_pixels':den,
            'valid_depth_pixels':count,'depth_support_fraction':fraction,'status':'unknown'}
        if entity['identity_status']=='hypothesis' and count>=cfg['min_points_per_view'] and fraction>=cfg['min_depth_fraction']:
            pts=backproject(depth,valid,mask,ext[i],k[i])
            inside=np.all((pts>=cfg['domain_min_m']) & (pts<=cfg['domain_max_m']),axis=1);pts=pts[inside]
            if len(pts)>=cfg['min_points_per_view']:
                pts=voxelize(pts,cfg['voxel_m'],cfg['max_entity_points'])
                samples.append(pts);centers.append(np.median(pts,axis=0));usable.append(camera)
                row.update(status='measured_surface',points=len(pts),surface_median_world_m=centers[-1].tolist())
        evidence.append(row)
    out={**clone(entity),'instance_id':entity['entity_id'],'observation_id':observation['observation_id'],
        'captured_monotonic':observation['captured_monotonic'],'views':clone(views),
        'current_evidence':evidence,'status':'unknown','point_world_m':None,'surface_cloud':[],
        'bounds_world_m':None,'uncertainty_radius_m':None,'measurement_kind':'unknown',
        'held_relation':'unknown','motion':'unknown','reason':'INSUFFICIENT_CURRENT_MULTIVIEW_DEPTH',
        'uncertainty_semantics':'observed surface extent, discretization and view disagreement; hidden volume unknown',
        'visibility':{v['camera']:'visible_RGB_support' for v in views}}
    out['partial_current_surface_cloud']=voxelize(np.concatenate(samples),cfg['voxel_m'],cfg['max_entity_points']).tolist() if samples else []
    if len(samples)>=cfg['min_views']:
        points=voxelize(np.concatenate(samples),cfg['voxel_m'],cfg['max_entity_points'])
        lo,hi=np.quantile(points,[.01,.99],axis=0);center=(lo+hi)/2
        disagreement=max(np.linalg.norm(p-center) for p in centers)
        if max(hi-lo)<=cfg['max_spread_m'] and disagreement<=cfg['max_view_center_disagreement_m']:
            out.update(status='coarse',point_world_m=center.tolist(),bounds_world_m=[lo.tolist(),hi.tolist()],
                surface_cloud=points.tolist(),measurement_kind='current_depth_region',
                uncertainty_radius_m=max(cfg['voxel_m']*2,float(disagreement)),
                reason='CURRENT_RGBD_SURFACE_BOUNDS_NOT_COMPLETE_OBJECT_VOLUME',
                center_semantics='observed-surface bounds midpoint; not guaranteed object or grasp center',
                contributing_views=usable,view_disagreement_m=float(disagreement))
        else:out['reason']='CURRENT_DEPTH_SPREAD_OR_ASSOCIATION_CONFLICT'
    return out


def cross_view_candidate(seed,old_rgb,current_rgb,anchor,depths,ext,k,cfg,tracker):
    """Recover only a UNIQUE current RGB component supported by CURRENT metric 3D.

    No old world-position prior, mask warp, GT or weaker 2D template threshold.
    Multiple geometrically plausible matches remain unknown.
    """
    from scipy.spatial import cKDTree
    camera=seed['camera'];i=CAMERAS.index(camera)
    likelihood=appearance_likelihood(old_rgb,current_rgb,decode_mask(seed['mask']))
    n,labels,stats,_=cv2.connectedComponentsWithStats((likelihood>=tracker['appearance_score_min']).astype(np.uint8),8)
    anchor=np.asarray(anchor).reshape(-1,3);uv,z=project(anchor,ext[i],k[i])
    h,w=likelihood.shape;pixel=np.rint(uv).astype(int)
    inside=(z>0)&(pixel[:,0]>=0)&(pixel[:,0]<w)&(pixel[:,1]>=0)&(pixel[:,1]<h)
    pixel=pixel[inside]
    if not len(pixel):return None,{'status':'unknown','reason':'CURRENT_ANCHOR_OUT_OF_VIEW'}
    depth,valid,_=depths[camera];accepted=[];tree=cKDTree(anchor)
    for component in range(1,n):
        if stats[component,cv2.CC_STAT_AREA]<18:continue
        mask=(labels==component).astype(np.uint8);expanded=cv2.dilate(mask,np.ones((5,5),np.uint8))
        overlap=float(expanded[pixel[:,1],pixel[:,0]].mean())
        if overlap<.4:continue
        interior=cv2.erode(mask,np.ones((3,3),np.uint8))
        if (valid & (interior>0)).sum()<cfg['min_points_per_view']:continue
        points=backproject(depth,valid,interior,ext[i],k[i]);points=voxelize(points,cfg['voxel_m'],cfg['max_entity_points'])
        distance=float(np.median(tree.query(points,k=1)[0]))
        if distance<=cfg['max_view_center_disagreement_m']:
            accepted.append((mask,overlap,distance))
    if len(accepted)!=1:return None,{'status':'unknown','reason':'NO_UNIQUE_CURRENT_RGBD_MATCH','plausible_candidates':len(accepted)}
    mask,overlap,distance=accepted[0]
    return mask,{'status':'current_multiview_association_hypothesis','reason':'UNIQUE_CURRENT_RGBD_COMPONENT',
        'projected_anchor_support_fraction':overlap,'current_surface_nearest_distance_m':distance}


def scene_layers(observation,depths,entities,plane,cfg,ext,k,previous=None):
    current=[];unassigned=[];excluded=[]
    for camera in CAMERAS:
        i=CAMERAS.index(camera);depth,valid,_=depths[camera]
        object_mask=np.zeros(depth.shape,np.uint8)
        for e in entities.values():
            for v in e['views']:
                if v['camera']==camera and e['kind']=='object':
                    object_mask |= cv2.dilate(decode_mask(v['mask']),np.ones((5,5),np.uint8))
        # Fixed stride for bounded CPU/memory, same geometry available to every group.
        mask=np.zeros(depth.shape,np.uint8);mask[::4,::4]=1
        mask &= 1-object_mask
        pts=backproject(depth,valid,mask,ext[i],k[i])
        pts=pts[np.all((pts>=cfg['domain_min_m']) & (pts<=cfg['domain_max_m']),axis=1)]
        error=np.abs(pts@np.array(plane['normal'])+plane['offset'])
        current.append(pts[error<=cfg['table_band_m']]);unassigned.append(pts[error>cfg['table_band_m']])
        excluded.append({'camera':camera,'dynamic_mask_excluded_pixels':int(object_mask.sum())})
    plane_points=voxelize(np.concatenate(current),cfg['voxel_m'],cfg['max_background_points'])
    current_unassigned=voxelize(np.concatenate(unassigned),cfg['voxel_m'],4096)
    now=observation['captured_monotonic'];memory={}
    if previous:
        for p,stamp in zip(previous['points'],previous['last_seen_monotonic']):
            if now-stamp<=cfg['max_point_age_s']:memory[tuple(np.floor(np.array(p)/cfg['voxel_m']).astype(int))]=(p,stamp)
    for p in plane_points:memory[tuple(np.floor(p/cfg['voxel_m']).astype(int))]=(p.tolist(),now)
    values=sorted(memory.values(),key=lambda x:x[1],reverse=True)[:cfg['max_background_points']]
    return {'static':{'kind':'public_plane_supported_surfels_only','points':[p for p,t in values],
            'last_seen_monotonic':[t for p,t in values],'current_points':plane_points.tolist(),
            'current_support_count':len(plane_points),'unknown_outside_observed_support':True,
            'does_not_include_objects_or_unclassified_geometry':True},
        'unassigned_current':{'points':current_unassigned.tolist(),'captured_monotonic':now,
            'temporal_fusion':False,'semantics':'unclassified current surface, never assumed static'},
        'dynamic_exclusion':excluded}


def quality(observation,entities,layers,plane,cfg):
    pts=np.asarray(layers['static']['current_points'],float).reshape(-1,3)
    # Plane filter is not an independent correctness proof. Object multiview
    # disagreement and holdout/GT scores are separate; no automatic task admission.
    available=any(e['status']=='coarse' for e in entities.values())
    return {'numeric_valid':'pass' if available else 'unknown',
        'self_consistent':'pass' if available and all(e['status']=='coarse' for e in entities.values()) else 'unknown',
        'task_usable':'unknown','reason':['TASK_SEMANTICS_AND_PRECONTACT_CLEARANCE_NOT_YET_ACCEPTED'],
        'observation_id':observation['observation_id'],'grants_execution':False,
        'table_current_support_points':len(pts),'plane_check_is_filter_not_independent_score':True}


def build(observation,entities,masks,depths,config,plane,semantic_source):
    start=time.monotonic();cfg=config['geometry'];ext,k=calibrated_cameras(observation)
    if any(c['axes']!='SAPIEN +x forward,+y left,+z up' for c in observation['calibration'].values()):raise ValueError('CAMERA_AXES')
    ids=[e['entity_id'] for e in entities]
    if len(set(ids))!=len(ids):raise ValueError('DUPLICATE_INSTANCE')
    result={}
    for e in entities:
        views=[]
        for v in e['views']:
            rec=masks.get((e['entity_id'],v['camera']))
            if not rec:continue
            if rec['observation_id']!=observation['observation_id']:raise ValueError('RGBD_MASK_TIME_BINDING')
            if decode_mask(rec['mask']).shape!=depths[v['camera']][0].shape:raise ValueError('RGBD_MASK_PIXEL_GRID')
            views.append({**clone(v),**clone(rec),'observation_id':observation['observation_id']})
        result[e['entity_id']]=measure_entity(e,views,observation,depths,cfg,ext,k)
        result[e['entity_id']]['tracking_seeds']=clone(views)
        result[e['entity_id']]['semantic_source']=clone(semantic_source)
    reject_identity_conflicts(result)
    layers=scene_layers(observation,depths,result,plane,cfg,ext,k)
    return {'backend':'semantic_lwh_v1','geometry_backend':BACKEND,'observation_id':observation['observation_id'],
        'captured_monotonic':observation['captured_monotonic'],'robot_state':clone(observation['state']),
        'entities':result,'scene_layers':layers,'scene_healthy':True,'geometry_only':False,'task_identity_verified':False,
        'geometry_quality':quality(observation,result,layers,plane,cfg),'public_plane':clone(plane),
        'semantic_evidence_id':semantic_source['evidence_id'],'semantic_source':clone(semantic_source),
        'history_semantics':'current RGB-D surfaces with explicit instance association hypothesis',
        'resource_metrics':{'build_compute_s':time.monotonic()-start,'Astra_calls':0,'DA3_calls':0,'SAM_calls':0},
        'rebuild_needed':any(e['status']=='unknown' for e in result.values()),'rebuild_dispatches_model':False}


def expected_visibility(historical,camera,ext,k,depths):
    points=np.asarray(historical.get('surface_cloud',[])).reshape(-1,3)
    if not len(points):return {'status':'unknown','reason':'NO_HISTORICAL_SURFACE'}
    uv,z=project(points,ext,k);depth,valid,_=depths[camera];h,w=depth.shape
    pix=np.rint(uv).astype(int);inside=(z>0)&(pix[:,0]>=0)&(pix[:,0]<w)&(pix[:,1]>=0)&(pix[:,1]<h)
    if not inside.any():return {'status':'out_of_view','source':'world reprojection'}
    pix=pix[inside];z=z[inside];d=depth[pix[:,1],pix[:,0]];good=valid[pix[:,1],pix[:,0]]
    if good.mean()<.4:return {'status':'depth_unknown','valid_fraction':float(good.mean())}
    occluded=float(np.mean(d[good]<z[good]-.01))
    return {'status':'occluded' if occluded>.6 else 'unknown_association',
        'nearer_depth_fraction':occluded,'source':'current metric depth vs historical projected surface'}


def update(reference,previous,current,images,depths,read_images,completed_at,feedback):
    start=time.monotonic()
    if current['captured_monotonic']<completed_at:raise ValueError('OBSERVATION_BEFORE_COMPLETION')
    if current['captured_monotonic']<=previous['captured_monotonic']:raise ValueError('NONCAUSAL_UPDATE')
    if reference['observation_id']!=previous['observation_id']:raise ValueError('REFERENCE_OBSERVATION_MISMATCH')
    if feedback and feedback['completed_monotonic']>current['captured_monotonic']:raise ValueError('FUTURE_EXECUTION_FEEDBACK')
    cfg=reference['object_config']['geometry'];tracker=reference['object_config']['tracker']
    ext,k=calibrated_cameras(current);cache={};entities={};fk=fk_camera_consistency(previous,current)
    for identity,e in reference['entities'].items():
        views=[];seeds=[];evidence=[]
        historical=({'surface_cloud':e['surface_cloud'],'point_world_m':e['point_world_m'],
            'observation_id':e['observation_id'],'captured_monotonic':e['captured_monotonic']}
            if e['status']=='coarse' else clone(e.get('historical_geometry',{})))
        for seed in e['tracking_seeds']:
            oid=seed['observation_id'];camera=seed['camera']
            if oid not in cache:cache[oid]=read_images(oid)
            track=track_view(cache[oid][camera],images[camera],decode_mask(seed['mask']),camera,tracker)
            track.update(camera=camera,observation_id=current['observation_id'],source_observation_id=oid)
            evidence.append(track)
            if track['mask'] is not None:
                view={'camera':camera,'mask':track['mask'],'bbox':track['bbox'],'observation_id':current['observation_id'],
                    'producer':'CURRENT_RGB_LIGHT_TRACKER','visibility':track['visibility']}
                views.append(view);seeds.append(view)
            else:seeds.append(clone(seed))
        tentative=measure_entity(e,views,current,depths,cfg,ext,k)
        anchor=tentative['partial_current_surface_cloud']
        if anchor:
            # One nonrecursive pass; successful proposals do not bootstrap further
            # proposals in this same frame, preventing chain reinforcement.
            for index,seed in enumerate(e['tracking_seeds']):
                camera=seed['camera']
                if any(v['camera']==camera for v in views):continue
                mask,association=cross_view_candidate(seed,cache[seed['observation_id']][camera],images[camera],
                    anchor,depths,ext,k,cfg,tracker)
                evidence[index]['cross_view_current_rgbd']=association
                if mask is not None:
                    view={'camera':camera,'mask':encode_mask(mask),'bbox':bbox(mask),
                        'observation_id':current['observation_id'],'producer':'CURRENT_RGBD_VERIFIED_RGB_COMPONENT',
                        'visibility':'visible_support','association':association}
                    views.append(view);seeds[index]=view
        measured=measure_entity(e,views,current,depths,cfg,ext,k)
        measured.update(tracking_seeds=seeds,tracking_evidence=evidence,historical_geometry=historical)
        for camera in CAMERAS:
            i=CAMERAS.index(camera)
            if not any(v['camera']==camera for v in views):
                measured['visibility'][camera]=expected_visibility(historical,camera,ext[i],k[i],depths)['status']
        if measured['status']=='coarse' and historical.get('point_world_m'):
            displacement=float(np.linalg.norm(np.array(measured['point_world_m'])-historical['point_world_m']))
            measured.update(displacement_from_previous_measurement_m=displacement,
                motion='moving' if displacement>cfg['movement_threshold_m'] else 'small_change_or_static')
        # No frames of a moving instance are accumulated into a static map or into
        # a stationary object cloud; only the current measured cloud is published.
        if fk['status']!='pass' or (feedback and not feedback['ok']):
            measured.update(status='unknown',point_world_m=None,surface_cloud=[],bounds_world_m=None,
                measurement_kind='unknown',reason='FK_OR_EXECUTION_FEEDBACK_UNRELIABLE')
        measured['held_relation']='unknown'
        entities[identity]=measured
    reject_identity_conflicts(entities)
    layers=scene_layers(current,depths,entities,reference['public_plane'],cfg,ext,k,reference['scene_layers']['static'])
    return {**clone(reference),'entities':entities,'scene_layers':layers,'observation_id':current['observation_id'],
        'captured_monotonic':current['captured_monotonic'],'robot_state':clone(current['state']),
        'geometry_quality':quality(current,entities,layers,reference['public_plane'],cfg),
        'fk_camera_check':fk,'execution_feedback':clone(feedback),'history_semantics':'current RGB-D surfaces; stale geometry explicitly historical',
        'rebuild_needed':any(e['status']=='unknown' for e in entities.values()),'rebuild_dispatches_model':False,
        'resource_metrics':{'update_compute_s':time.monotonic()-start,'Astra_calls':0,'DA3_calls':0,'SAM_calls':0}}
