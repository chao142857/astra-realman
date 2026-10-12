"""Snapshot adapters. Archived simulator truth and synthetic fixtures stay labeled."""
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import zlib
from .schema import read, write
from .inputs import FRAME
from .geometry import box


def geometry(objects, regions=None, obstacles=None, source='SIMULATOR_TRUTH'):
    return {'source':source,'frame':'robot_base','units':'m','objects':objects,
            'regions':regions or [],'obstacles':obstacles or [],'renderings':[]}


def task(kind, identity, *, questions=None, constraints=None, instruction=None):
    return {'task_id':identity,'kind':kind,'frame':'robot_base','tolerance_m':.005,
            'instruction':instruction or 'Answer the specified geometric questions in robot_base, meters.',
            'questions':questions or [],'constraints':constraints or {}}


def questions(object_id, other_id):
    return [{'question_id':'relative_x','type':'relation','object_id':object_id,'other_id':other_id,'axis':'x'},
            {'question_id':'position','type':'position','object_id':object_id},
            {'question_id':'top_height','type':'height','object_id':object_id,'reference':'top'},
            {'question_id':'size','type':'size','object_id':object_id},
            {'question_id':'gap_x','type':'gap','object_id':object_id,'other_id':other_id,'axis':'x'}]


def constraints(kind):
    c={'object_id':'target_cube','allowed_region_id':'task_volume','clearance_m':.002,
       'required_quaternion_wxyz':[1,0,0,0],'orientation_tolerance_rad':.05}
    if kind=='path':c.update(start_position_m=[.1,-.1,.12],workspace_region_id='workspace')
    return c


