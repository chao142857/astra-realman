"""Run-scoped interaction evidence on existing RGB-D WorldHead; never control/GT."""
import hashlib
import numpy as np
import cv2
from scipy import ndimage
from scipy.spatial.transform import Rotation
from .contracts import clone,digest
from . import rgbd_world as rw
from sim_skills.full_pnp import rgb

def green_mask(image):
 a=image.astype(float);r,g,b=a[...,0],a[...,1],a[...,2]
 mask=(g>45)&(g>1.35*r)&(g>1.3*b) # unchanged declared toy-scene detector, not generic semantics
 labels,n=ndimage.label(mask);counts=np.bincount(labels.ravel());counts[0]=0
 order=np.argsort(counts)[::-1]
 if counts[order[0]]<18 or len(order)>1 and counts[order[1]]>=.35*counts[order[0]]:return None
 m=(labels==order[0]).astype(np.uint8);v,u=np.where(m)
 if min(u)<=1 or min(v)<=1 or max(u)>=m.shape[1]-2 or max(v)>=m.shape[0]-2:return None
 return m

def destination(reference,current,images,depths,read_images):
 old=reference.get('pnp_destination',{})
 semantic=old.get('semantic_support')
 if semantic is None:
  oid=reference['semantic_source']['binding']['observation_ids'][0]
  source=read_images(oid)
  for req in reference.get('semantic_requests',[]):
   if req['kind']!='new_planar_region' or req['bbox'] is None:continue
   m=green_mask(source[req['camera']])
   if m is None:continue
   y,x=np.where(m);h,w=m.shape;x0,y0,x1,y1=req['bbox']
   fraction=float(((x>=x0*w)&(x<x1*w)&(y>=y0*h)&(y<y1*h)).mean())
   if fraction>=.5:
    semantic={'evidence_id':reference['semantic_evidence_id'],'request':clone(req),'observation_id':oid,
     'source_image_array_sha256':hashlib.sha256(source[req['camera']].tobytes()).hexdigest(),'actual_green_pixels_inside_semantic_bbox_fraction':fraction};break
 if semantic is None:return {'status':'unknown','reason':'NO_MODEL_REGION_BOUND_TO_ACTUAL_GREEN_PIXELS'}
 ext,k=rw.calibrated_cameras(current);rows=[];clouds=[]
 for i,c in enumerate(rw.CAMERAS):
  mask=green_mask(images[c])
  if mask is None:continue
  depth,valid,meta=depths[c];pts=rw.backproject(depth,valid,cv2.erode(mask,np.ones((3,3),np.uint8)),ext[i],k[i])
  # Only current sensor-supported public-plane points; no truth coordinates.
  if len(pts)<12:continue
  good=abs(pts[:,2])<=.012
  if good.mean()<.8:continue
  pts=pts[good];lo,hi=np.quantile(pts,[.01,.99],axis=0);clouds.append(pts)
  rows.append({'camera':c,'observation_id':current['observation_id'],'bounds_world_m':[lo.tolist(),hi.tolist()],
    'depth_sha256':meta['depth']['sha256'],'rgb_sha256':meta['aligned_rgb_sha256'],'points':len(pts)})
 if len(rows)<2:return {'status':'unknown','reason':'CURRENT_GOAL_MULTIVIEW_DEPTH_INSUFFICIENT','semantic_support':semantic,'views':rows}
 centers=[np.mean(x['bounds_world_m'],axis=0) for x in rows]
 if max(np.linalg.norm(a-b) for a in centers for b in centers)>.02:return {'status':'unknown','reason':'GOAL_MULTIVIEW_CONFLICT','semantic_support':semantic,'views':rows}
 points=np.concatenate(clouds);lo,hi=np.quantile(points,[.01,.99],axis=0);mid=(lo+hi)/2
 if old.get('status')=='current_region' and np.linalg.norm(mid-np.array(old['point_world_m']))>.02:
  return {'status':'unknown','reason':'GOAL_ASSOCIATION_CONFLICT','semantic_support':semantic,'views':rows}
 return {'status':'current_region','point_world_m':mid.tolist(),'bounds_world_m':[lo.tolist(),hi.tolist()],
  'measurement_kind':'CURRENT_RGB_MASK_RGBD_PUBLIC_PLANE','identity':'SEMANTIC_REGION_PLUS_SHARED_TOY_RGB_HEURISTIC',
  'semantic_support':semantic,'views':rows,'observation_id':current['observation_id'],
  'unknown':'observed support only; occluded boundary and localization calibration uncertainty remain unknown'}


