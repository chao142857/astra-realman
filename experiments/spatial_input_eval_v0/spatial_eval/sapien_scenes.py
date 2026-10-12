"""Static SAPIEN RGB-D export. No owner, robot, model, IK or controller imports.

GT is extracted from live PhysX actor poses and collider half-sizes after capture,
not from nominal setup parameters. Static scenes do not claim dynamic feasibility.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import time

from .data import geometry, questions, task
from .geometry import box
from .inputs import FRAME, load_snapshot, build_input
from .schema import write, read


def configurations():
    result = []
    for index, name in enumerate(('clear', 'occluded', 'narrow_container',
                                 'rotated_cuboid', 'thin_obstacle', 'detour_wall')):
        result.append({'scene_id':'sapien_v0_'+name, 'kind':'placement' if index in (0,2,3) else 'path',
            'target_size_m':[.11,.045,.065] if index==3 else [.06,.06,.08],
            'target_quaternion_wxyz':[math.cos(math.pi/8),0,0,math.sin(math.pi/8)] if index==3 else [1,0,0,0],
            'interior_size_m':[.125,.085,.12] if index==2 else [.18,.16,.18],
            'obstacle':None if index in (0,2,3) else {
                'center_m':[.17,-.28,.13] if index==1 else [.40,0,.13],
                'size_m':[.25,.025,.26] if index==1 else [.01,.30,.26] if index==4 else [.04,.55,.26]}})
    return {'version':'static_sapien_scenes.v0', 'resolution':[640,480],
            'camera_positions_m':[[.15,-.85,.65],[.85,.65,.65],[.42,0,1.05]],
            'camera_look_at_m':[.40,0,.08], 'scenes':result}


def collider_state(actors, sapien):
    """Read the actual simulation state; refuse unsupported collider types."""
    records = []
    for actor, role in actors:
        body = actor.find_component_by_type(sapien.physx.PhysxRigidStaticComponent)
        shapes = body.collision_shapes
        if len(shapes)!=1 or not isinstance(shapes[0], sapien.physx.PhysxCollisionShapeBox):
            raise ValueError('BOX_COLLIDER_REQUIRED')
        shape = shapes[0]
        pose = actor.pose * shape.local_pose
        records.append({'id':actor.name, 'role':role, 'pose_xyz_wxyz':
                        [float(v) for v in pose.p]+[float(v) for v in pose.q],
                        'half_size_m':[float(v) for v in shape.half_size],
                        'actor_pose_xyz_wxyz':[float(v) for v in actor.pose.p]+[float(v) for v in actor.pose.q],
                        'collider_local_pose_xyz_wxyz':[float(v) for v in shape.local_pose.p]+[float(v) for v in shape.local_pose.q]})
    return records


def truth_from_state(state):
    """Independent extraction using only exported collision state, no setup config."""
    solids = {r['id']:box(r['id'],r['pose_xyz_wxyz'][:3],
                         [2*x for x in r['half_size_m']],r['pose_xyz_wxyz'][3:]) for r in state}
    # Containers here are axis aligned. Derive free interior from actual inner faces.
    for name in ('container_x_minus','container_x_plus','container_y_minus','container_y_plus','container_floor'):
        if solids[name]['quaternion_wxyz'] != [1,0,0,0]:
            raise ValueError('AXIS_ALIGNED_CONTAINER_REQUIRED')
    xm,xp,ym,yp,floor = [solids[name] for name in ('container_x_minus','container_x_plus',
                           'container_y_minus','container_y_plus','container_floor')]
    low = [xm['center_m'][0]+xm['size_m'][0]/2, ym['center_m'][1]+ym['size_m'][1]/2,
           floor['center_m'][2]+floor['size_m'][2]/2]
    high = [xp['center_m'][0]-xp['size_m'][0]/2, yp['center_m'][1]-yp['size_m'][1]/2,
            min(w['center_m'][2]+w['size_m'][2]/2 for w in (xm,xp,ym,yp))]
    if any(h<=l for l,h in zip(low,high)):
        raise ValueError('EMPTY_CONTAINER')
    region = box('container_interior', [(l+h)/2 for l,h in zip(low,high)], [h-l for l,h in zip(low,high)])
    # Workspace is a declared task constraint, not a measured solid or a solution.
    workspace = box('workspace',[.45,0,.30],[.90,.90,.58])
    objects = [solids[r['id']] for r in state if r['role']=='object']
    obstacles = [solids[r['id']] for r in state if r['role']!='object']
    return geometry(objects,[region,workspace],obstacles)


def export(config_path, output):
    import numpy as np
    import sapien
    from PIL import Image
    from transforms3d.quaternions import mat2quat
    cfg = read(config_path)
    output = Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    write(output/'config.json',cfg)
    manifest = {'source':'LIVE_SAPIEN_RENDERER_STATIC_PHYSX_COLLIDERS', 'sapien_version':sapien.__version__,
                'real_model_calls':0, 'physics_steps':0, 'robot_controllers':0, 'reconstruction':None,
                'scenes':[], 'coordinate_transform':'world == robot_base, identity; no physical robot present',
                'limitations':'Static geometric scenes. No grasp, support, dynamics, IK or robot calibration validation.'}
    write(output/'manifest.json',manifest)
    for setup in cfg['scenes']:
        folder = output/setup['scene_id']; folder.mkdir(); assets=folder/'assets'; assets.mkdir()
        scene = sapien.Scene()
        scene.set_ambient_light([.45,.45,.45])
        scene.add_directional_light([0,1,-1],[2.5,2.5,2.5],shadow=True)
        actors=[]
        def solid(name, center, size, color, role='obstacle', q=None):
            builder=scene.create_actor_builder()
            builder.add_box_collision(half_size=np.array(size)/2)
            builder.add_box_visual(half_size=np.array(size)/2, material=color)
            builder.set_initial_pose(sapien.Pose(center,q or [1,0,0,0]))
            actor=builder.build_static(name=name); actors.append((actor,role)); return actor
        solid('table',[.45,0,-.025],[1.10,1.10,.05],[.62,.64,.67,1])
        solid('target_cube',[.20,-.18,.06],setup['target_size_m'],[.85,.08,.08,1],
              'object',setup['target_quaternion_wxyz'])
        solid('blue_distractor',[.30,.03,.035],[.07,.05,.07],[.07,.18,.85,1],'object')
        cx,cy=.62,.18
        sx,sy,sz=setup['interior_size_m']; thick=.02; bottom=.01
        solid('container_floor',[cx,cy,bottom/2],[sx+2*thick,sy+2*thick,bottom],[.12,.55,.26,1])
        for axis in (0,1):
            for side,label in ((-1,'minus'),(1,'plus')):
                center=[cx,cy,bottom+sz/2]; center[axis]+=side*([sx,sy][axis]/2+thick/2)
                size=[sx+2*thick,sy+2*thick,sz]; size[axis]=thick
                solid('container_'+('x' if axis==0 else 'y')+'_'+label,center,size,[.12,.55,.26,1])
        if setup['obstacle']:
            solid('barrier',setup['obstacle']['center_m'],setup['obstacle']['size_m'],[.7,.45,.07,1])
        cameras=[]; w,h=cfg['resolution']; look=np.array(cfg['camera_look_at_m'])
        for i,pos in enumerate(cfg['camera_positions_m']):
            cam=scene.add_camera('view_%d'%i,w,h,math.radians(60),.01,5.)
            forward=look-np.array(pos); forward/=np.linalg.norm(forward)
            left=np.cross([0,0,1],forward); left/=np.linalg.norm(left)
            up=np.cross(forward,left)
            cam.set_pose(sapien.Pose(pos,mat2quat(np.stack([forward,left,up],axis=1))))
            cameras.append(cam)
        before=collider_state(actors,sapien)
        scene.update_render()  # No physics step between views.
        started=time.monotonic(); rgb=[]; depth=[]; calib={}
        for cam in cameras:
            cam.take_picture()
            color=cam.get_picture('Color'); position=cam.get_picture('Position')
            pixels=(np.clip(color[:,:,:3],0,1)*255).astype(np.uint8)
            dep=-position[:,:,2]
            valid=np.isfinite(dep)&(position[:,:,3]<1)&(dep>.01)&(dep<5)
            dep=np.where(valid,dep,0).astype('<f4')
            if not np.any(valid) or pixels.std()<2:
                raise ValueError('EMPTY_RENDER')
            rgbfile=assets/(cam.name+'.png'); Image.fromarray(pixels).save(rgbfile)
            depthfile=assets/(cam.name+'.depth.npy'); np.save(depthfile,dep,allow_pickle=False)
            maskfile=assets/(cam.name+'.valid.png'); Image.fromarray(valid.astype(np.uint8)*255).save(maskfile)
            digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            rgb.append({'camera_id':cam.name,'path':'assets/'+rgbfile.name,'sha256':digest(rgbfile)})
            depth.append({'camera_id':cam.name,'depth':{'file':'assets/'+depthfile.name,'sha256':digest(depthfile)},
                          'validity':{'file':'assets/'+maskfile.name,'sha256':digest(maskfile)},
                          'units':'m','dtype':'<f4','aligned_rgb_sha256':digest(rgbfile),
                          'simulation_step':0,'same_physics_step_three_views':True,
                          'valid_pixel_count':int(valid.sum()),'semantics':'optical Z depth = -Position.z; zero invalid'})
            calib[cam.name]={'intrinsic':cam.get_intrinsic_matrix().tolist(),'resolution':[w,h],
                            'pose_base_xyz_wxyz':cam.get_pose().p.tolist()+cam.get_pose().q.tolist(),
                            'axes':'SAPIEN camera pose: +X forward, +Y left, +Z up; RGB/depth optical axes +X right,+Y down,+Z forward'}
        span=time.monotonic()-started
        state=collider_state(actors,sapien)
        if before!=state:
            raise ValueError('STATE_CHANGED_DURING_CAPTURE')
        write(folder/'physics_state.json',state)
        # Read the sealed state back into an independent extractor.
        gt=truth_from_state(read(folder/'physics_state.json'))
        region=next(b for b in gt['regions'] if b['id']=='container_interior')
        qs=questions('target_cube','blue_distractor')
        qs.append({'question_id':'fits','type':'fit','object_id':'target_cube','region_id':region['id'],
                   'quaternion_wxyz':[1,0,0,0]})
        region_text=' Container interior center '+json.dumps(region['center_m'])+' m, size '+json.dumps(region['size_m'])+' m.'
        c={'object_id':'target_cube','allowed_region_id':region['id'],'clearance_m':.002,
           'required_quaternion_wxyz':[1,0,0,0],'orientation_tolerance_rad':.05}
        if setup['kind']=='path':
            c.update(start_position_m=[.20,-.18,.06],workspace_region_id='workspace')
        tasks=[task('understanding','understand',questions=qs,instruction=
                    'The red object is target_cube; the blue object is blue_distractor. Answer the specified positive-base-axis relations, center, top height, size, gap and oriented fit.'+region_text),
               task(setup['kind'],'plan',constraints=c,instruction=
                    'Place the red target_cube fully inside container_interior with axes aligned to base, avoiding all other solids by 0.002 m. '
                    +('Plan carried-object waypoints from start [0.20,-0.18,0.06] m with fixed identity orientation; workspace center [0.45,0,0.30] size [0.90,0.90,0.58] m. ' if setup['kind']=='path' else '')
                    +'Static geometric task only; no support or dynamics requirement.'+region_text)]
        snapshot={'version':'astra.scene_snapshot.v0','scene_id':setup['scene_id'],
                  'provenance':'LIVE_SAPIEN_STATIC_RGBD_NOT_REAL_CAMERA','coordinate_system':FRAME,
                  'observations':{'rgb':rgb,'depth':depth,'calibration':calib,
                                  'robot_state':{'joint_names':[],'qpos_rad':[],'flange_pose_base_xyz_wxyz':None},
                                  'synchronization':{'simulation_step':0,'capture_span_s':span,
                                    'timestamp_semantics':'same static scene; sequential renderer acquisition; no physics step', 'same_step':True}},
                  'geometry':{'reconstruction':None,'oracle':copy.deepcopy(gt)},'ground_truth':gt,'task':tasks}
        write(folder/'snapshot.json',snapshot)
        loaded=load_snapshot(folder/'snapshot.json')
        for t in tasks:
            for condition in ('RGB_MULTI_VIEW','RGB_ORACLE_3D'):
                context,_,_=build_input(loaded,t,condition)
                if 'ground_truth' in context:
                    raise ValueError('GT_BOUNDARY')
        seal={p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in folder.rglob('*') if p.is_file()}
        write(folder/'SEAL.json',{'sha256':seal,'binding':'unchanged collider state before/after synchronized RGB-D capture',
                                'gt_source':'physics_state.json actual actor and collider values; no setup poses read'})
        manifest['scenes'].append({'scene_id':setup['scene_id'],'task_count':2,'rgb_count':3,'depth_count':3,
                                  'snapshot':'%s/snapshot.json'%setup['scene_id'],'seal_sha256':hashlib.sha256((folder/'SEAL.json').read_bytes()).hexdigest()})
        write(output/'manifest.json',manifest)
        print(setup['scene_id']+' RGBD/GT PASS',flush=True)
        del cameras, actors, scene
    manifest['status']='PASS'; write(output/'manifest.json',manifest)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--config',type=Path)
    p.add_argument('--write-default-config',action='store_true')
    a=p.parse_args()
    if a.write_default_config:
        if a.output.exists(): raise ValueError('REFUSE_OVERWRITE')
        write(a.output,configurations()); return
    if not a.config: p.error('--config required for export')
    export(a.config,a.output)


if __name__=='__main__': main()
