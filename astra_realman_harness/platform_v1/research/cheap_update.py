"""CPU RGB evidence update. No torch, depth network, broker or simulator imports.

Minimal supported appearance domain: distinct saturated regions. Current masks
are redetected; temporal identity requires bidirectional LK and current support.
Only explicitly planar regions receive current 3D measurements. Other objects
retain historical geometry separately and current 3D stays unknown.
"""
import cv2
import numpy as np
from .contracts import clone
from .da3_geometry import calibrated_cameras, CAMERAS

def appearance(rgb,bbox):
    h,w=rgb.shape[:2];x0,y0,x1,y1=np.asarray(bbox)*[w,h,w,h]
    roi=rgb[max(0,int(y0)):min(h,int(np.ceil(y1))),max(0,int(x0)):min(w,int(np.ceil(x1)))]
    if not roi.size:return None
    hsv=cv2.cvtColor(roi,cv2.COLOR_RGB2HSV);good=(hsv[:,:,1]>=80)&(hsv[:,:,2]>=40)
    if good.sum()<12:return None
    hist=np.bincount(hsv[:,:,0][good],minlength=180);return int(hist.argmax())

def current_mask(rgb,hue):
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV);d=abs(hsv[:,:,0].astype(float)-hue);d=np.minimum(d,180-d)
    mask=((d<=8)&(hsv[:,:,1]>=80)&(hsv[:,:,2]>=40)).astype(np.uint8)
    n,labs,stats,_=cv2.connectedComponentsWithStats(mask,8)
    order=[i for i in range(1,n) if stats[i,cv2.CC_STAT_AREA]>=12]
    order.sort(key=lambda i:stats[i,cv2.CC_STAT_AREA],reverse=True)
    if not order:return None,'NO_CURRENT_APPEARANCE_SUPPORT'
    if len(order)>1 and stats[order[1],cv2.CC_STAT_AREA]>=.25*stats[order[0],cv2.CC_STAT_AREA]:
        return None,'AMBIGUOUS_CURRENT_COMPONENTS'
    return (labs==order[0]).astype(np.uint8),'CURRENT_RGB_COMPONENT'

def project(point,ext,k):
    x=ext[:3,:3]@np.asarray(point)+ext[:3,3]
    return (k@x)[:2]/x[2] if x[2]>0 else None

def planar_points(uv,ext,k,plane):
    pose=np.linalg.inv(ext);rays=np.column_stack([uv,np.ones(len(uv))])@np.linalg.inv(k).T@pose[:3,:3].T
    n=np.asarray(plane['normal']);den=rays@n
    z=-(pose[:3,3]@n+plane['offset'])/np.where(abs(den)>1e-8,den,np.nan)
    if not np.isfinite(z).all() or np.any((z<=0)|(z>3)):return None
    return pose[:3,3]+z[:,None]*rays

