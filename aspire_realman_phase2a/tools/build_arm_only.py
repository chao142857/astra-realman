"""Explicit ARM_ONLY_DIAGNOSTIC: original body geometry, no attachments/TCP."""
import argparse, copy, json, sys, tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'aspire_realman_phase2a/src'),str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src')]
import yaml
from aspire_realman_phase2a.model import build_model, sha, synthetic_layout

BODY=['base_link']+[f'Link{i}' for i in range(1,7)]

def build(vendor, assembly, config, output, coincident=False):
    source=vendor/'rm_description/urdf/rm_65.urdf'
    raw=ET.parse(source).getroot();full=ET.parse(assembly).getroot()
    # Require direct agreement with the existing body; no geometry adjustment.
    for j in raw.findall('joint'):
        other=full.find(f"joint[@name='{j.get('name')}']")
        for tag in ('origin','parent','child','axis','limit'):
            assert j.find(tag).attrib==other.find(tag).attrib,(j.get('name'),tag)
    for mesh in raw.findall('.//mesh'):
        mesh.set('filename',str(vendor/mesh.get('filename').removeprefix('package://')))
    for name in BODY:
        a=raw.find(f"link[@name='{name}']/collision")
        b=full.find(f"link[@name='{name}']/collision")
        assert a.find('origin').attrib==b.find('origin').attrib,name
        assert sha(a.find('.//mesh').get('filename'))==sha(b.find('.//mesh').get('filename')),name
    c=yaml.safe_load(config.read_text());k=c['robot_cfg']['kinematics']
    original=copy.deepcopy(k)
    k['collision_spheres']={n:copy.deepcopy(k['collision_spheres'][n]) for n in BODY}
    k['self_collision_ignore']={n:[v for v in vs if v in BODY] for n,vs in k.get('self_collision_ignore',{}).items() if n in BODY}
    k['self_collision_buffer']={n:v for n,v in k.get('self_collision_buffer',{}).items() if n in BODY}
    k['lock_joints']={}
    layout=synthetic_layout()
    if coincident:
        layout['base_transforms']['right']=copy.deepcopy(layout['base_transforms']['left'])
        layout['purpose']='ARM_ONLY_DIAGNOSTIC COINCIDENT CROSS_ARM_NEGATIVE ONLY'
    # Temporary input derivatives are inside the isolated task, never source assets.
    with tempfile.TemporaryDirectory(prefix='arm-only-input-',dir=output.parent) as tmp:
        u=Path(tmp)/'body.urdf';y=Path(tmp)/'body.yml'
        ET.ElementTree(raw).write(u,encoding='utf-8',xml_declaration=True)
        y.write_text(yaml.safe_dump(c,sort_keys=False))
        m=build_model(u,y,output,layout=layout)
    m['diagnostic_scope']='ARM_ONLY_DIAGNOSTIC'
    m['source_sha256']={str(p):sha(p) for p in (source,assembly,config)}
    m['omitted_attachments']=[n for n in original['collision_spheres'] if n not in BODY]
    m['gripper_geometry']='ABSENT_ARM_ONLY_DIAGNOSTIC_NOT_FULL_BASELINE'
    m['temporary_mounts']='ABSENT_NO_PHYSICAL_ASSEMBLY_CLAIM'
    m['collision_policy']='Original RM65 body spheres/radii/buffers/within-body ignores unchanged; ALL cross-arm body pairs checked; attachments absent by explicit diagnostic scope'
    m['body_source_agreement']={'joint_origin_axis_limits':True,'mesh_sha256_and_collision_origins':True}
    assert m['active_sphere_count_dual']==2*sum(len(original['collision_spheres'][n]) for n in BODY)
    (output/'model.json').write_text(json.dumps(m,indent=2))
    return m

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--vendor',type=Path,required=True);p.add_argument('--assembly',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--coincident',action='store_true');a=p.parse_args()
    a.output.resolve().relative_to(ROOT);a.output.parent.mkdir(parents=True,exist_ok=True)
    m=build(a.vendor,a.assembly,a.config,a.output,a.coincident)
    print(json.dumps({k:m[k] for k in ('diagnostic_scope','active_sphere_count_dual','body_source_agreement')}))
