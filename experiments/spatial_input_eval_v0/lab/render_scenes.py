#!/usr/bin/env python3
"""Real GPU rendering and simulator-state export. Contains no inference entry point."""
import argparse
import copy
import hashlib
import json
from importlib.metadata import version
from pathlib import Path
import platform
import time
from types import SimpleNamespace

import numpy as np
from PIL import Image
import sapien
from transforms3d.quaternions import mat2quat

from robotwin_scene_setup import setup_scene
from scene_specs import scenes
from spatial_eval.data import geometry, box
from spatial_eval.inputs import FRAME, load_snapshot, build_input
from spatial_eval.schema import write


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_solid(scene, b, color):
    builder = scene.create_actor_builder()
    builder.add_box_collision(half_size=np.asarray(b['size_m'])/2)
    builder.add_box_visual(half_size=np.asarray(b['size_m'])/2, material=color)
    actor = builder.build_static(name=b['id'])
    actor.set_pose(sapien.Pose(b['center_m'], b['quaternion_wxyz']))
    return actor


def export_solid(actor):
    """Read size and pose back from PhysX; do not copy the declared answer geometry."""
    component = actor.find_component_by_type(sapien.physx.PhysxRigidStaticComponent)
    shapes = component.collision_shapes
    if len(shapes) != 1 or not isinstance(shapes[0], sapien.physx.PhysxCollisionShapeBox):
        raise ValueError('NON_BOX_SIMULATOR_GEOMETRY')
    shape = shapes[0]
    pose = actor.get_pose() * shape.local_pose
    return box(actor.name, pose.p.tolist(), (2*np.asarray(shape.half_size)).tolist(), pose.q.tolist())


def draw_region(scene, region):
    """Thin green box edges mark public task volumes; no collisions or GT solids."""
    c = np.asarray(region['center_m']); size = np.asarray(region['size_m']); t = .002
    for axis in range(3):
        others = [i for i in range(3) if i != axis]
        for a in (-1,1):
            for b in (-1,1):
                pos = c.copy(); pos[others[0]] += a*size[others[0]]/2; pos[others[1]] += b*size[others[1]]/2
                edge_size = np.full(3,t); edge_size[axis] = size[axis]
                builder = scene.create_actor_builder()
                builder.add_box_visual(half_size=edge_size/2, material=[.12,.70,.22])
                actor = builder.build_static(name='annotation_'+region['id'])
                actor.set_pose(sapien.Pose(pos))


def camera_pose(position, target):
    position = np.asarray(position,dtype=float)
    forward = np.asarray(target)-position; forward /= np.linalg.norm(forward)
    left = np.cross([0,0,1],forward); left /= np.linalg.norm(left)
    up = np.cross(forward,left)
    return sapien.Pose(position,mat2quat(np.stack([forward,left,up],axis=1)))


