#!/usr/bin/env python3
"""Offline physical controls, calibrated visibility, A/C boundary and input-only sandbox."""
import argparse
import base64
import copy
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np
from PIL import Image
from spatial_eval.inputs import load_snapshot
from spatial_eval.geometry import axes
from spatial_eval.schema import write
from pilot02_contract import build, score, policy_for
from pilot02_specs import specs, policies
from verify_suite import isolation_probe


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def features(s):
    """Evaluator-only boundary samples; never sent to the model. Five per relevant edge."""
    points={}; samples=np.linspace(-.8,.8,5)
    if s['family']=='A_PLACEMENT_MARGIN':
        m=s['design']['nominal_per_side_gap_m']; x,y,z=s['witness']['position_m']; hx=.04+m; hy=.03+m
        for sign,label in [(-1,'minus'),(1,'plus')]:
            points['block_x_'+label]=[[x+sign*hx,y+t*hy,z+.10] for t in samples]
            points['block_y_'+label]=[[x+t*hx,y+sign*hy,z+.10] for t in samples]
    elif s['family']=='C_FREE_YAW':
        x,y,z=s['witness']['position_m']; a=math.radians(s['design']['private_slot_angle_deg'])
        for sign,label in [(-1,'minus'),(1,'plus')]:
            points['block_x_'+label]=[[sign*.08,t*.0325,.10] for t in samples]
            points['block_y_'+label]=[[t*.08,sign*.0325,.10] for t in samples]
        for k,pp in points.items(): points[k]=[[x+p[0]*math.cos(a)-p[1]*math.sin(a),y+p[0]*math.sin(a)+p[1]*math.cos(a),z+p[2]] for p in pp]
    else:
        side=s['design']['open_side']; points['barrier']=[[.48,side*.11,z] for z in np.linspace(.045,.235,5)]
    return points


