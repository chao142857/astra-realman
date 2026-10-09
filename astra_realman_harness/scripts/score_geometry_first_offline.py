"""Independent frozen-prediction scoring; no estimator or runtime import."""
import argparse,json,hashlib,time
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

def distance(points,gt):
    p=gt['pose_world_xyz_wxyz'];rot=Rotation.from_quat([*p[4:],p[3]]).as_matrix();local=(points-p[:3])@rot
    q=np.abs(local)-gt['side_m']/2
    return np.abs(np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(q.max(axis=1),0))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=Path,required=True);ap.add_argument('--truth',type=Path,required=True);args=ap.parse_args()
    r=args.run;seal=json.loads((r/'PREDICTION_SEAL.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    for rel,h in seal['files'].items():assert sha(r/rel)==h,rel
    # First private read is after verification of the prediction seal.
    truth=json.loads(args.truth.read_text());world=json.loads((r/'results/geometry/WORLD.json').read_text());rows=[];matches={x['setup_name']:[] for x in truth['objects']}
    for identity,e in world['state']['entities'].items():
        pts=np.array(e['candidate_surface_cloud']);metrics=[]
        for gt in truth['objects']:
            d=distance(pts,gt);metrics.append({'private_object':gt['setup_name'],'surface_p95_m':float(np.quantile(d,.95)),'fraction_within_10mm':float(np.mean(d<=.01))})
        supported=[x['private_object'] for x in metrics if x['surface_p95_m']<=.01]
        mixed=[x['private_object'] for x in metrics if x['fraction_within_10mm']>=.1]
        row={'geometry_instance_id':identity,'status':e['status'],'candidate_type':e['candidate_type'],'robot_exclusion':e['robot_exclusion'],'contributing_cameras':[v['camera'] for v in e['views']],
            'multiview_supported':any(x['supported'] for x in e['association_evidence']),'scores':metrics,'uniquely_supported_GT':supported[0] if len(supported)==1 else None,'potential_merge_GT_objects':mixed if len(mixed)>1 else [],'point_count':len(pts)}
        if len(supported)==1:
            matches[supported[0]].append(identity);gt=next(g for g in truth['objects'] if g['setup_name']==supported[0])
            row['center_error_m']=float(np.linalg.norm(np.array(e['point_world_m'])-gt['pose_world_xyz_wxyz'][:3])) if e['point_world_m'] else None
        rows.append(row)
    score={'status':'S1_DEVELOPMENT_ONLY_NOT_CROSS_LAYOUT_ACCEPTANCE','scored_unix':time.time(),'prediction_seal_sha256':sha(r/'PREDICTION_SEAL.json'),'GT_sha256':sha(args.truth),
        'candidate_count':len(rows),'rows':rows,'GT_matches':matches,'missed_measurable_cubes':[k for k,v in matches.items() if not v],'split_cube_candidates':{k:v for k,v in matches.items() if len(v)>1},
        'merged_cube_candidates':[x['geometry_instance_id'] for x in rows if x['potential_merge_GT_objects']],
        'robot_assessment':'FK-linked regions remain unknown; remaining non-cube geometry needs independent RGB review; actor GT does not annotate all robot parts',
        'GT_used_for_prediction':False,'GT_not_used_to_change_parameters':True,'green_planar_region':'outside depth-height discovery scope','independent_scene_count':1}
    out=r/'results/score';out.mkdir(exist_ok=False);(out/'SCORE.json').write_text(json.dumps(score,indent=2))
    print(json.dumps({'candidates':len(rows),'matches':matches,'rows':[{k:v for k,v in x.items() if k!='scores'} for x in rows]},indent=2))
if __name__=='__main__':main()
