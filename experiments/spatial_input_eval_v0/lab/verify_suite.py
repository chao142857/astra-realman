#!/usr/bin/env python3
"""Independent offline acceptance of pixels, calibration, private GT and A/C parity."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import sys

import numpy as np
from PIL import Image
from spatial_eval.inputs import load_snapshot, build_input
from spatial_eval.geometry import axes, contains
from spatial_eval.scoring import evaluate
from spatial_eval.schema import write, parse_prediction


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def verify(root):
    index=json.loads((root/'index.json').read_text()); records=[]
    assert len(index['snapshots'])==6, 'SIX_SCENES_REQUIRED'
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'astra_realman_harness'))
    from scripts.codex_astra_mac_bridge import validate_payload
    from scripts.structured_outputs import compile_schema
    import base64
    from jsonschema import Draft202012Validator
    for rel in index['snapshots']:
        path=root/rel; folder=path.parent; s=load_snapshot(path)
        truth=json.loads((folder/'private/simulator_truth.json').read_text())
        assert s['ground_truth']==truth and s['geometry']['oracle']==truth
        target=next(b for b in truth['objects'] if b['id']=='target')
        actor_ids=json.loads((folder/'capture.json').read_text())['solid_actor_ids']
        matrices=json.loads((folder/'private/camera_matrices.json').read_text())
        pixel_tests=[]
        for rgb,d in zip(s['observations']['rgb'],s['observations']['depth']):
            name=rgb['camera_id']; Image.open(rgb['path']).verify()
            depth=np.load(folder/d['path'],allow_pickle=False); valid=np.load(folder/d['validity_path'],allow_pickle=False)
            seg=np.load(folder/'assets'/f'{name}_segmentation.npy',allow_pickle=False)
            assert sha(folder/d['path'])==d['sha256'] and sha(folder/d['validity_path'])==d['validity_sha256']
            assert d['aligned_rgb_sha256']==rgb['sha256'] and d['simulation_step']==10
            assert depth.dtype==np.float32 and depth.shape==(480,640) and np.isfinite(depth).all()
            assert valid.dtype==bool and (depth[~valid]==0).all() and valid.sum()>1000
            # Independently lift visible solid pixels using K and the measured extrinsic.
            K=np.asarray(s['observations']['calibration'][name]['intrinsic'])
            cv2base=np.asarray(matrices[name]['camera_cv_to_base'])
            for b in truth['objects']:
                mask=(seg[...,1]==actor_ids[b['id']])&valid
                ys,xs=np.nonzero(mask)
                if not len(xs): continue
                stride=max(1,len(xs)//500); ys=ys[::stride]; xs=xs[::stride]
                rays=np.stack([xs+.5,ys+.5,np.ones(len(xs))],axis=1)@np.linalg.inv(K).T
                cam=rays*depth[ys,xs,None]
                points=cam@cv2base[:3,:3].T+cv2base[:3,3]
                local=(points-b['center_m'])@np.asarray(axes(b['quaternion_wxyz'])).T
                distances=np.abs(np.abs(local)-np.asarray(b['size_m'])/2)
                surface_error=distances.min(axis=1)
                outside=np.maximum(np.abs(local)-np.asarray(b['size_m'])/2,0).max(axis=1)
                assert surface_error.max()<.001 and outside.max()<.001, 'RGBD_GT_EXTRINSIC_MISMATCH'
                pixel_tests.append({'camera':name,'object':b['id'],'samples':len(xs),
                                    'surface_max_error_m':float(surface_error.max())})
        assert pixel_tests, 'NO_GEOMETRY_PIXELS_VERIFIED'
        witness=json.loads((folder/'private/planning_witness.json').read_text())
        plan=s['task'][1]; parse_prediction(json.dumps(witness),plan)
        good=evaluate(s,plan,witness); assert good['success'], (s['scene_id'],good)
        bad=copy.deepcopy(witness); bad['position_m']=[2,2,2]
        if plan['kind']=='path': bad['waypoints_m']=[bad['position_m']]
        assert evaluate(s,plan,bad)['score']==0
        if plan['kind']=='path':
            shortcut=copy.deepcopy(witness); shortcut['waypoints_m']=[witness['position_m']]
            assert not evaluate(s,plan,shortcut)['constraints']['continuous_path_collision_free']
        if 'rotated_fit' in s['scene_id']:
            region=next(r for r in truth['regions'] if r['id']=='task_volume')
            aligned=copy.deepcopy(target); aligned.update(center_m=region['center_m'],quaternion_wxyz=[1,0,0,0])
            assert not contains(region,aligned)
            aligned['quaternion_wxyz']=witness['quaternion_wxyz']; assert contains(region,aligned)
        if 'narrow_container' in s['scene_id']:
            region=next(r for r in truth['regions'] if r['id']=='task_volume')
            aligned=copy.deepcopy(target); aligned.update(center_m=region['center_m'],quaternion_wxyz=[1,0,0,0])
            assert not contains(region,aligned)
        if 'occlusion' in s['scene_id']:
            views=json.loads((folder/'capture.json').read_text())['cameras']
            counts={v['camera_id']:v['target_visible_pixels'] for v in views}
            assert counts['front']<counts['side']*.35 and counts['overhead']>50, ('OCCLUSION_NOT_ESTABLISHED',counts)
        s['ground_truth']['PRIVATE_CANARY']='PRIVATE_GT_CANARY_MUST_NEVER_ENTER_MODEL'
        for t in s['task']:
            a,ma,ai=build_input(s,t,'RGB_MULTI_VIEW'); c,mc,ci=build_input(s,t,'RGB_ORACLE_3D')
            assert a['geometry'] is None and ai==ci and ma['task_prompt_sha256']==mc['task_prompt_sha256']
            cc=copy.deepcopy(c); cc['geometry']=None; assert a==cc
            assert 'PRIVATE_GT_CANARY' not in json.dumps(c)
            for condition,context in [('RGB_MULTI_VIEW',a),('RGB_ORACLE_3D',c)]:
                prepared=folder/'model_inputs'/t['task_id']/condition
                assert json.loads((prepared/'context.json').read_text())==context
                assert sorted(p.name for p in prepared.iterdir())==['context.json','image-0.png','image-1.png','image-2.png','manifest.json']
                assert sha(prepared/'image-0.png')==sha(ai[0])
                schema,_=compile_schema(context['output_schema']); Draft202012Validator.check_schema(schema)
                validate_payload({'context':context,'images':[base64.b64encode(p.read_bytes()).decode() for p in ai],
                                  'schema':schema,'authoritative_schema':context['output_schema']})
        records.append({'scene_id':s['scene_id'],'status':'PASS','rgbd_gt_checks':pixel_tests,
                        'planning_witness':'PASS_PRIVATE_EVALUATOR_ONLY','negative_control':'PASS',
                        'ac_parity_and_gt_canary':'PASS'})
    return records


def isolation_probe(input_folder, result_path):
    """Actual no-network bwrap with only frozen model input, no auth or evaluator mounts."""
    code=('import json, pathlib; p=pathlib.Path("/input"); '
          'files=sorted(x.name for x in p.iterdir()); '
          'assert files==["context.json","image-0.png","image-1.png","image-2.png","manifest.json"]; '
          'c=json.loads((p/"context.json").read_text()); '
          'assert "ground_truth" not in c; '
          'assert not pathlib.Path("/home/tongji/alex").exists(); '
          'assert not pathlib.Path("/private").exists(); '
          'print(json.dumps({"status":"PASS","files":files,"auth_mounted":False,"network":"unshared","model_calls":0}))')
    cmd=['bwrap','--unshare-all','--die-with-parent','--new-session','--ro-bind','/usr','/usr',
         '--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--proc','/proc','--dev','/dev',
         '--tmpfs','/tmp','--ro-bind',str(input_folder.resolve()),'/input',
         '--chdir','/input','/usr/bin/python3','-I','-c',code]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
    write(result_path,{'command':cmd,'return_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'new_model_calls':0})
    assert result.returncode==0, 'INPUT_ONLY_SANDBOX_FAILED'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--suite',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    records=verify(args.suite)
    first=args.suite/json.loads((args.suite/'index.json').read_text())['snapshots'][0]
    for condition in ('RGB_MULTI_VIEW','RGB_ORACLE_3D'):
        isolation_probe(first.parent/'model_inputs/understand'/condition,args.output/('isolation_'+condition+'.json'))
    write(args.output/'acceptance.json',{'status':'PASS','scenes':records,'scene_count':len(records),
                                       'rgb_images':18,'tasks':12,'prepared_ac_inputs':24,
                                       'all_24_provider_payloads':'PASS_OFFLINE_VALIDATION',
                                       'real_model_calls':0,'new_hardware_connections':0,
                                       'limitations':['Static box geometry; no IK, robot, dynamics, support or stability scoring',
                                                     'GT exported from simulator collision shapes; oracle and evaluator share simulator provenance',
                                                     'No B reconstruction or model capability conclusion']})
    write(args.output/'data_seal.json',{str(x.relative_to(args.suite)):sha(x) for x in sorted(args.suite.rglob('*')) if x.is_file()})
    print('PASS: six real simulations, 18 RGB-D views, 12 tasks, 24 frozen A/C inputs; real_calls=0')


if __name__=='__main__': main()