def import_archive(archive, output):
    """S1 frozen RGBD schema only; missing independent truth stays unscored.

    Reads no action plans, reference poses, inferred world models or prior scores.
    The special S1 capture seal supplies the same-step truth binding.
    """
    archive=Path(archive).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    origin=archive/'public/o-0000';obs=read(origin/'observation.json')
    if obs.get('schema')!='astra.shared.observation.rgbd.v2' or obs['frame']!='sapien:world':raise ValueError('UNSUPPORTED_ARCHIVE')
    cfg_path=archive/'private/scene/assembly_config.json';cfg=read(cfg_path)
    offset=cfg['temporary_assembly']['base_world_xyz_m']
    def to_base(p):return [p[i]-offset[i] for i in range(3)]+p[3:]
    assets=output/'assets';assets.mkdir();rgb=[];depth=[]
    seals=read(archive/'PUBLIC_SEAL.json')['public_files'] if (archive/'PUBLIC_SEAL.json').exists() else None
    if seals is not None:
        for name,expected in seals.items():
            actual=hashlib.sha256((archive/'public'/name).read_bytes()).hexdigest()
            if actual!=expected:raise ValueError('ARCHIVE_PUBLIC_SEAL_MISMATCH')
    for item in obs['rgb']:
        data=(origin/item['file']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('ARCHIVE_IMAGE_HASH')
        (assets/item['file']).write_bytes(data)
        rgb.append({'camera_id':item['camera'],'path':'assets/'+item['file'],'sha256':item['sha256']})
    for item in obs.get('depth',[]):
        if item['simulation_step']!=obs['state']['sim_step'] or item['same_physics_step_three_views'] is not True:raise ValueError('DEPTH_STEP_BINDING')
        if item['aligned_rgb_sha256']!=next(x['sha256'] for x in obs['rgb'] if x['camera']==item['camera']):raise ValueError('RGBD_ALIGNMENT_BINDING')
        copied=copy.deepcopy(item)
        for key in ('depth','validity'):
            data=(origin/item[key]['file']).read_bytes()
            if hashlib.sha256(data).hexdigest()!=item[key]['sha256']:raise ValueError('ARCHIVE_DEPTH_HASH')
            (assets/item[key]['file']).write_bytes(data);copied[key]['file']='assets/'+item[key]['file']
        depth.append(copied)
    calib={}
    for name,c in obs['calibration'].items():
        calib[name]={'intrinsic':c['intrinsic'],'resolution':c['resolution'],
                     'pose_base_xyz_wxyz':to_base(c['pose_world_xyz_wxyz']),'axes':c['axes']}
    state=obs['state']
    robot={'joint_names':state['joint_names'],'qpos_rad':state['qpos'],
           'flange_pose_base_xyz_wxyz':to_base(state['flange_pose_world'])}
    gt=None;truth_path=archive/'private/SCORING_TRUTH.json'
    # A region defined by the NEW task, not an archived placement solution.
    region=box('task_volume',[.35,.20,.045],[.18,.14,.15])
    if truth_path.exists():
        result=read(archive/'RESULT.json')
        if seals is None or result['observation_id']!=obs['observation_id'] or result['final_step']!=state['sim_step']:
            raise ValueError('UNBOUND_ARCHIVE_TRUTH')
        truth=read(truth_path)
        if truth['source']!='PRIVATE_SIMULATOR_TRUTH_NOT_MODEL_INPUT':raise ValueError('UNTRUSTED_GT_SOURCE')
        objects=[box(b['setup_name'],to_base(b['pose_world_xyz_wxyz'])[:3],[b['side_m']]*3,b['pose_world_xyz_wxyz'][3:]) for b in truth['objects']]
        # Distractors are also solid obstacles for placement (target itself excluded).
        gt=geometry(objects,[region],copy.deepcopy([b for b in objects if b['id']!='target_cube']))
    qs=questions('target_cube','s1_red_distractor') if gt else [
        {'question_id':'position','type':'position','object_id':'target_cube'}]
    if gt:qs.append({'question_id':'fits','type':'fit','object_id':'target_cube','region_id':'task_volume','quaternion_wxyz':[1,0,0,0]})
    plan=task('placement','place',constraints=constraints('placement'),instruction=
        'Place target_cube (the nearer red cube) entirely inside the task-defined volume: '
        'center [0.35,0.20,0.045] m, size [0.18,0.14,0.15] m in robot_base; keep local axes aligned with base. '
        'Avoid all other cubes with 0.002 m clearance. Geometric placement only; no support or dynamics constraint.')
    snapshot={'version':'astra.scene_snapshot.v0','scene_id':'s1_frozen_20261009',
        'provenance':'ARCHIVED_SAPIEN_RGBD_NOT_REAL_CAMERA','coordinate_system':FRAME,
        'observations':{'rgb':rgb,'depth':depth,'calibration':calib,'robot_state':robot,
        'synchronization':{'simulation_step':state['sim_step'],'capture_span_s':obs['capture_span_s'],
            'timestamp_semantics':obs['timestamp_semantics'],'same_step':True}},
        'geometry':{'reconstruction':None,'oracle':copy.deepcopy(gt)},'ground_truth':gt,
        'task':[task('understanding','understand',questions=qs,instruction=
             'Identify target_cube as the nearer red cube; s1_red_distractor is the farther red cube. '
             'Report relations along positive base axes, center position, top height, local dimensions, '
             'projected x gap and fit at the prescribed orientation. The task volume center is '
             '[0.35,0.20,0.045] m with size [0.18,0.14,0.15] m.'),plan]}
    write(output/'snapshot.json',snapshot)
    one=copy.deepcopy(snapshot);one['task']=one['task'][:1];write(output/'snapshot_understanding.json',one)
    source_files=[origin/'observation.json',cfg_path,archive/'RESULT.json']
    if truth_path.exists():source_files.append(truth_path)
    write(output/'import_manifest.json',{'source_archive':str(archive),'provenance':snapshot['provenance'],
         'transform':'base aligned with world; p_base=p_world-base_world_xyz_m, identity base rotation',
         'base_world_xyz_m':offset,'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
         'oracle_information':'Only measured object boxes and newly declared task region; no answers, trajectories, scores',
         'new_model_calls':0,'new_simulation_episodes':0})
    return output/'snapshot.json'


def png(path, width, height, pixels):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    scan=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+
                     chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b''))


