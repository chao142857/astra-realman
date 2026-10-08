"""Declared toy-scene RGB checks. No simulator imports, state queries or GT masks.

Color connected components are an engineering detector, NOT semantic certainty.
All coordinates are pixels from supplied RGB. Unsupported/occluded/ambiguous => unknown.
"""
import math
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial.transform import Rotation

REVISION='rgb_red_green_components_v1'
THRESHOLDS={'min_pixels':18,'second_component_ratio':.35,'static_shift_px':6.,
            'static_area_ratio':[.25,4.],'color_cosine_min':.95,'near_tool_diagonals':1.5}


def detect(path):
    a=np.asarray(Image.open(path).convert('RGB'),dtype=float);h,w=a.shape[:2]
    out={'width':w,'height':h,'healthy':bool(np.std(a)>8),'source':'RGB_HEURISTIC_NOT_OBJECT_TRUTH'}
    r,g,b=a[:,:,0],a[:,:,1],a[:,:,2]
    masks={'object':(r>60)&(r>1.8*g)&(r>1.8*b),'goal':(g>45)&(g>1.35*r)&(g>1.3*b)}
    for key,mask in masks.items():
        labels,n=ndimage.label(mask);counts=np.bincount(labels.ravel());counts[0]=0
        order=np.argsort(counts)[::-1];big=int(order[0]);area=int(counts[big])
        reason=None
        if not out['healthy'] or area<THRESHOLDS['min_pixels']:reason='INSUFFICIENT_VISIBLE_PIXELS'
        elif len(order)>1 and counts[order[1]]>=area*.35:reason='AMBIGUOUS_COMPONENTS'
        if reason:
            out[key]={'status':'unknown','reason':reason,'visible_pixels':area};continue
        yy,xx=np.where(labels==big);bbox=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]
        if bbox[0]<=1 or bbox[1]<=1 or bbox[2]>=w-1 or bbox[3]>=h-1:
            out[key]={'status':'unknown','reason':'IMAGE_BOUNDARY_CLIPPING','visible_pixels':area};continue
        color=a[labels==big].mean(axis=0);color=color/(np.linalg.norm(color)+1e-12)
        out[key]={'status':'visible','centroid':[float(xx.mean()),float(yy.mean())],
                  'bbox':bbox,'bbox_normalized':[bbox[0]/w,bbox[1]/h,bbox[2]/w,bbox[3]/h],
                  'visible_pixels':area,'color_unit':color.tolist(),
                  'identity_status':'unique_color_hypothesis_not_confirmed_identity'}
    return out


def features(observation):
    return {camera:detect(path) for camera,path in observation['images'].items()}


def rotation(cal):return Rotation.from_quat(np.roll(cal['pose_world_xyz_wxyz'][3:],-1)).as_matrix()


def pixel_world_on_plane(feature,cal,z):
    if feature['status']!='visible':raise ValueError('RGB_TARGET_UNKNOWN')
    u,v=feature['centroid'];K=np.asarray(cal['intrinsic']);p=np.asarray(cal['pose_world_xyz_wxyz'][:3])
    ray=rotation(cal)@np.array([1.,-(u-K[0,2])/K[0,0],-(v-K[1,2])/K[1,1]])
    if abs(ray[2])<1e-6:raise ValueError('RAY_PARALLEL_PLANE')
    t=(z-p[2])/ray[2]
    if t<=0:raise ValueError('RAY_BEHIND_CAMERA')
    return (p+t*ray).tolist()


def project(point,cal):
    v=rotation(cal).T@(np.asarray(point)-np.asarray(cal['pose_world_xyz_wxyz'][:3]))
    if v[0]<=1e-5:return None
    pix=np.asarray(cal['intrinsic'])@np.array([-v[1],-v[2],v[0]])
    return (pix[:2]/pix[2]).tolist()


def same_camera(a,b):
    return bool(np.max(np.abs(np.asarray(a['pose_world_xyz_wxyz'])-b['pose_world_xyz_wxyz']))<1e-6)


