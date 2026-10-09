"""Shared strong 2D baseline and cheap world evidence maintenance.

Appearance histograms come from instance masks, not hard-coded color identities.
Current connected components + forward/backward LK verify fresh pixel evidence.
Fixed-view template matching is retained as fallback. No learned model is called.
"""
import time
import cv2
import numpy as np
from .contracts import clone
from .da3_geometry import CAMERAS, calibrated_cameras
from .object_world import BACKEND, decode_mask, encode_mask, render_support


def fk_camera_consistency(previous, current):
    """Check a rigid wrist-camera rig using measured flange FK, never simulator GT.

    FK predicts the current camera pose; public current calibration is independently
    checked, not corrected. Tolerances are interface sanity checks, not safety gates.
    """
    from scipy.spatial.transform import Rotation
    def matrix(p):
        if len(p)!=7 or not np.isfinite(p).all() or abs(np.linalg.norm(p[3:])-1)>.002:
            raise ValueError('INVALID_MEASURED_FK')
        m=np.eye(4);m[:3,:3]=Rotation.from_quat([*p[4:],p[3]]).as_matrix();m[:3,3]=p[:3]
        return m
    try:
        f0=matrix(previous['state']['flange_pose_world']);f1=matrix(current['state']['flange_pose_world'])
        c0=matrix(previous['calibration']['wrist']['pose_world_xyz_wxyz'])
        c1=matrix(current['calibration']['wrist']['pose_world_xyz_wxyz'])
        predicted=f1@np.linalg.inv(f0)@c0
        translation=float(np.linalg.norm(predicted[:3,3]-c1[:3,3]))
        angle=float(Rotation.from_matrix(predicted[:3,:3].T@c1[:3,:3]).magnitude()*180/np.pi)
        return {'status':'pass' if translation<=.005 and angle<=1 else 'fail',
            'translation_residual_m':translation,'rotation_residual_deg':angle,
            'source':'measured flange FK + previous public wrist extrinsics; no pose correction'}
    except (KeyError,ValueError):
        return {'status':'unknown','reason':'FK_OR_WRIST_CALIBRATION_UNAVAILABLE'}