def visibility(folder,s,snapshot,capture,matrices):
    # Depth points near projected edge samples prove observable boundary support;
    # 6mm radius accommodates rasterization only, never changes geometry scoring.
    feature_points=features(s); visible={k:[False]*len(v) for k,v in feature_points.items()}; rows=[]; surfaces=[]
    truth=snapshot['ground_truth']; solids=truth['objects']+truth['obstacles']
    for rgb,dep in zip(snapshot['observations']['rgb'],snapshot['observations']['depth']):
        name=rgb['camera_id']; path=folder/dep['path']; assert sha(path)==dep['sha256']
        assert dep['aligned_rgb_sha256']==rgb['sha256'] and dep['simulation_step']==10
        with np.load(path,allow_pickle=False) as arrays:
            depth=arrays['depth_m']; valid=arrays['valid']; seg=arrays['segmentation']
        assert depth.shape==(720,960) and depth.dtype==np.float32 and valid.dtype==bool
        assert np.isfinite(depth).all() and (depth[~valid]==0).all() and valid.sum()>1000
        with Image.open(rgb['path']) as im: assert im.size==(960,720) and np.asarray(im).std()>5
        K=np.array(snapshot['observations']['calibration'][name]['intrinsic']); cv2base=np.array(matrices[name]['camera_cv_to_base']); base2cv=np.linalg.inv(cv2base)
        for b in solids:
            ys,xs=np.nonzero((seg[...,1]==capture['solid_actor_ids'][b['id']])&valid)
            if not len(xs): continue
            stride=max(1,len(xs)//400); ys=ys[::stride]; xs=xs[::stride]
            rays=np.stack([xs+.5,ys+.5,np.ones(len(xs))],axis=1)@np.linalg.inv(K).T
            world=(rays*depth[ys,xs,None])@cv2base[:3,:3].T+cv2base[:3,3]
            local=(world-b['center_m'])@np.array(axes(b['quaternion_wxyz'])).T
            deviation=np.abs(np.abs(local)-np.array(b['size_m'])/2).min(axis=1)
            outside=np.maximum(np.abs(local)-np.array(b['size_m'])/2,0).max(axis=1)
            assert max(deviation.max(),outside.max())<.001, (b['id'],deviation.max(),outside.max())
            surfaces.append({'camera':name,'solid':b['id'],'samples':len(xs),'surface_max_error_m':float(deviation.max())})
        for key,pp in feature_points.items():
            for i,p in enumerate(pp):
                cv=(base2cv@np.array([*p,1]))[:3]; uvh=K@cv; uv=uvh[:2]/uvh[2]; px,py=np.floor(uv).astype(int)
                nearest=None
                if cv[2]>0 and 2<=px<958 and 2<=py<718:
                    yy,xx=np.mgrid[py-2:py+3,px-2:px+3]; mask=(seg[yy,xx,1]==capture['solid_actor_ids'][key])&valid[yy,xx]
                    if mask.any():
                        ys=yy[mask]; xs=xx[mask]; rays=np.stack([xs+.5,ys+.5,np.ones(len(xs))],axis=1)@np.linalg.inv(K).T
                        world=(rays*depth[ys,xs,None])@cv2base[:3,:3].T+cv2base[:3,3]
                        nearest=float(np.linalg.norm(world-p,axis=1).min())
                ok=nearest is not None and nearest<=.006
                visible[key][i]|=ok
                rows.append({'camera':name,'boundary':key,'sample':i,'uv_px':uv.tolist(),'nearest_same_actor_depth_point_m':nearest,'raster_visibility_pass':ok})
    counts={k:sum(v) for k,v in visible.items()}
    assert all(x>=3 for x in counts.values()), ('KEY_INNER_BOUNDARY_NOT_VISIBLE',s['scene_id'],counts)
    assert max(v['visible_pixels']['target'] for v in capture['cameras'])>50
    critical=['target',*feature_points]
    assert all(max(v['visible_pixels'][k] for v in capture['cameras'])>=20 for k in critical)
    return {'status':'PASS','critical_inner_boundary_visible_samples_of_5':counts,'boundary_projection_checks':rows,
            'rgbd_solid_surface_checks':surfaces,'caveat':'Visibility is not equal metric precision. 6mm search tests raster support only; scoring clearance is unchanged.'}


def main():
    p=argparse.ArgumentParser(); p.add_argument('--suite',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False); index=json.loads((a.suite/'index.json').read_text()); allspec=specs(); assert len(index['snapshots'])==10
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'astra_realman_harness'))
    from scripts.codex_astra_mac_bridge import validate_payload
    from scripts.structured_outputs import compile_schema
    from jsonschema import Draft202012Validator
    records=[]; policy_rows=[]
    for rel,s in zip(index['snapshots'],allspec):
        folder=(a.suite/rel).parent; snapshot=load_snapshot(folder/'snapshot.json'); task=snapshot['task'][0]
        assert snapshot['scene_id']==s['scene_id']
        policy=json.loads((folder/'task_policy.json').read_text()); assert policy==policy_for(s)
        private=json.loads((folder/'private/design_and_controls.json').read_text()); assert private==s
        truth=json.loads((folder/'private/simulator_truth.json').read_text()); assert truth==snapshot['ground_truth']==snapshot['geometry']['oracle']
        capture=json.loads((folder/'capture.json').read_text()); matrices=json.loads((folder/'private/camera_matrices.json').read_text())
        viz=visibility(folder,s,snapshot,capture,matrices); write(a.output/(s['scene_id']+'_visibility.json'),viz)
        positive=[s['witness'],*s['alternate_witnesses']]; good=[score(snapshot,task,x,policy) for x in positive]; assert all(x['score']==1 for x in good)
        negatives={k:score(snapshot,task,x,policy) for k,x in s['negative_controls'].items()}; assert all(x['score']==0 for x in negatives.values())
        other=next(t for t in allspec if t['pair_id']==s['pair_id'] and t['scene_id']!=s['scene_id'])
        swapped=score(snapshot,task,other['witness'],policy); assert swapped['score']==0
        controls={name:score(snapshot,task,pred,policy) for name,pred in policies(s).items()}
        for name,r in controls.items(): policy_rows.append({'scene_id':s['scene_id'],'pair_id':s['pair_id'],'family':s['family'],'policy':name,'score':r['score'],'failed_constraints':';'.join(r['error_types'])})
        # Poison only evaluator truth after independent export checks; oracle is a separate copy.
        snapshot['ground_truth']['PRIVATE_CANARY']='P02_PRIVATE_GT_AND_WITNESS_NEVER_SEND'
        contexts=[]
        for cond in ('RGB_MULTI_VIEW','RGB_ORACLE_3D'):
            context,manifest,images=build(snapshot,task,cond,policy); contexts.append(context); prepared=folder/'model_inputs'/cond
            assert json.loads((prepared/'context.json').read_text())==context
            assert json.loads((prepared/'manifest.json').read_text())==manifest
            assert sorted(p.name for p in prepared.iterdir())==['context.json','image-0.png','image-1.png','image-2.png','manifest.json']
            assert 'PRIVATE_CANARY' not in json.dumps(context) and 'P02_PRIVATE' not in json.dumps(context)
            assert s['scene_id'] not in json.dumps(context) and 'witness' not in json.dumps(context) and 'ground_truth' not in context
            for i,img in enumerate(images): assert sha(prepared/f'image-{i}.png')==sha(img)
            provider,_=compile_schema(context['output_schema']); Draft202012Validator.check_schema(provider)
            validate_payload({'context':context,'images':[base64.b64encode(p.read_bytes()).decode() for p in images],
                              'schema':provider,'authoritative_schema':context['output_schema']})
            isolation_probe(prepared,a.output/(s['scene_id']+'_'+cond+'_sandbox.json'))
        other_context=copy.deepcopy(contexts[1]); other_context['geometry']=None; assert contexts[0]==other_context
        # Mirror variants share exact task/policy; only scene observations and geometry change.
        assert s['task']==other['task'] and policy_for(s)==policy_for(other)
        records.append({'scene_id':s['scene_id'],'family':s['family'],'pair_id':s['pair_id'],'status':'PASS',
                        'positive_controls':good,'negative_controls':negatives,'opposite_scene_witness':swapped,'simple_policies':controls,
                        'key_boundary_visibility':viz['critical_inner_boundary_visible_samples_of_5'],
                        'ac_only_geometry_diff':True,'offline_provider_payload_validation':'PASS','input_only_sandbox':'PASS'})
    # No scene-blind policy can succeed on both members of a geometry-variation pair.
    for pair in sorted({r['pair_id'] for r in policy_rows}):
        rr=[r for r in policy_rows if r['pair_id']==pair]
        for name in {r['policy'] for r in rr}: assert sum(r['score'] for r in rr if r['policy']==name)<2
    with (a.output/'simple_policy_scores.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(policy_rows[0])); w.writeheader(); w.writerows(policy_rows)
    write(a.output/'acceptance.json',{'status':'PASS','scenes':records,'scene_count':10,'rgbd_views':30,'prepared_ac_inputs':20,
          'all_20_input_only_sandboxes':'PASS','real_model_calls':0,'hardware_connections':0,
          'limitations':['Static cuboids; no support, IK or dynamics','Private witness only proves feasibility, never a unique scoring reference',
          'All key inner boundaries have raster/depth support; visible does not imply exact 3mm metric readability',
          'Oracle supplies precise simulator geometry of visible solids; representation and precision effects remain coupled']})
    print('PASS: Pilot02 10 real scenes / 30 RGB-D views / 20 isolated A/C inputs / all controls; generation=0')

if __name__=='__main__': main()