def fixture_image(path, boxes, view):
    # Schematic test images only, not a physical camera or simulator rendering.
    w,h=96,72;pixels=bytearray([220]*(w*h*3))
    for i,b in enumerate(boxes):
        x=int(b['center_m'][0]*w);y=int((b['center_m'][1]+.4)*h) if view==0 else int((.4-b['center_m'][2])*h)
        for yy in range(max(0,y-5),min(h,y+6)):
            for xx in range(max(0,x-5),min(w,x+6)):
                pixels[(yy*w+xx)*3:(yy*w+xx)*3+3]=bytes([(200 if i==0 else 20),40,(40 if i==0 else 180)])
    png(path,w,h,bytes(pixels))


def fixtures(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);paths=[]
    labels=['clear','occlusion_schematic','narrow_container','rotated_object','thin_obstacle','detour']
    for i,label in enumerate(labels):
        folder=output/label;folder.mkdir()
        q=[math.cos(.35),0,0,math.sin(.35)] if i==3 else [1,0,0,0]
        objects=[box('target_cube',[.2+i*.015,-.1,.1],[.05,.04,.06],q),box('other',[.45,.0,.12],[.06]*3)]
        region=box('task_volume',[.6,.2,.12],[.16,.14,.20])
        small=box('fit_volume',[.1,.2,.1],[.03,.03,.03] if i==2 else [.10,.09,.08])
        workspace=box('workspace',[.4,0,.25],[1.,1.,.6])
        obstacle=box('obstacle',[.35,.05,.12],[.001 if i==4 else .07,.13,.19])
        gt=geometry(objects,[region,small,workspace],[obstacle],source='SYNTHETIC_FIXTURE_TRUTH');rgb=[]
        for view in (0,1):
            name='view-%d.png'%view;fixture_image(folder/name,objects+[obstacle],view)
            rgb.append({'camera_id':'view-%d'%view,'path':name,'sha256':hashlib.sha256((folder/name).read_bytes()).hexdigest()})
        kind='placement' if i%2==0 else 'path'
        qs=questions('target_cube','other')+[{'question_id':'fits','type':'fit','object_id':'target_cube',
             'region_id':'fit_volume','quaternion_wxyz':[1,0,0,0]}]
        c=constraints(kind)
        if kind=='path':c['start_position_m']=objects[0]['center_m']
        snap={'version':'astra.scene_snapshot.v0','scene_id':'fixture_'+label,'provenance':'SYNTHETIC_ANALYTICAL_TEST_NOT_SIMULATION',
            'coordinate_system':FRAME,'observations':{'rgb':rgb,'depth':[],
            'calibration':{x['camera_id']:{'intrinsic':None,'resolution':[96,72],
                'pose_base_xyz_wxyz':None,'axes':'SCHEMATIC_NO_PHYSICAL_CALIBRATION'} for x in rgb},
            'robot_state':{'joint_names':[],'qpos_rad':[],'flange_pose_base_xyz_wxyz':None},
            'synchronization':{'simulation_step':None,'capture_span_s':0.,'timestamp_semantics':'synthetic immutable fixture','same_step':True}},
            'geometry':{'reconstruction':None,'oracle':copy.deepcopy(gt)},'ground_truth':gt,
            'task':[task('understanding','understand',questions=qs),task(kind,'plan',constraints=c)]}
        write(folder/'snapshot.json',snap);paths.append(str(folder/'snapshot.json'))
    write(output/'index.json',{'provenance':'SYNTHETIC_ANALYTICAL_TEST_NOT_SIMULATION','snapshots':paths})
    return paths


class PublicDatasetAdapter:
    """Extension contract: an implementation must declare license, frame, units and GT provenance."""
    dataset_name='UNCONFIGURED'
    def convert(self, root, output):
        raise NotImplementedError(self.dataset_name+': public dataset format/license/GT not verified in V0')

class RoboSpatialHomeAdapter(PublicDatasetAdapter):dataset_name='RoboSpatial-Home'
class TraceSpatialBenchAdapter(PublicDatasetAdapter):dataset_name='TraceSpatial-Bench'