def appearance_likelihood(old, new, mask):
    a = cv2.cvtColor(old, cv2.COLOR_RGB2HSV)
    b = cv2.cvtColor(new, cv2.COLOR_RGB2HSV)
    bins = [18, 4, 4]; ranges = [0, 180, 0, 256, 0, 256]
    fg = cv2.calcHist([a], [0, 1, 2], mask, bins, ranges)
    ring = cv2.dilate(mask, np.ones((15, 15), np.uint8)) - mask
    bg = cv2.calcHist([a], [0, 1, 2], ring, bins, ranges)
    fg /= max(float(fg.sum()), 1); bg /= max(float(bg.sum()), 1)
    table = fg / (fg + bg + .01)
    index = (b[:, :, 0] // 10, b[:, :, 1] // 64, b[:, :, 2] // 64)
    return table[index]


def bbox(mask):
    y, x = np.where(mask); h, w = mask.shape
    return [float(x.min()/w), float(y.min()/h), float((x.max()+1)/w), float((y.max()+1)/h)]


def track_view(old, new, old_mask, camera, cfg):
    result = {'association': 'unknown', 'visibility': 'unknown', 'measurement_kind': 'current_RGB_2D',
        'reason': 'NO_PREVIOUS_SUPPORT', 'mask': None}
    if old_mask.sum() < 18: return result
    gray0 = cv2.cvtColor(old, cv2.COLOR_RGB2GRAY); gray1 = cv2.cvtColor(new, cv2.COLOR_RGB2GRAY)
    features = cv2.goodFeaturesToTrack(gray0, 60, .01, 3,
        mask=cv2.dilate(old_mask, np.ones((3, 3), np.uint8)), blockSize=3)
    matched = np.empty((0, 2), np.float32); fb_good = []
    if features is not None:
        p, s, error = cv2.calcOpticalFlowPyrLK(gray0, gray1, features, None, winSize=(25, 25), maxLevel=4)
        if p is not None:
            back, bs, _ = cv2.calcOpticalFlowPyrLK(gray1, gray0, p, None, winSize=(25, 25), maxLevel=4)
            if back is not None:
                fb = np.linalg.norm(back-features, axis=2).ravel()
                good = (s.ravel()>0) & (bs.ravel()>0) & (fb <= cfg['max_fb_px']) & (error.ravel() <= cfg['max_lk_error'])
                matched = p[:, 0][good]; fb_good = fb[good]
    likelihood = appearance_likelihood(old, new, old_mask)
    binary = (likelihood >= cfg['appearance_score_min']).astype(np.uint8)
    n, labels, stats, centers = cv2.connectedComponentsWithStats(binary, 8)
    candidates = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 18: continue
        mask = (labels == i).astype(np.uint8)
        near = cv2.dilate(mask, np.ones((7, 7), np.uint8))
        pix = np.rint(matched).astype(int)
        inside = (pix[:, 0]>=0)&(pix[:, 0]<mask.shape[1])&(pix[:, 1]>=0)&(pix[:, 1]<mask.shape[0])
        hits = np.zeros(len(pix), bool); hits[inside] = near[pix[inside, 1], pix[inside, 0]] > 0
        candidates.append((int(hits.sum()), float(likelihood[mask>0].mean()), i, mask))
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    result['lk_good_features'] = len(matched)
    result['median_FB_px'] = float(np.median(fb_good)) if len(fb_good) else None
    accepted = None
    if candidates and candidates[0][0] >= cfg['min_features']:
        if len(candidates)>1 and candidates[1][0] >= max(cfg['min_features'], candidates[0][0]*.5):
            result['reason'] = 'AMBIGUOUS_TEMPORAL_ASSOCIATION'; return result
        accepted = candidates[0]; result['reason'] = 'BIDIRECTIONAL_LK_AND_CURRENT_APPEARANCE'
    elif camera in ('fixed', 'assembly') and candidates:
        # Fixed-camera fallback remains available to BOTH groups. Full-frame
        # template search; never use world projection to handicap the baseline.
        y, x = np.where(old_mask); margin=3
        x0=max(0,x.min()-margin); y0=max(0,y.min()-margin)
        x1=min(old.shape[1],x.max()+margin+1); y1=min(old.shape[0],y.max()+margin+1)
        template = old[y0:y1, x0:x1]
        corr = cv2.matchTemplate(new, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(corr)
        result['fixed_template_score'] = float(score)
        if score >= cfg['min_template_score']:
            tx, ty = loc; cy=ty+template.shape[0]/2; cx=tx+template.shape[1]/2
            matches=[c for c in candidates if np.linalg.norm(centers[c[2]]-[cx,cy]) < max(template.shape[:2])]
            if len(matches)==1:
                accepted=matches[0]; result['reason']='FIXED_VIEW_TEMPLATE_AND_CURRENT_APPEARANCE'
    if accepted is None:
        result['reason']='NO_RELIABLE_CURRENT_ASSOCIATION'; return result
    mask=accepted[3]; y,x=np.where(mask)
    clipped=x.min()<=1 or y.min()<=1 or x.max()>=mask.shape[1]-2 or y.max()>=mask.shape[0]-2
    result.update(association='temporal_instance_hypothesis', visibility='partial' if clipped else 'visible_support',
        mask=encode_mask(mask), bbox=bbox(mask), current_pixels=int(mask.sum()), matched_on_component=accepted[0])
    return result


def measure(reference, previous, current, old_images, new_images, completed_at, cfg):
    start=time.monotonic()
    if current['captured_monotonic']<completed_at: raise ValueError('OBSERVATION_BEFORE_COMPLETION')
    if current['captured_monotonic']<=previous['captured_monotonic']: raise ValueError('NONCAUSAL_UPDATE')
    if reference['observation_id']!=previous['observation_id']: raise ValueError('REFERENCE_OBSERVATION_MISMATCH')
    ext,k=calibrated_cameras(current)
    fk_check=fk_camera_consistency(previous,current)
    out={**clone(reference),'backend':BACKEND,'observation_id':current['observation_id'],
        'captured_monotonic':current['captured_monotonic'],'robot_state':clone(current['state']),
        'history_semantics':'historical 3D occupancy checked against current 2D; no new 3D measurement',
        'entities':{},'rebuild_dispatches_model':False,
        'geometry_quality':{'numeric_valid':'unknown','self_consistent':'unknown','task_usable':'unknown',
            'observation_id':current['observation_id'],'grants_execution':False},
        'resource_metrics':{'DA3_calls':0,'Astra_calls':0,'segmentation_calls':0}}
    out['fk_camera_check']=fk_check
    out['physical_evidence']={'observation_id':current['observation_id'],
        'captured_monotonic':current['captured_monotonic'],
        'source':'actual archived robot observation, not requested action or predicted completion',
        'stopped':current['state'].get('stopped'),
        'actual_pad_gap_m':current['state'].get('actual_pad_gap_m'),
        'gripper_master_rad':current['state'].get('gripper_master_rad'),
        'holding_evidence':'unknown; jaw state alone does not establish attachment',
        'execution_result':'not supplied in this offline observation interface'}
    for identity,e in reference['entities'].items():
        historical=e.get('historical_geometry') or {'occupancy':clone(e.get('occupancy')),
            'observation_id':e['observation_id'],'captured_monotonic':e['captured_monotonic']}
        entity={**clone(e),'occupancy':None,'bounds_world_m':None,'status':'unknown','point_world_m':None,
            'measurement_kind':'unknown','observation_id':current['observation_id'],
            'captured_monotonic':current['captured_monotonic'],'historical_geometry':historical,
            'held_relation':'unknown','motion':'unknown','views':[], 'visibility':{},'current_evidence':[]}
        supported=[];conflicts=[]
        tracking_s=0.;projection_s=0.
        for v in e['views']:
            stamp=time.monotonic()
            camera=v['camera']; rec=track_view(old_images[camera],new_images[camera],decode_mask(v['mask']),camera,cfg)
            tracking_s+=time.monotonic()-stamp
            rec.update(camera=camera,observation_id=current['observation_id'],
                captured_monotonic=current['captured_monotonic'],source_observation=previous['observation_id'])
            entity['visibility'][camera]=rec['visibility']
            if rec['mask'] is not None:
                entity['views'].append({'camera':camera,'mask':rec['mask'],'bbox':rec['bbox'],
                    'visibility':rec['visibility'],'observation_id':current['observation_id']})
                if historical['occupancy']:
                    stamp=time.monotonic()
                    i=CAMERAS.index(camera);mask=decode_mask(rec['mask'])
                    projected=render_support(historical['occupancy'],ext[i],k[i],mask.shape)
                    recall=float((projected & mask).sum()/max(1,mask.sum()))
                    rec['historical_projection_current_support_recall']=recall
                    # A disjoint current mask is a conflict; low visibility cannot
                    # certify static geometry and is not interpreted as movement GT.
                    (supported if recall>=cfg['projection_support_min'] else conflicts).append(camera)
                    projection_s+=time.monotonic()-stamp
            entity['current_evidence'].append(rec)
        entity['baseline_2d']={'current_associated_views':[v['camera'] for v in entity['views']],
            'fixed_fallback_available':any(v['camera'] in ('assembly','fixed') for v in entity['views']),
            'spatial_3d':'unknown','same_tracker_and_observation_budget':True}
        entity['motion']='projection_conflict' if conflicts else ('static_projection_supported_not_proven_static' if len(supported)>=2 else 'unknown')
        entity['reason']='CURRENT_3D_UNKNOWN_REQUEST_REBUILD' if conflicts or len(supported)<2 else 'HISTORICAL_OCCUPANCY_WITH_CURRENT_2D_SUPPORT'
        # Keep prediction separate even when every check passes; no mask-warp or
        # static assumption is published as a fresh 3D measurement.
        entity['predicted_occupancy']=historical['occupancy'] if len(supported)>=2 and not conflicts else None
        if fk_check['status']!='pass':
            entity.update(predicted_occupancy=None,motion='unknown',reason='FK_CAMERA_CONSISTENCY_UNKNOWN_OR_FAILED')
        entity['timing']={'shared_2d_tracking_s':tracking_s,'world_projection_s':projection_s}
        out['entities'][identity]=entity
    # Current masks claimed by two identities => both associations unknown.
    ids=list(out['entities'])
    for ai,a in enumerate(ids):
        for b in ids[ai+1:]:
            ea=out['entities'][a];eb=out['entities'][b]
            for va in ea['views']:
                for vb in eb['views']:
                    if va['camera']!=vb['camera']:continue
                    ma=decode_mask(va['mask']);mb=decode_mask(vb['mask'])
                    if (ma&mb).sum()>.25*max(1,min(ma.sum(),mb.sum())):
                        for entity in (ea,eb):
                            entity.update(predicted_occupancy=None,motion='unknown',reason='CROSS_INSTANCE_TRACK_CONFLICT')
                            entity['baseline_2d'].update(current_associated_views=[],fixed_fallback_available=False)
                            entity['views']=[]
    out['rebuild_needed']=any(e['predicted_occupancy'] is None for e in out['entities'].values())
    out['resource_metrics']['update_compute_s']=time.monotonic()-start
    return out