def measure(reference,previous,current,old_images,new_images,completed_at):
    if current['captured_monotonic']<completed_at:raise ValueError('OBSERVATION_BEFORE_COMPLETION')
    if current['captured_monotonic']<=previous['captured_monotonic']:raise ValueError('NONCAUSAL_UPDATE')
    if reference['observation_id']!=previous['observation_id']:raise ValueError('REFERENCE_OBSERVATION_MISMATCH')
    oldext,oldk=calibrated_cameras(previous);ext,k=calibrated_cameras(current)
    out={'backend':'cheap_rgb_update_v1','observation_id':current['observation_id'],
        'captured_monotonic':current['captured_monotonic'],'robot_state':clone(current['state']),
        'scene_healthy':bool(new_images),'entities':{},'geometry_only':reference.get('geometry_only',True),
        'task_identity_verified':False,'history_semantics':'current RGB association; FK current; old geometry historical',
        'resource_metrics':{'DA3_calls':0,'Astra_calls':0},'observation_residual_m':None,
        'observation_residual_status':'2D_RESIDUAL_NOT_A_METRIC_DEPTH_MEASUREMENT',
        'geometry_quality':{'version':'astra.geometry_quality.v1','numeric_valid':'unknown','self_consistent':'unknown',
            'task_usable':'unknown','observation_id':current['observation_id'],'grants_execution':False}}
    if 'semantic_evidence_id' in reference:out['semantic_evidence_id']=reference['semantic_evidence_id']
    for identity,e in reference.get('entities',{}).items():
        hist=e.get('historical_geometry') or {'point_world_m':clone(e.get('point_world_m')),'observation_id':previous['observation_id']}
        entity={**clone(e),'status':'unknown','point_world_m':None,'uncertainty_radius_m':None,
            'measurement_kind':'unknown','historical_geometry':hist,'motion':'unknown','held_relation':'unknown',
            'visibility':{},'views':[],'current_evidence':[],'reason':'CURRENT_3D_UNOBSERVABLE'}
        plane=e.get('public_plane') if e.get('kind')=='region' else None
        plane_centers=[];motion=[]
        for v in e.get('views',[]):
            camera=v['camera'];i=CAMERAS.index(camera);old=old_images[camera];new=new_images[camera]
            hue=appearance(old,v['bbox']);evidence={'camera':camera,'observation_id':current['observation_id'],
                'measurement_kind':'current_RGB_2D','association':'unknown','source_bbox_observation':previous['observation_id']}
            if hue is None:evidence['reason']='APPEARANCE_DOMAIN_UNSUPPORTED';entity['current_evidence'].append(evidence);continue
            om,_=current_mask(old,hue);nm,reason=current_mask(new,hue)
            if om is None or nm is None:
                evidence['reason']=reason;entity['visibility'][camera]='unknown';entity['current_evidence'].append(evidence);continue
            ys,xs=np.where(nm);h,w=nm.shape;bbox=[xs.min()/w,ys.min()/h,(xs.max()+1)/w,(ys.max()+1)/h]
            evidence.update(current_bbox=[float(x) for x in bbox],current_pixels=int(nm.sum()))
            # Bound OLD support by its evidence ROI; current bbox is always newly detected.
            roi=np.zeros_like(om);x0,y0,x1,y1=np.asarray(v['bbox'])*[w,h,w,h];roi[int(y0):int(np.ceil(y1)),int(x0):int(np.ceil(x1))]=1
            gray0=cv2.cvtColor(old,cv2.COLOR_RGB2GRAY);gray1=cv2.cvtColor(new,cv2.COLOR_RGB2GRAY)
            p0=cv2.goodFeaturesToTrack(gray0,maxCorners=40,qualityLevel=.01,minDistance=3,mask=om*roi,blockSize=3)
            if p0 is None or len(p0)<3:
                evidence['reason']='INSUFFICIENT_TEXTURE_FEATURES';entity['current_evidence'].append(evidence);continue
            guess=p0.copy();point=e.get('point_world_m') or hist.get('point_world_m')
            if point is not None:
                a=project(point,oldext[i],oldk[i]);b=project(point,ext[i],k[i])
                if a is not None and b is not None:guess+=np.asarray(b-a,np.float32)
            if plane is not None:
                pp=planar_points(p0[:,0],oldext[i],oldk[i],plane)
                if pp is not None:
                    projected=[project(x,ext[i],k[i]) for x in pp]
                    if all(x is not None for x in projected):guess=np.asarray(projected,np.float32).reshape(-1,1,2).copy()
            expected=guess[:,0].copy() # LK may mutate nextPts in-place.
            p1,s1,err=cv2.calcOpticalFlowPyrLK(gray0,gray1,p0,guess,winSize=(21,21),maxLevel=3,flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
            if p1 is None:evidence['reason']='FLOW_FAILED';entity['current_evidence'].append(evidence);continue
            back,s2,_=cv2.calcOpticalFlowPyrLK(gray1,gray0,p1,None,winSize=(21,21),maxLevel=3)
            if back is None:evidence['reason']='BACKWARD_FLOW_FAILED';entity['current_evidence'].append(evidence);continue
            fb=np.linalg.norm(back-p0,axis=2).ravel();uv=p1[:,0];idx=np.rint(uv).astype(int)
            in_image=(idx[:,0]>=0)&(idx[:,0]<w)&(idx[:,1]>=0)&(idx[:,1]<h)
            in_mask=np.zeros(len(idx),bool);in_mask[in_image]=nm[idx[in_image,1],idx[in_image,0]]>0
            good=(s1.ravel()>0)&(s2.ravel()>0)&(fb<=1)&(err.ravel()<=20)&in_mask
            evidence.update(features=len(p0),matched=int(good.sum()),median_FB_error_px=float(np.median(fb[good])) if good.any() else None)
            if good.sum()<3:
                evidence['reason']='UNVERIFIED_TEMPORAL_ASSOCIATION';entity['current_evidence'].append(evidence);continue
            residual=np.linalg.norm(p1[:,0]-expected,axis=1)[good]
            rp=float(np.median(residual));motion.append(rp)
            clipped=xs.min()<=1 or ys.min()<=1 or xs.max()>=w-2 or ys.max()>=h-2
            evidence.update(association='appearance_temporal_hypothesis',reason='BIDIRECTIONAL_LK_AND_CURRENT_MASK',
                current_points_px=p1[:,0][good].tolist(),previous_points_px=p0[:,0][good].tolist(),
                static_reprojection_residual_px=rp,visibility='partial' if clipped else 'visible')
            entity['visibility'][camera]=evidence['visibility'];entity['views'].append({'camera':camera,'bbox':evidence['current_bbox'],
                'visibility':evidence['visibility'],'observation_id':current['observation_id']})
            if plane is not None and not clipped and np.allclose(plane['normal'],[0,0,1]):
                pts=planar_points(np.column_stack([xs,ys]),ext[i],k[i],plane)
                if pts is not None:
                    rect=cv2.minAreaRect(pts[:,:2].astype(np.float32));corners=cv2.boxPoints(rect)
                    corner_d=max(float(np.linalg.norm(pts[:,:2]-c,axis=1).min()) for c in corners)
                    if corner_d<=.006:
                        plane_centers.append([*map(float,rect[0]),-float(plane['offset'])])
                        evidence['plane_region_center_world_m']=plane_centers[-1]
            entity['current_evidence'].append(evidence)
        if motion:entity['motion']='static_projection_conflict' if max(motion)>3 else 'static_projection_supported_not_proven_static'
        if len(plane_centers)>=2:
            c=np.median(plane_centers,axis=0);d=max(float(np.linalg.norm(x-c)) for x in plane_centers)
            if d<=.02:
                entity.update(status='coarse',point_world_m=c.tolist(),uncertainty_radius_m=max(.01,d),
                    measurement_kind='current_RGB_plane_constraint',reason='CURRENT_PLANAR_REGION_MULTIVIEW_SUPPORT')
        out['entities'][identity]=entity
    out['rebuild_needed']=not out['entities'] or any(e['status']=='unknown' or e['motion']=='static_projection_conflict' for e in out['entities'].values())
    out['rebuild_dispatches_model']=False
    # A planar diagnostic measurement does not certify generic precontact task geometry.
    return out
