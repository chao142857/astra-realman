#!/usr/bin/env python3
"""Render deterministic Pilot02 previews using existing RoboTwin/SAPIEN setup only."""
import argparse
import copy
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from importlib.metadata import version
import numpy as np
from PIL import Image, ImageDraw
import sapien
from robotwin_scene_setup import setup_scene
from render_scenes import create_solid, export_solid, camera_pose
from spatial_eval.data import geometry
from spatial_eval.geometry import axes
from spatial_eval.inputs import FRAME, load_snapshot
from spatial_eval.schema import write
from pilot02_specs import specs
from pilot02_contract import build, policy_for

RESOLUTION=(960,720)
VIEWS=[('front',[-.25,-.80,.80]),('opposite',[1.12,.72,.90]),('overhead',[.48,.00,1.15])]
LOOK_AT=[.46,-.045,.10]

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def outline(scene, region):
    # Full orientation-aware public wireframe, including workspace height boundary.
    c=np.array(region['center_m']); size=np.array(region['size_m']); R=np.array(axes(region['quaternion_wxyz'])).T
    for axis in range(3):
        other=[i for i in range(3) if i!=axis]
        for a in (-1,1):
            for b in (-1,1):
                offset=np.zeros(3); offset[other[0]]=a*size[other[0]]/2; offset[other[1]]=b*size[other[1]]/2
                extent=np.full(3,.0015); extent[axis]=size[axis]
                builder=scene.create_actor_builder(); builder.add_box_visual(half_size=extent/2,material=[.12,.7,.22])
                actor=builder.build_static(name='annotation_'+region['id'])
                actor.set_pose(sapien.Pose(c+R@offset,region['quaternion_wxyz']))

