"""Parse existing URDF/config assets only; emit two separate nominal arm models.
Never joins bases with a guessed transform. No planner, executor, SDK or simulator.
"""
import argparse,copy,hashlib,json,re,xml.etree.ElementTree as ET
from pathlib import Path
import yaml

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def record(p):
    p=Path(p);return {'path':str(p.resolve()),'bytes':p.stat().st_size,'sha256':sha(p)}

def urdf_inventory(path,vendor):
    root=ET.parse(path).getroot();joints=[];meshes=[]
    for j in root.findall('joint'):
        row={'name':j.get('name'),'type':j.get('type')}
        for tag in ['parent','child','origin','axis','limit','mimic']:
            e=j.find(tag)
            if e is not None:row[tag]=dict(e.attrib)
        joints.append(row)
    for uri in sorted({e.get('filename') for e in root.findall('.//mesh')}):
        f=vendor/uri[len('package://'):] if uri.startswith('package://') else Path(uri)
        if not f.is_absolute():f=Path(path).parent/f
        meshes.append({'uri':uri,'exists':f.is_file(),**(record(f) if f.is_file() else {'resolved_path':str(f)})})
    children={j.find('child').get('link') for j in root.findall('joint')}
    return {**record(path),'robot_name':root.get('name'),'root_links':[l.get('name') for l in root.findall('link') if l.get('name') not in children],
        'links':[l.get('name') for l in root.findall('link')],'joints':joints,'meshes':meshes}

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--vendor',type=Path,required=True);p.add_argument('--runtime-config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.resolve().relative_to(Path(__file__).resolve().parents[2]);a.output.mkdir(parents=True,exist_ok=False)
source=a.vendor/'rm_description/urdf/rm_65.urdf'
paths={'nominal_vendor_arm':source,'historical_planning_arm_and_gripper':a.runtime_config/'planning.urdf','historical_assembly_arm_and_gripper':a.runtime_config/'assembly.urdf'}
inventory={n:urdf_inventory(f,a.vendor) for n,f in paths.items()}
nominal=inventory['nominal_vendor_arm'];arm_joints=[j for j in nominal['joints'] if j['type']=='revolute']
assert [j['name'] for j in arm_joints]==[f'joint{i}' for i in range(1,7)]
assert all(m['exists'] for m in nominal['meshes'])
config=yaml.safe_load((a.runtime_config/'curobo.yml').read_text());kin=config['robot_cfg']['kinematics'];assembly=json.loads((a.runtime_config/'assembly.json').read_text())
old={'config':record(a.runtime_config/'curobo.yml'),'base_link':kin.get('base_link'),'ee_link':kin.get('ee_link'),
    'urdf_path':kin.get('urdf_path'),'configured_urdf_path_exists':Path(kin['urdf_path']).is_file(),
    'cspace':kin.get('cspace'),'lock_joints':kin.get('lock_joints'),
    'collision_sphere_count':sum(len(v) for v in kin.get('collision_spheres',{}).values()),
    'collision_spheres_per_link':{k:len(v) for k,v in kin.get('collision_spheres',{}).items()},
    'historical_controller_planner_note':assembly.get('control',{}).get('planner_note'),
    'temporary_simulation_assembly':assembly.get('temporary_assembly'),
    'temporary_values_not_adopted_as_real_transforms':True}
model_paths={};groups={}
for arm in ['left','right']:
    root=ET.parse(source).getroot();root.set('name',arm+'_rm65_nominal_arm_candidate')
    links={e.get('name'):arm+'_'+e.get('name') for e in root.findall('link')}
    for e in root.findall('link'):e.set('name',links[e.get('name')])
    for e in root.findall('joint'):
        name=e.get('name');i=int(name.removeprefix('joint'));e.set('name',f'{arm}_joint_{i}')
        for tag in ['parent','child']:
            node=e.find(tag);node.set('link',links[node.get('link')])
    for e in root.findall('.//mesh'):
        uri=e.get('filename');e.set('filename',str((a.vendor/uri.removeprefix('package://')).resolve()))
    target=a.output/f'{arm}_rm65_nominal.urdf';ET.indent(root);ET.ElementTree(root).write(target,encoding='utf-8',xml_declaration=True)
    built=urdf_inventory(target,a.vendor)
    assert built['root_links']==[arm+'_base_link'] and len(built['joints'])==6 and all(m['exists'] for m in built['meshes'])
    # Model-local FK geometry/limits stay exact; namespace/path edits only.
    for before,after in zip(arm_joints,built['joints']):
        for key in ['origin','axis','limit']:assert before.get(key)==after.get(key)
    model_paths[arm]=record(target);groups[arm]=[f'{arm}_joint_{i}' for i in range(1,7)]
result={'status':'TWO_SEPARATE_NOMINAL_ARMS_PREPARED_NOT_REGISTERED','inventory':inventory,'historical_curobo':old,
 'candidate_models':model_paths,'proposed_joint_names':groups,'proposed_order_12':groups['left']+groups['right'],
 'model_local_flange_links':{'left':'left_Link6','right':'right_Link6'},
 'physical_sdk_joint_order_sign_offsets_verified':False,'physical_model_variant_and_fk_verified':False,
 'common_world':None,'base_transforms':{'left':None,'right':None},'actual_tcp':{'left':None,'right':None},
 'gripper_and_wrist_collision_geometry_verified':False,'ready_for_native_planning_context':False,
 'curobo_registered':False,'planner_started':False,'hardware_commands_sent':0,
 'nominal_urdf_units':'joint angles radians; translations metres; limits from archived URDF, not current controller readback',
 'candidate_scope':'No gripper/TCP/camera/world link; independent arm base roots. Physical dual assembly intentionally not constructed.'}
(a.output/'rm65_inventory.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:result[k] for k in ['status','proposed_joint_names','base_transforms','actual_tcp']},indent=2))
