"""Build nominal RM65 dual kinematics; SYNTHETIC bases only, never calibration.

Original vendor mesh paths and historical gripper assembly remain read-only.
Sphere compression encloses every original sphere, never drops collision cover.
"""
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import yaml
from aspire_realman.codec import rigid,rpy_matrix

MODEL='realman_rm65_dual'
ARMS=('left','right')
NAMES={a:tuple(f'{a}_joint_{i}' for i in range(1,7)) for a in ARMS}
ROOT_LINK='SYNTHETIC_rm65_world'
FRAME='synthetic:realman_rm65_world'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def synthetic_layout():
    left=np.eye(4);right=np.eye(4)
    left[0,3]=-.65;right[0,3]=.65
    right[:3,:3]=rpy_matrix([0,0,np.pi])
    return {'status':'SYNTHETIC_OFFLINE_NOT_REAL_CALIBRATION','frame':FRAME,
        'base_transforms':{'left':left.tolist(),'right':right.tolist()},
        'purpose':'software planning validation only; never deploy as measured layout'}


def compress_spheres(spheres,group_size):
    if type(group_size) is not int or group_size<1:raise ValueError('POSITIVE_GROUP_SIZE')
    # Deterministic local groups, conservative minimal-at-centroid enclosure.
    result={};proof={}
    for link,items in spheres.items():
        source=sorted(items,key=lambda s:tuple(s['center']))
        merged=[];checks=[]
        for start in range(0,len(source),group_size):
            group=source[start:start+group_size]
            centers=np.array([s['center'] for s in group]);radii=np.array([s['radius'] for s in group])
            if len(group)==1:center=centers[0];radius=float(radii[0])
            else:
                center=centers.mean(0);radius=float(np.max(np.linalg.norm(centers-center,axis=1)+radii))+1e-7
            assert np.all(np.linalg.norm(centers-center,axis=1)+radii <= radius+1e-10)
            merged.append({'center':center.tolist(),'radius':radius})
            checks.append({'source_count':len(group),'maximum_covered_extent_m':float(np.max(np.linalg.norm(centers-center,axis=1)+radii)),'radius_m':radius})
        result[link]=merged;proof[link]=checks
    return result,proof