def local_target_support(reference,current,images,depths,read_images):
 """Target-conditioned current depth subset, not whole robot-component identity.

 Historical shape and appearance are search cues. No old XYZ becomes a fresh
 measurement; incomplete/full absence remain separate and never grant motion.
 """
 from scipy.spatial import cKDTree
 import time
 start=time.monotonic();target=reference['task_target_geometry_id'];old=reference['entities'][target]
 hist=rw._historical_entity(old);prior=reference.get('pnp_interaction',{}).get('tracking_measurement')
 if prior and prior.get('status')=='coarse' and prior.get('tracking_seeds'):
  hist=prior
 cfg=reference['object_config'];geo=cfg['geometry'];disc=cfg['discovery']
 ext,k=rw.calibrated_cameras(current);views=[];rows=[];clouds={}
 robot=np.array([current['state']['flange_pose_world'][:3],*current['state']['actual_pad_centers_world']])
 historical=np.asarray(hist.get('candidate_surface_cloud',hist.get('surface_cloud',[])),float).reshape(-1,3)
 anchor=reference.get('pnp_interaction',{}).get('FK_carry_prediction_world_m')
 # Translation prediction is only a search cue, never output geometry.
 search_center=np.median(historical,axis=0) if len(historical) else None
 local_anchor=reference.get('pnp_interaction',{}).get('carry_anchor_flange_local_m')
 if local_anchor is not None:
  flange=np.asarray(current['state']['flange_pose_world']);rotation=Rotation.from_quat(np.roll(flange[3:],-1)).as_matrix()
  search_center=flange[:3]+rotation@np.asarray(local_anchor)
 max_shift=reference['geometry_update_config']['max_association_displacement_m']
 for seed in hist.get('tracking_seeds',[]):
  c=seed['camera'];i=rw.CAMERAS.index(c)
  track=rw.track_view(read_images(seed['observation_id'])[c],images[c],rw.decode_mask(seed['mask']),c,cfg['tracker'])
  row={'camera':c,'reason':track['reason'],'association':track['association'],'source_observation_id':seed['observation_id'],
       'current_observation_id':current['observation_id'],'lk_good_features':track.get('lk_good_features'),
       'median_FB_px':track.get('median_FB_px'),'fixed_template_score':track.get('fixed_template_score')}
  rows.append(row)
  if track['mask'] is None:continue
  mask=rw.decode_mask(track['mask']);depth,valid,meta=depths[c]
  yy,xx=np.where(valid & mask.astype(bool));points=rw.backproject(depth,valid,mask,ext[i],k[i])
  keep=np.ones(len(points),bool)
  if len(points):
   robot_distance=cKDTree(robot).query(points)[0];keep &= robot_distance>disc['robot_FK_seed_radius_m']
   row['robot_seed_excluded_pixels']=int((~keep).sum())
   if search_center is None:keep[:]=False
   else:keep &= np.linalg.norm(points-search_center,axis=1)<=max_shift
  filtered=np.zeros_like(mask);filtered[yy[keep],xx[keep]]=1
  row.update(tracked_pixels=int(mask.sum()),retained_current_depth_pixels=int(filtered.sum()),
      robot_geometry_scope='current FK seed spheres only; incomplete link exclusion; absence not clearance',
      search_center_world_m=None if search_center is None else search_center.tolist(),search_center_kind='prediction_or_history_search_cue_only')
  if filtered.sum()<geo['min_points_per_view']:continue
  view={'camera':c,'mask':rw.encode_mask(filtered),'bbox':rw.bbox(filtered),'observation_id':current['observation_id'],
        'producer':'TARGET_CONDITIONED_CURRENT_RGBD_NOT_WHOLE_COMPONENT','visibility':'partial_visible_surface',
        'image_sha256':meta['aligned_rgb_sha256'],'depth_sha256':meta['depth']['sha256']}
  views.append(view)
  clouds[c]=rw.backproject(depth,valid,cv2.erode(filtered,np.ones((3,3),np.uint8)),ext[i],k[i])
 note=rw.measure_entity({'entity_id':target,'kind':'object','identity_status':'hypothesis'},views,current,depths,geo,ext,k)
 agreement=[]
 for ca,a in clouds.items():
  for cb,b in clouds.items():
   if ca>=cb or len(a)<geo['min_points_per_view'] or len(b)<geo['min_points_per_view']:continue
   dist=[cKDTree(a).query(b)[0],cKDTree(b).query(a)[0]]
   fractions=[float(np.mean(d<=disc['surface_agreement_m'])) for d in dist]
   agreement.append({'cameras':[ca,cb],'symmetric_surface_fraction':fractions,
       'supported':min(fractions)>=disc['min_symmetric_surface_fraction']})
 if note['status']=='coarse' and not any(a['supported'] for a in agreement):
  note.update(status='unknown',point_world_m=None,bounds_world_m=None,surface_cloud=[],reason='LOCAL_CROSS_VIEW_CONFLICT')
 # A partial visible patch is allowed; no requirement that all historical
 # surfaces remain visible, but observed shape cannot be entirely incompatible.
 shape=None
 if note['status']=='coarse':
  cloud=np.asarray(note['surface_cloud']);aligned=cloud-np.median(cloud,axis=0)
  shape=float(np.mean(cKDTree(historical-np.median(historical,axis=0)).query(aligned)[0]<=reference['geometry_update_config']['surface_match_m'])) if len(historical) else 0.
  if shape<reference['geometry_update_config']['min_surface_fraction']:
   note.update(status='unknown',point_world_m=None,bounds_world_m=None,surface_cloud=[],reason='LOCAL_HISTORICAL_SHAPE_CONFLICT')
 if any(r['reason']=='AMBIGUOUS_TEMPORAL_ASSOCIATION' for r in rows):
  note.update(status='unknown',point_world_m=None,bounds_world_m=None,surface_cloud=[],reason='LOCAL_INSTANCE_COMPETITION')
 partial=bool(note['partial_current_surface_cloud'])
 note.update(track_rows=rows,tracking_seeds=rw.clone(views),candidate_surface_cloud=rw.clone(note['surface_cloud']),
    support_status='current_multiview_partial_surface' if note['status']=='coarse' else ('partial_current_surface' if partial else 'unknown'),
    association_evidence=agreement,shape_support_fraction=shape,held_relation='unknown',
    association_uncertainty={'identity_guaranteed':False,'method':'CURRENT_UNIQUE_TRACK_AND_MULTIVIEW_DEPTH','merged_robot_component_not_promoted':True},
    geometry_scope='visible target surface only; occluded volume and collision clearance unknown',
    source_version='target_local_reassociation.v1',wall_s=time.monotonic()-start,grants_execution=False)
 return note

