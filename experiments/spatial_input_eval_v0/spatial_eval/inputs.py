"""Allowlisted model boundary: scores and ground_truth never reach a request."""
import copy
import hashlib
from pathlib import Path
from .schema import CONDITIONS, KINDS, fields, number, vector, quaternion, output_schema, read
from .geometry import validate_geometry

FRAME = {'id':'robot_base','units':'m','axes':'+x forward, +y left, +z up; right-handed',
         'pose':'object center xyz in meters; unit quaternion wxyz, object local axes in robot_base'}
PROMPT = ('Return exactly one JSON object matching output_schema. This is offline geometry evaluation. '
          'Use only observations, optional geometry and task. No tools or execution. '
          'All positions are object centers in robot_base, meters; orientations are unit quaternions wxyz. '
          'For understanding return each question_id once, populating only the relevant answer field: '
          'relation=less/equal/greater along the specified positive axis, scalar_m=height/gap, '
          'vector_m=position/size, fits=fit; all other fields null. '
          'For placement waypoints_m must be empty. For path, waypoints_m excludes start, includes the final '
          'position_m, and orientation is fixed throughout translation. Choose any constraint-valid solution.')

def validate_task(t):
    fields(t,['task_id','kind','instruction','frame','questions','constraints','tolerance_m'])
    if t['kind'] not in KINDS or t['frame'] != 'robot_base' or not isinstance(t['instruction'],str): raise ValueError('TASK')
    if not isinstance(t['task_id'],str) or not t['task_id']: raise ValueError('TASK_ID')
    if not number(t['tolerance_m']) or not 0<=t['tolerance_m']<=.02: raise ValueError('TASK_TOLERANCE')
    if t['kind']=='understanding':
        if t['constraints']!={} or not isinstance(t['questions'],list) or not t['questions']: raise ValueError('QUESTIONS_REQUIRED')
        ids=set()
        for q in t['questions']:
            kinds={'relation':('object_id','other_id','axis'), 'position':('object_id',),
                   'height':('object_id','reference'), 'size':('object_id',),
                   'gap':('object_id','other_id','axis'), 'fit':('object_id','region_id','quaternion_wxyz')}
            if q.get('type') not in kinds: raise ValueError('QUESTION_TYPE')
            fields(q, ['question_id','type',*kinds[q['type']]])
            if not isinstance(q['question_id'],str) or q['question_id'] in ids: raise ValueError('QUESTION_ID')
            ids.add(q['question_id'])
            if 'axis' in q and q['axis'] not in ('x','y','z'): raise ValueError('AXIS')
            if q['type']=='height' and q['reference'] not in ('center','top','bottom'): raise ValueError('HEIGHT_REFERENCE')
            if q['type']=='fit':quaternion(q['quaternion_wxyz'])
    else:
        if t['questions']!=[]:raise ValueError('PLAN_QUESTIONS_EMPTY')
        c=t['constraints']; req=['object_id','allowed_region_id','clearance_m','required_quaternion_wxyz','orientation_tolerance_rad']
        if t['kind']=='path':req+=['start_position_m','workspace_region_id']
        fields(c,req)
        for key in ('clearance_m','orientation_tolerance_rad'):
            if not number(c[key]) or c[key]<0:raise ValueError('CONSTRAINT_NUMBER')
        if c['required_quaternion_wxyz'] is not None:quaternion(c['required_quaternion_wxyz'])
        if t['kind']=='path':vector(c['start_position_m'],3)
    return t

def validate_observations(obs):
    fields(obs,['rgb','depth','calibration','robot_state','synchronization'])
    if not isinstance(obs['calibration'],dict):raise ValueError('CALIBRATION_OBJECT')
    for c in obs['calibration'].values():
        fields(c,['intrinsic','resolution','pose_base_xyz_wxyz','axes'])
        vector(c['resolution'],2)
        if c['intrinsic'] is not None:
            if not isinstance(c['intrinsic'],list) or len(c['intrinsic'])!=3:raise ValueError('INTRINSIC_MATRIX')
            for r in c['intrinsic']:vector(r,3)
        if c['pose_base_xyz_wxyz'] is not None:
            vector(c['pose_base_xyz_wxyz'],7);quaternion(c['pose_base_xyz_wxyz'][3:])
        if not isinstance(c['axes'],str):raise ValueError('CAMERA_AXES')
    robot=obs['robot_state'];fields(robot,['joint_names','qpos_rad','flange_pose_base_xyz_wxyz'])
    if not isinstance(robot['joint_names'],list) or not all(isinstance(n,str) for n in robot['joint_names']):raise ValueError('JOINT_NAMES')
    vector(robot['qpos_rad'],len(robot['joint_names']))
    if robot['flange_pose_base_xyz_wxyz'] is not None:
        vector(robot['flange_pose_base_xyz_wxyz'],7);quaternion(robot['flange_pose_base_xyz_wxyz'][3:])
    sync=obs['synchronization'];fields(sync,['simulation_step','capture_span_s','timestamp_semantics','same_step'])
    if not number(sync['capture_span_s']) or sync['capture_span_s']<0:raise ValueError('CAPTURE_SPAN')
    if sync['same_step'] is not True:raise ValueError('SYNCHRONIZATION_REQUIRED')
    if sync['simulation_step'] is not None and type(sync['simulation_step']) is not int:raise ValueError('SIMULATION_STEP')
    if not isinstance(sync['timestamp_semantics'],str):raise ValueError('TIMESTAMP_SEMANTICS')