def capture(s, out):
    out.mkdir(); assets=out/'assets'; assets.mkdir(); private=out/'private'; private.mkdir()
    env=SimpleNamespace(random_light=False,render_freq=0); setup_scene(env)
    sapien.render.set_ray_tracing_denoiser('none'); sapien.render.set_camera_shader_dir('default')
    scene=env.scene; actors={}
    for group in ('objects','obstacles'):
        for b in s[group]: actors[b['id']]=create_solid(scene,b,[.85,.08,.06] if b['id']=='target' else [.48,.48,.48])
    for r in s['regions']: outline(scene,r)
    cams=[]
    for name,p in VIEWS:
        cam=scene.add_camera(name,*RESOLUTION,.90,.01,5.); cam.set_pose(camera_pose(p,LOOK_AT)); cams.append((name,cam))
    for _ in range(10): scene.step()
    gt=geometry([export_solid(actors[b['id']]) for b in s['objects']],copy.deepcopy(s['regions']),
                [export_solid(actors[b['id']]) for b in s['obstacles']])
    scene.update_render(); rgb=[]; depth=[]; calibration={}; matrices={}; qa=[]; started=time.monotonic()
    for name,cam in cams:
        cam.take_picture(); rgba=cam.get_picture('Color'); pos=cam.get_picture('Position'); seg=cam.get_picture('Segmentation')
        im=(np.clip(rgba[...,:3],0,1)*255).astype(np.uint8); path=assets/f'{name}.png'; Image.fromarray(im).save(path)
        z=-pos[...,2]; valid=np.isfinite(pos[...,:3]).all(axis=-1)&(z>.01)&(z<5.)
        z=np.where(valid,z,0).astype(np.float32)
        data_path=assets/f'{name}_rgbd.npz'; np.savez_compressed(data_path,depth_m=z,valid=valid,segmentation=seg)
        K=cam.get_intrinsic_matrix()[:3,:3]; pose=cam.get_pose(); cv2base=cam.get_model_matrix()@np.diag([1,-1,-1,1])
        calibration[name]={'intrinsic':K.tolist(),'resolution':list(RESOLUTION),'pose_base_xyz_wxyz':pose.p.tolist()+pose.q.tolist(),
                           'axes':'SAPIEN pose: +x forward,+y left,+z up. Intrinsic: OpenCV +x right,+y down,+z forward.'}
        matrices[name]={'camera_cv_to_base':cv2base.tolist()}
        yy,xx=np.indices(z.shape); cv=pos[...,:3]*[1,-1,-1]; proj=cv@K.T
        error=np.hypot(proj[...,0][valid]/proj[...,2][valid]-(xx[valid]+.5),proj[...,1][valid]/proj[...,2][valid]-(yy[valid]+.5))
        assert float(np.quantile(error,.99))<.05
        rgb.append({'camera_id':name,'path':str(path.relative_to(out)),'sha256':sha(path)})
        depth.append({'camera_id':name,'path':str(data_path.relative_to(out)),'sha256':sha(data_path),
                      'format':'npz lossless: depth_m float32, valid bool, segmentation uint32',
                      'definition':'positive optical z = -Position[...,2]','units':'m','simulation_step':10,
                      'aligned_rgb_sha256':sha(path)})
        qa.append({'camera_id':name,'rgb_std':float(im.std()),'valid_pixels':int(valid.sum()),'reprojection_p99_px':float(np.quantile(error,.99)),
                   'visible_pixels':{k:int((seg[...,1]==v.per_scene_id).sum()) for k,v in actors.items()}})
    snapshot={'version':'astra.scene_snapshot.v0','scene_id':s['scene_id'],'provenance':'SAPIEN_GPU_SIMULATION_STATIC_NOT_REAL_CAMERA',
              'coordinate_system':FRAME,'observations':{'rgb':rgb,'depth':depth,'calibration':calibration,
              'robot_state':{'joint_names':[],'qpos_rad':[],'flange_pose_base_xyz_wxyz':None},
              'synchronization':{'simulation_step':10,'capture_span_s':time.monotonic()-started,'same_step':True,
              'timestamp_semantics':'sequential readback from immutable static actors; no physics step between views'}},
              'geometry':{'reconstruction':None,'oracle':copy.deepcopy(gt)},'ground_truth':gt,'task':[s['task']]}
    write(out/'snapshot.json',snapshot); write(out/'task_policy.json',policy_for(s))
    write(private/'simulator_truth.json',gt); write(private/'camera_matrices.json',matrices)
    write(private/'design_and_controls.json',s)
    write(out/'capture.json',{'engine':'SAPIEN','version':version('sapien'),'physics_steps':10,'cameras':qa,
                            'solid_actor_ids':{k:v.per_scene_id for k,v in actors.items()},
                            'geometry_source':'PhysX box half-sizes and actor/shape pose readback',
                            'new_model_calls':0,'hardware_connections':0})
    loaded=load_snapshot(out/'snapshot.json')
    for cond in ('RGB_MULTI_VIEW','RGB_ORACLE_3D'):
        context,manifest,images=build(loaded,loaded['task'][0],cond,policy_for(s)); folder=out/'model_inputs'/cond; folder.mkdir(parents=True)
        write(folder/'context.json',context); write(folder/'manifest.json',manifest)
        for a,img in zip(context['attachments'],images): (folder/a['file']).write_bytes(img.read_bytes())
    return str((out/'snapshot.json').relative_to(out.parent))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True); p.add_argument('--single-scene',choices=[s['scene_id'] for s in specs()]); a=p.parse_args()
    if a.single_scene:
        capture(next(s for s in specs() if s['scene_id']==a.single_scene),a.output)
        return
    a.output.mkdir(parents=True,exist_ok=False)
    design=specs(); write(a.output/'design_before_render.json',{'selection':'10 deterministic pre-model designs; all attempts retained; no model-based selection',
                'specifications':design,'new_generation_budget':0,'camera_positions':VIEWS,'look_at':LOOK_AT,'resolution':RESOLUTION,
                'scene_spec_sha256':sha(Path(__file__).with_name('pilot02_specs.py'))})
    paths=[]
    for s in design:
        print('SAPIEN rendering',s['scene_id'],flush=True)
        # Fresh process releases Vulkan/SAPIEN global resources after each scene.
        subprocess.run([sys.executable,'-B',__file__,'--single-scene',s['scene_id'],'--output',str(a.output/s['scene_id'])],check=True)
        paths.append(s['scene_id']+'/snapshot.json')
    write(a.output/'index.json',{'snapshots':paths,'platform':platform.platform(),'sapien':version('sapien'),
            'real_model_calls':0,'hardware_connections':0,'renderer_sha256':sha(__file__)})
    # Thumbnails derived from actual SAPIEN RGB only, annotated as review, never model inputs.
    sheet=Image.new('RGB',(1200,10*320),'white'); d=ImageDraw.Draw(sheet)
    for i,rel in enumerate(paths):
        folder=(a.output/rel).parent
        for j,(name,_) in enumerate(VIEWS):
            with Image.open(folder/'assets'/f'{name}.png') as im: sheet.paste(im.resize((400,300)),(j*400,i*320+20))
            d.text((j*400+5,i*320+3),folder.name+' / '+name,fill='black')
    sheet.save(a.output/'preview_all.png'); print('PASS: 10 actual SAPIEN captures / 30 RGB-D views / 20 A/C contexts; real calls=0')

if __name__=='__main__': main()