def compare(source,current,source_cal,current_cal,requirements,state):
    """Evidence-only acceptance. No image-hash equality shortcut, no default pass."""
    checks=[]
    for requirement in requirements:
        votes=[]
        if requirement=='scene_healthy':
            votes=[{'camera':c,'status':'valid' if v['healthy'] else 'unknown'} for c,v in current.items()]
        elif requirement in ('object_static','goal_static'):
            key=requirement.split('_')[0]
            for camera,new in current.items():
                old=source.get(camera,{}).get(key,{});new=new[key]
                if not same_camera(source_cal[camera],current_cal[camera]):
                    votes.append({'camera':camera,'status':'unknown','reason':'CAMERA_MOVED'});continue
                if old.get('status')!='visible' or new['status']!='visible':
                    votes.append({'camera':camera,'status':'unknown','reason':'NOT_VISIBLE_OR_AMBIGUOUS'});continue
                drift=float(np.linalg.norm(np.array(old['centroid'])-new['centroid']))
                ratio=new['visible_pixels']/old['visible_pixels'];cos=float(np.dot(old['color_unit'],new['color_unit']))
                ok=drift<=6 and .25<=ratio<=4 and cos>=.95
                votes.append({'camera':camera,'status':'valid' if ok else 'invalid','shift_px':drift,'area_ratio':ratio,'color_cosine':cos})
        elif requirement=='object_near_tool':
            for camera,f in current.items():
                o=f['object'];pix=project(state['actual_grasp_center_world'],current_cal[camera])
                if o['status']!='visible' or pix is None:
                    votes.append({'camera':camera,'status':'unknown','reason':'OBJECT_OCCLUDED_OR_PROJECTION_INVALID'});continue
                box=o['bbox'];diag=math.hypot(box[2]-box[0],box[3]-box[1])
                distance=float(np.linalg.norm(np.array(o['centroid'])-pix));ok=distance<=1.5*diag
                votes.append({'camera':camera,'status':'valid' if ok else 'invalid','pixel_distance_to_measured_tool':distance,'bbox_diagonal':diag})
        elif requirement=='object_at_goal':
            for camera,f in current.items():
                o,g=f['object'],f['goal']
                if o['status']!='visible' or g['status']!='visible':
                    votes.append({'camera':camera,'status':'unknown','reason':'OBJECT_OR_GOAL_NOT_VISIBLE'});continue
                distance=float(np.linalg.norm(np.array(o['centroid'])-g['centroid']))
                box=g['bbox'];diag=math.hypot(box[2]-box[0],box[3]-box[1])
                votes.append({'camera':camera,'status':'valid' if distance<=.6*diag else 'invalid','pixel_distance':distance,'goal_diagonal':diag})
        else:raise ValueError('UNSUPPORTED_RGB_REQUIREMENT')
        # All available identifiable views must agree; one valid view suffices only
        # when other views are explicitly unknown, never when they contradict it.
        status='invalid' if any(v['status']=='invalid' for v in votes) else 'valid' if any(v['status']=='valid' for v in votes) else 'unknown'
        checks.append({'requirement':requirement,'status':status,'views':votes})
    status='invalid' if any(v['status']=='invalid' for v in checks) else 'unknown' if not checks or any(v['status']=='unknown' for v in checks) else 'valid'
    return {'status':status,'method':REVISION,'thresholds':THRESHOLDS,'checks':checks}


def reuse_packet(packet,old_features,current_features,old_cal,current_cal,observation_id):
    """Keep old bbox provenance separate from identity hypothesis/current state."""
    checks=compare(old_features,current_features,old_cal,current_cal,['goal_static'],{'actual_grasp_center_world':[0,0,0]})
    camera=packet['selected_camera'];same=same_camera(old_cal[camera],current_cal[camera])
    obj=current_features[camera]['object']
    return {'eligible':checks['status']=='valid' and same and obj['status']=='visible','original_evidence_request':packet['binding']['request_id'],
            'identity_hypothesis':{'status':'unconfirmed','source_observation_id':packet['binding']['source_observation_id']},
            'old_bbox':{'status':'historical_only','source_observation_id':packet['binding']['source_observation_id'],'bbox':packet['bbox']},
            'current_object_state':{'status':'visible_color_component' if obj['status']=='visible' else 'unknown','source_observation_id':observation_id},
            'current_roi':{'status':'rgb_relocalized' if same and obj['status']=='visible' else 'unknown',
                           'source_observation_id':observation_id,'bbox':obj.get('bbox_normalized') if same and obj['status']=='visible' else None},
            'rgb_check':checks,'camera_unchanged':same}