def build_model(source_urdf,source_config,output,*,layout=None,sphere_group_size=1,synthetic_finger_midpoints=False):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    layout=synthetic_layout() if layout is None else copy.deepcopy(layout)
    if layout.get('status')!='SYNTHETIC_OFFLINE_NOT_REAL_CALIBRATION' or layout.get('frame')!=FRAME:
        raise ValueError('EXPLICIT_SYNTHETIC_LAYOUT_REQUIRED_NO_PHYSICAL_FALLBACK')
    bases={a:rigid(layout['base_transforms'][a]) for a in ARMS}
    urdf=ET.parse(source_urdf).getroot()
    old=yaml.safe_load(Path(source_config).read_text())['robot_cfg']['kinematics']
    nominal_locks=copy.deepcopy(old.get('lock_joints',{}))
    if synthetic_finger_midpoints:
        # Explicit configuration test within the source URDF joint ranges.
        # Does not modify geometry, fixed mounts, spheres or collision pairs.
        joints={j.get('name'):j for j in urdf.findall('joint')}
        for name in nominal_locks:
            joint=joints[name];lim=joint.find('limit')
            if joint.get('type')!='revolute' or lim is None:raise ValueError('BOUNDED_REVOLUTE_FINGER_REQUIRED')
            lower,upper=float(lim.get('lower')),float(lim.get('upper'))
            if not np.isfinite([lower,upper]).all() or lower>upper:raise ValueError('FINITE_SOURCE_FINGER_LIMITS_REQUIRED')
            nominal_locks[name]=(lower+upper)/2
    armjoints=[j for j in urdf.findall('joint') if j.get('name') in [f'joint{i}' for i in range(1,7)]]
    if [j.get('name') for j in armjoints]!=[f'joint{i}' for i in range(1,7)]:raise ValueError('SOURCE_JOINT_ORDER')
    limits={j.get('name'):{k:float(v) for k,v in j.find('limit').attrib.items()} for j in armjoints}
    meshes={m.get('filename'):sha(m.get('filename')) for m in urdf.findall('.//mesh')}
    before={str(Path(source_urdf).resolve()):sha(source_urdf),str(Path(source_config).resolve()):sha(source_config)}
    original_spheres=old['collision_spheres'];spheres,proof=compress_spheres(original_spheres,sphere_group_size)
    robot=ET.Element('robot',name=MODEL+'_SYNTHETIC_NOT_REAL_CALIBRATION')
    ET.SubElement(robot,'link',name=ROOT_LINK)
    all_spheres={};ignore={};lock={}
    for arm in ARMS:
        prefix=arm+'_'
        for node in urdf:
            item=copy.deepcopy(node)
            for element in item.iter():
                if element.tag in ('link','joint') and 'name' in element.attrib:
                    name=element.get('name');element.set('name',f'{arm}_joint_{name[5:]}' if element.tag=='joint' and name in limits else prefix+name)
                if element.tag in ('parent','child') and 'link' in element.attrib:element.set('link',prefix+element.get('link'))
                if element.tag=='mimic':element.set('joint',prefix+element.get('joint'))
            robot.append(item)
        t=bases[arm];yaw=float(np.arctan2(t[1,0],t[0,0]));pitch=float(np.arctan2(-t[2,0],np.hypot(t[0,0],t[1,0])));roll=float(np.arctan2(t[2,1],t[2,2]))
        fixed=ET.SubElement(robot,'joint',name=arm+'_SYNTHETIC_base',type='fixed')
        ET.SubElement(fixed,'parent',link=ROOT_LINK);ET.SubElement(fixed,'child',link=prefix+'base_link')
        ET.SubElement(fixed,'origin',xyz=' '.join(map(str,t[:3,3])),rpy=f'{roll} {pitch} {yaw}')
        all_spheres.update({prefix+link:copy.deepcopy(items) for link,items in spheres.items()})
        ignore.update({prefix+k:[prefix+x for x in values] for k,values in old.get('self_collision_ignore',{}).items()})
        lock.update({prefix+k:v for k,v in nominal_locks.items()})
    path=output/'rm65_dual_SYNTHETIC.urdf';ET.indent(robot);ET.ElementTree(robot).write(path,encoding='utf-8',xml_declaration=True)
    kin={'format_version':2.0,'urdf_path':str(path),'base_link':ROOT_LINK,
        'tool_frames':[a+'_Link6' for a in ARMS], 'collision_link_names':list(all_spheres),
        'mesh_link_names':list(all_spheres),'collision_spheres':all_spheres,
        'collision_sphere_buffer':float(old.get('collision_sphere_buffer',0)),
        'self_collision_ignore':ignore,'self_collision_buffer':{a+'_'+k:float(old.get('self_collision_buffer',{}).get(k,0.)) for a in ARMS for k in spheres},
        'lock_joints':lock,
        'cspace':{'joint_names':list(NAMES['left']+NAMES['right']),
          'default_joint_position':list(old['cspace']['retract_config'])*2,
          'null_space_weight':[1.]*12,'cspace_distance_weight':[1.]*12,
          'max_acceleration':old['cspace']['max_acceleration'],'max_jerk':old['cspace']['max_jerk']}}
    cfg=output/'rm65_dual.yml';cfg.write_text(yaml.safe_dump({'robot_cfg':{'kinematics':kin}},sort_keys=False))
    manifest={'model':MODEL,'scope':'SYNTHETIC_OFFLINE_ONLY','frame':FRAME,'layout':layout,
        'urdf':{'path':str(path),'sha256':sha(path)},'config':{'path':str(cfg),'sha256':sha(cfg)},
        'source_sha256':before,'source_mesh_sha256':meshes,'joint_names':NAMES,
        'joint_limits':{a:[limits[f'joint{i}'] for i in range(1,7)] for a in ARMS},
        'end_effector_links':{a:a+'_Link6' for a in ARMS},
        'default_positions':{a:list(old['cspace']['retract_config']) for a in ARMS},
        'original_sphere_count_per_arm':sum(map(len,original_spheres.values())),
        'active_sphere_count_dual':sum(map(len,all_spheres.values())),
        'sphere_group_size':sphere_group_size,'conservative_sphere_enclosure_proof':proof,
        'finger_configuration':{'kind':'SYNTHETIC_SOURCE_URDF_LIMIT_MIDPOINTS' if synthetic_finger_midpoints else 'HISTORICAL_LOCKED_VALUES',
            'values_rad':nominal_locks,'original_values_rad':old.get('lock_joints',{}),'physical_opening_mapping_verified':False},
        'collision_policy':'original historical per-arm ignore pairs preserved; NO additional ignore pairs; NO cross-arm ignores; no collision disabling',
        'gripper_geometry':'historical CTAG assembly locked at declared nominal finger values, not current gripper feedback',
        'temporary_mounts':'historical adapter/camera values retained ONLY as SYNTHETIC nominal geometry',
        'actual_grasp_tcp':None,'physical_model_geometry_verified':False,'physical_calibration':None}
    assert all(sha(p)==h for p,h in before.items())
    (output/'model.json').write_text(json.dumps(manifest,indent=2))
    return manifest


def load_manifest(path):
    m=json.loads(Path(path).read_text())
    if m['model']!=MODEL or m['scope']!='SYNTHETIC_OFFLINE_ONLY':raise ValueError('SYNTHETIC_MODEL_REQUIRED')
    if m['frame']!=FRAME or m['layout']['status']!='SYNTHETIC_OFFLINE_NOT_REAL_CALIBRATION' or m['actual_grasp_tcp'] is not None:
        raise ValueError('EXPLICIT_SYNTHETIC_LAYOUT_AND_UNCERTIFIED_TCP_REQUIRED')
    for key in ('urdf','config'):
        if sha(m[key]['path'])!=m[key]['sha256']:raise ValueError('MODEL_ARTIFACT_HASH_MISMATCH')
    return m