def validate_references(task, truth):
    objects={b['id'] for b in truth['objects']};regions={b['id'] for b in truth['regions']}
    if task['kind']=='understanding':
        for q in task['questions']:
            if q['object_id'] not in objects or ('other_id' in q and q['other_id'] not in objects):raise ValueError('GT_OBJECT_REFERENCE')
            if 'region_id' in q and q['region_id'] not in regions:raise ValueError('GT_REGION_REFERENCE')
    else:
        c=task['constraints']
        if c['object_id'] not in objects:raise ValueError('GT_OBJECT_REFERENCE')
        if c['allowed_region_id'] not in regions or (task['kind']=='path' and c['workspace_region_id'] not in regions):raise ValueError('GT_REGION_REFERENCE')


def load_snapshot(path):
    s=read(path)
    fields(s,['version','scene_id','provenance','coordinate_system','observations','geometry','ground_truth','task'])
    if s['version']!='astra.scene_snapshot.v0' or s['coordinate_system']!=FRAME:raise ValueError('SNAPSHOT_VERSION_FRAME')
    validate_observations(s['observations'])
    if not 2<=len(s['observations']['rgb'])<=8: raise ValueError('RGB_COUNT')
    cameras=set()
    for item in s['observations']['rgb']:
        fields(item,['camera_id','path','sha256'])
        if item['camera_id'] in cameras or item['camera_id'] not in s['observations']['calibration']:raise ValueError('CAMERA_ID')
        cameras.add(item['camera_id'])
        p=(Path(path).parent/item['path']).resolve()
        data=p.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>8*1024*1024:raise ValueError('INVALID_IMAGE')
        if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('IMAGE_HASH_MISMATCH')
        item['path']=str(p)
    fields(s['geometry'],['reconstruction','oracle'])
    for name,g in s['geometry'].items():
        if g is not None:
            validate_geometry(g)
            if g['frame']!='robot_base':raise ValueError('GEOMETRY_FRAME')
            if name=='reconstruction' and g['source']!='RECONSTRUCTION':raise ValueError('B_SOURCE')
            if name=='oracle' and g['source'] not in ('SIMULATOR_TRUTH','INDEPENDENT_MEASUREMENT','SYNTHETIC_FIXTURE_TRUTH'):raise ValueError('C_SOURCE')
            if g['source']=='SYNTHETIC_FIXTURE_TRUTH' and s['provenance']!='SYNTHETIC_ANALYTICAL_TEST_NOT_SIMULATION':raise ValueError('FIXTURE_PROVENANCE')
    if s['ground_truth'] is not None:
        validate_geometry(s['ground_truth'])
        if s['ground_truth']['frame']!='robot_base':raise ValueError('GT_FRAME')
        solids={b['id']:b for b in s['ground_truth']['objects']}
        for b in s['ground_truth']['obstacles']:
            if b['id'] in solids and b!=solids[b['id']]:raise ValueError('CONFLICTING_GT_SOLID')
    if not isinstance(s['task'],list) or not s['task']:raise ValueError('TASK_LIST')
    ids=set()
    for task in s['task']:
        validate_task(task)
        if task['task_id'] in ids:raise ValueError('DUPLICATE_TASK_ID')
        ids.add(task['task_id'])
        if s['ground_truth'] is not None:validate_references(task,s['ground_truth'])
    return s

def build_input(snapshot, task, condition):
    if condition not in CONDITIONS:raise ValueError('CONDITION')
    validate_task(task)
    obs=snapshot['observations'];validate_observations(obs)
    geometry=None
    if condition!=CONDITIONS[0]:
        key='reconstruction' if condition==CONDITIONS[1] else 'oracle'
        geometry=snapshot['geometry'][key]
        if geometry is None:raise ValueError('GEOMETRY_UNAVAILABLE:'+condition)
        validate_geometry(geometry)
    # Explicit selection; never serialize snapshot, provenance, private truth, or depth pixels.
    attachments=[{'camera_id':x['camera_id'],'file':'image-%d.png'%i,'sha256':x['sha256']} for i,x in enumerate(obs['rgb'])]
    context={'instruction':PROMPT, 'coordinate_system':copy.deepcopy(FRAME), 'task':copy.deepcopy(task),
             'output_schema':output_schema(task['kind']), 'attachments':attachments,
             'observations':{k:copy.deepcopy(obs[k]) for k in ('calibration','robot_state','synchronization')},
             'geometry':copy.deepcopy(geometry)}
    manifest={'condition':condition,'image_count':len(attachments),'geometry_source':geometry['source'] if geometry else None,
              'extra_information':[] if geometry is None else ['objects: ids, centers, sizes, orientations',
              'regions: interior centers, sizes, orientations','obstacles: centers, sizes, orientations'],
              'depth_sent':False,'geometry_representation':'structured_text' if geometry else None,
              'task_prompt_sha256':hashlib.sha256((PROMPT+__import__('json').dumps(task,sort_keys=True)).encode()).hexdigest()}
    return context,manifest,[Path(x['path']) for x in obs['rgb']]