def capture(spec, output):
    output.mkdir(parents=True,exist_ok=False); assets = output/'assets'; assets.mkdir()
    private = output/'private'; private.mkdir()
    task_env = SimpleNamespace(random_light=False,render_freq=0)
    # Exact pinned RoboTwin scene setup only; robot/controller imports never run.
    setup_scene(task_env)
    # Existing archive disables unsupported OIDN. Raster G-buffer provides
    # deterministic, calibrated Position/Segmentation without ray-tracing noise.
    sapien.render.set_ray_tracing_denoiser('none')
    sapien.render.set_camera_shader_dir('default')
    scene = task_env.scene
    actors = {}
    for group in ('objects','obstacles'):
        for b in spec[group]:
            color = [.85,.08,.06] if b['id']=='target' else [.06,.22,.85] if b['id']=='other' else [.48,.48,.48]
            actors[b['id']] = create_solid(scene,b,color)
    for r in spec['regions']:
        if r['id'] != 'workspace': draw_region(scene,r)
    views = [('front',[-.55,-.85,.65]),('side',[.95,-.65,.70]),('overhead',[.40,.03,1.25])]
    cameras = []
    for name,p in views:
        cam = scene.add_camera(name,640,480,.90,.01,5.)
        cam.set_pose(camera_pose(p,[.43,.02,.08])); cameras.append((name,cam))
    # Static benchmark: physics is actually advanced, poses held by static actors.
    for _ in range(10): scene.step()
    truth = geometry([export_solid(actors[b['id']]) for b in spec['objects']],
                     copy.deepcopy(spec['regions']),[export_solid(actors[b['id']]) for b in spec['obstacles']])
    scene.update_render()
    rgb=[]; depths=[]; calibration={}; camera_matrices={}; qa=[]
    start=time.monotonic()
    for name,cam in cameras:
        cam.take_picture()
        rgba=cam.get_picture('Color'); position=cam.get_picture('Position'); segmentation=cam.get_picture('Segmentation')
        image=(np.clip(rgba[...,:3],0,1)*255).astype(np.uint8)
        assert image.shape==(480,640,3) and image.std()>5, 'BLANK_RENDER'
        path=assets/(name+'.png'); Image.fromarray(image).save(path)
        raw_depth=-position[...,2]
        valid=np.isfinite(position[...,:3]).all(axis=-1)&(raw_depth>.01)&(raw_depth<5.)
        depth=np.where(valid,raw_depth,0).astype(np.float32)
        np.save(assets/(name+'_depth_m.npy'),depth,allow_pickle=False)
        np.save(assets/(name+'_valid.npy'),valid,allow_pickle=False)
        np.save(assets/(name+'_segmentation.npy'),segmentation,allow_pickle=False)
        rgb.append({'camera_id':name,'path':'assets/'+path.name,'sha256':digest(path)})
        depths.append({'camera_id':name,'path':'assets/'+name+'_depth_m.npy',
                       'sha256':digest(assets/(name+'_depth_m.npy')),'validity_path':'assets/'+name+'_valid.npy',
                       'validity_sha256':digest(assets/(name+'_valid.npy')),
                       'dtype':'float32','units':'m','definition':'positive optical z = -Position[...,2]',
                       'simulation_step':10,'aligned_rgb_sha256':digest(path)})
        pose=cam.get_pose(); K=cam.get_intrinsic_matrix()[:3,:3]
        calibration[name]={'intrinsic':K.tolist(),'resolution':[640,480],
                           'pose_base_xyz_wxyz':pose.p.tolist()+pose.q.tolist(),
                           'axes':'SAPIEN pose: +x forward,+y left,+z up. Intrinsic: OpenCV +x right,+y down,+z forward.'}
        model=cam.get_model_matrix()
        camera_matrices[name]={'camera_gl_to_base':model.tolist(),
                              'camera_cv_to_base':(model@np.diag([1,-1,-1,1])).tolist()}
        # Validate actual G-buffer optical coordinates against the exported K.
        yy,xx=np.indices(depth.shape); cv=position[...,:3]*[1,-1,-1]
        proj=cv@K.T
        mask=valid.copy()
        px=proj[...,0][mask]/proj[...,2][mask]; py=proj[...,1][mask]/proj[...,2][mask]
        err=np.sqrt((px-(xx[mask]+.5))**2+(py-(yy[mask]+.5))**2)
        assert float(np.quantile(err,.99))<.05, 'DEPTH_CALIBRATION_REPROJECTION'
        target_id=actors['target'].per_scene_id
        target_mask=segmentation[...,1]==target_id
        qa.append({'camera_id':name,'rgb_std':float(image.std()),'valid_depth_pixels':int(valid.sum()),
                   'target_visible_pixels':int(target_mask.sum()),'reprojection_p99_px':float(np.quantile(err,.99)),
                   'depth_min_m':float(depth[valid].min()),'depth_max_m':float(depth[valid].max())})
    span=time.monotonic()-start
    # Oracle is geometric simulator state, while evaluation truth and witnesses
    # remain in the independent evaluator package. No trajectory is in oracle.
    snapshot={'version':'astra.scene_snapshot.v0','scene_id':spec['scene_id'],
              'provenance':'SAPIEN_GPU_SIMULATION_STATIC_NOT_REAL_CAMERA','coordinate_system':FRAME,
              'observations':{'rgb':rgb,'depth':depths,'calibration':calibration,
                              'robot_state':{'joint_names':[],'qpos_rad':[],'flange_pose_base_xyz_wxyz':None},
                              'synchronization':{'simulation_step':10,'capture_span_s':span,
                                                 'timestamp_semantics':'sequential render readback; no physics step between cameras; immutable static actors',
                                                 'same_step':True}},
              'geometry':{'reconstruction':None,'oracle':copy.deepcopy(truth)},
              'ground_truth':truth,'task':spec['tasks']}
    write(private/'simulator_truth.json',truth)
    write(private/'planning_witness.json',spec['private_witness'])
    write(private/'camera_matrices.json',camera_matrices)
    write(output/'snapshot.json',snapshot)
    loaded=load_snapshot(output/'snapshot.json')
    # Freeze only allowlisted contexts and RGB for later authorization. No inference.
    prepared=output/'model_inputs'; prepared.mkdir()
    for t in loaded['task']:
        contexts=[]
        for condition in ('RGB_MULTI_VIEW','RGB_ORACLE_3D'):
            context,manifest,images=build_input(loaded,t,condition)
            folder=prepared/t['task_id']/condition; folder.mkdir(parents=True)
            for attachment,image in zip(context['attachments'],images):
                (folder/attachment['file']).write_bytes(image.read_bytes())
            write(folder/'context.json',context); write(folder/'manifest.json',manifest)
            contexts.append(context)
        c=copy.deepcopy(contexts[1]); c['geometry']=None
        assert c==contexts[0], 'AC_INPUT_PARITY'
    if not any(x['target_visible_pixels']>20 for x in qa): raise ValueError('TARGET_NEVER_VISIBLE')
    write(output/'capture.json',{'status':'PASS','scene_id':spec['scene_id'],'engine':'SAPIEN',
                               'sapien':version('sapien'),'physics_steps':10,'timestep_s':1/250,
                               'shader':'default','denoiser':'none','cameras':qa,
                               'solid_actor_ids':{k:v.per_scene_id for k,v in actors.items()},
                               'truth_export':'PhysX box half_size and composed actor/shape pose readback',
                               'regions':'public task definitions; container walls are separate measured solids',
                               'new_model_calls':0,'hardware_connections':0})
    return output/'snapshot.json'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--scene',choices=[s['scene_id'] for s in scenes()])
    args=p.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    paths=[]
    for spec in scenes():
        if args.scene and args.scene!=spec['scene_id']: continue
        print('rendering',spec['scene_id'],flush=True)
        paths.append(str(capture(spec,args.output/spec['scene_id']).relative_to(args.output)))
    write(args.output/'index.json',{'snapshots':paths,'new_model_calls':0,'hardware_connections':0,
                                 'platform':platform.platform(),'sapien':version('sapien'),
                                 'scene_specs_sha256':digest(Path(__file__).with_name('scene_specs.py')),
                                 'renderer_sha256':digest(__file__),'upstream':json.loads(Path(__file__).with_name('upstream.json').read_text())})
    print('completed',len(paths),'real SAPIEN scenes; model_calls=0',flush=True)


if __name__=='__main__': main()