def augment(state,reference,previous,current,images,depths,read_images,feedback):
 """Separate predictions, current visual support, and control-event evidence."""
 target=reference.get('task_target_geometry_id');old=reference.get('pnp_interaction',{})
 e=state['entities'].get(target,{})
 measured=e.get('status')=='coarse' and e.get('temporal_association',{}).get('status')=='unique_current_match'
 point=e.get('point_world_m') if measured else None
 note=None
 event=old.get('gripper_event','none')
 for a in feedback.get('actions',[]):
  if a.get('completed') and a['action']['type']=='gripper':event='close' if a['action']['opening']<.5 else 'release'
 # Evaluate the actual just-completed gripper event before testing fallback.
 if point is None and event in ('close','release') and feedback.get('ok') is True and state.get('fk_camera_check',{}).get('status')=='pass':
  note=local_target_support(reference,current,images,depths,read_images)
  if note['status']=='coarse':
   from .semantic_binding import SEMANTIC_FIELDS
   point=note['point_world_m'];old_entity=reference['entities'][target]
   semantics=old_entity.get('historical_semantics',{}) if old_entity.get('semantic_status')=='unknown' else {k:clone(old_entity[k]) for k in SEMANTIC_FIELDS if k in old_entity}
   recovered={**clone(e),**clone(note),**clone(semantics),'geometry_instance_id':target,
      'historical_geometry':rw._historical_entity(old_entity),'measurement_kind':'current_target_conditioned_depth_region',
      'temporal_association':{'status':'unique_current_local_match','current_observation_id':current['observation_id'],
          'semantic_carry':'prior identity hypothesis with current local multiview support; not whole-component identity'},
      'geometry_residual':{'current_to_previous_surface_midpoint_m':None if old.get('current_xyz_m') is None else float(np.linalg.norm(np.asarray(point)-old['current_xyz_m']))}}
   state['entities'][target]=recovered
   state['task_target_current_support']={'geometry_instance_id':target,'status':'associated_current_local_hypothesis','grants_execution':False}
   state['current_unknowns']=[x for x in state.get('current_unknowns',[]) if x['entity_id']!=target]
  elif note['partial_current_surface_cloud']:
   e.update(partial_current_surface_cloud=clone(note['partial_current_surface_cloud']),current_evidence=clone(note['current_evidence']),
       local_support_status='partial_current_surface',views=clone(note['views']),visibility={v['camera']:'partial_current_surface' for v in note['views']},reason=note['reason'])
 origin=old.get('initial_object_xyz_m')
 if origin is None and point is not None:origin=clone(point)
 anchor=old.get('carry_anchor_flange_local_m');anchor_initialized=event=='close' and anchor is None and point is not None
 flange=np.array(current['state']['flange_pose_world']);rot=Rotation.from_quat(np.roll(flange[3:],-1)).as_matrix()
 if event=='close' and anchor is None and point is not None:anchor=(rot.T@(np.array(point)-flange[:3])).tolist()
 prediction=(flange[:3]+rot@np.array(anchor)).tolist() if event=='close' and anchor is not None else None
 residual=float(np.linalg.norm(np.array(point)-prediction)) if prediction is not None and point is not None else None
 lift=float(point[2]-origin[2]) if point is not None and origin is not None else None
 supported=point is not None
 status='tabletop_target' if event=='none' and measured else 'unknown'
 if event=='close':status='held_candidate' if supported else 'unknown'
 if event=='close' and lift is not None and lift>=.05 and residual is not None and residual<=.03:status='carrying_visual_hypothesis'
 if event=='release':status='released_visual_hypothesis' if supported and current['state']['actual_pad_gap_m']>.07 else 'unknown'
 last=old.get('current_xyz_m');shift=float(np.linalg.norm(np.array(point)-last)) if supported and last is not None else None
 state['pnp_interaction']={'status':status,'target_geometry_id':target,'current_xyz_m':point,'current_observation_id':current['observation_id'],
  'current_support':supported,'main_geometry_association':measured,'support_status':note['support_status'] if note is not None else ('current_multiview_surface' if supported else 'unknown'),'tracking_measurement':None if note is None else {k:clone(note[k]) for k in ('status','point_world_m','bounds_world_m','current_evidence','reason','track_rows','support_status','association_evidence','shape_support_fraction','wall_s','source_version','geometry_scope')},
  'initial_object_xyz_m':origin,'gripper_event':event,'carry_anchor_flange_local_m':anchor,
  'FK_carry_prediction_world_m':prediction,'prediction_source':'MEASURED_FK_PLUS_HISTORICAL_CLOSE_ANCHOR_NOT_CURRENT_OBJECT_MEASUREMENT' if prediction else None,
  'current_visual_vs_carry_prediction_residual_m':residual,'observed_lift_m':lift,'current_position_shift_m':shift,
  'carrying_seen':old.get('carrying_seen',False) or status=='carrying_visual_hypothesis',
  'released_stable_observed':status=='released_visual_hypothesis' and old.get('status')=='released_visual_hypothesis' and shift is not None and shift<.002 and current['captured_monotonic']-previous['captured_monotonic']>=1.2,
  'close_is_not_held':True,'carry_anchor_initialized_this_update':anchor_initialized,'carry_residual_scope':'anchor_definition_not_hold_verification' if anchor_initialized else 'current_visual_vs_prior_FK_prediction','control_feedback_sha256':digest(feedback),'grants_execution':False,
  'unknown':'visual identity and holding are hypotheses; no private contacts or actor pose input'}
 state['pnp_destination']=destination(reference,current,images,depths,read_images)
