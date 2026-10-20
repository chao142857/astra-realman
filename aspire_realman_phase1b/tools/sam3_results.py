"""Persist real SAM3 predictions. A completed call is not target recognition."""
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from rgbd_evidence import artifact,mask_geometry


def classify(mask_count,accepted_count):
    return {'inference_completed':True,'mask_count':mask_count,'accepted_candidate_count':accepted_count,
      'target_candidates_present':accepted_count>0,'target_identification_success':False if accepted_count==0 else None,
      'visual_validation':'NOT_APPLICABLE_NO_ACCEPTED_TARGET' if accepted_count==0 else 'PENDING_VISUAL_REVIEW',
      'status':'INFERENCE_COMPLETED_NO_TARGET' if mask_count==0 else
               ('INFERENCE_COMPLETED_LOW_CONFIDENCE' if accepted_count==0 else 'INFERENCE_COMPLETED_CANDIDATES_UNVERIFIED')}


def save_predictions(masks,boxes,scores,rgb,z,meta,out,prefix,threshold,*,geometry=False):
    masks=np.asarray(masks,dtype=bool)
    if masks.ndim==4 and masks.shape[1]==1:masks=masks[:,0]
    boxes=np.asarray(boxes);scores=np.asarray(scores).reshape(-1)
    if masks.size==0:masks=np.empty((0,*z.shape),bool)
    if masks.shape!=(len(scores),*z.shape) or boxes.shape!=(len(scores),4):raise ValueError('MODEL_OUTPUT_SHAPE_MISMATCH')
    order=np.argsort(-scores);rows=[];overlay=rgb.copy();draw_boxes=[]
    colors=[[255,60,60],[40,230,80],[70,140,255],[255,190,20],[190,80,255]]
    for rank,index in enumerate(order[:5]):
        mask=masks[index];score=float(scores[index]);accepted=bool(mask.any() and score>=threshold)
        path=out/f'{prefix}-mask-{rank}.png';Image.fromarray(mask.astype(np.uint8)*255).save(path)
        row={'rank':rank,'model_index':int(index),'source_rgb_sha256':meta['assets']['rgb.png']['sha256'],
             'source_depth_sha256':meta['assets']['aligned-depth-m.npy']['sha256'],'score':score,'box_xyxy_pixels':boxes[index].astype(float).tolist(),
             'mask_pixel_count':int(mask.sum()),'accepted_by_score_and_nonempty':accepted,'mask':artifact(path),
             'mask_bool_sha256':hashlib.sha256(np.ascontiguousarray(mask).tobytes()).hexdigest()}
        if geometry and mask.any():row['camera_geometry']=mask_geometry(rgb,z,meta,mask,out,f'{prefix}-{rank}')
        rows.append(row)
        color=np.array(colors[rank]);overlay[mask]=(overlay[mask]*.55+color*.45).astype(np.uint8)
        draw_boxes.append((row['box_xyxy_pixels'],f'{rank}: {score:.3f}',tuple(color)))
    im=Image.fromarray(overlay);d=ImageDraw.Draw(im)
    for box,label,color in draw_boxes:
        d.rectangle(box,outline=color,width=2);d.text((box[0],box[1]),label,fill=color)
    overlay_artifact=None
    if rows:
        path=out/f'{prefix}-actual-mask-overlay.png';im.save(path);overlay_artifact=artifact(path)
    accepted=sum(bool(masks[i].any() and scores[i]>=threshold) for i in range(len(scores)))
    return {**classify(len(scores),accepted),'score_threshold':threshold,'box_units':'source RGB pixels',
        'raw_scores':scores.astype(float).tolist(),'raw_boxes_xyxy_pixels':boxes.astype(float).tolist(),
        'retention':'Top 5 by score saved, matching native Provider result limit; all counts/scores/boxes retained',
        'predictions':rows,'overlay':overlay_artifact,
        'overlay_note':'No overlay generated when no actual masks were returned'}
