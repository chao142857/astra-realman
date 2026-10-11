"""Offline robot-only calibration. No SAPIEN, object state or model request."""
import argparse,hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
import trimesh

def build(assets):
    assets=Path(assets);path=assets/'configs/rm65_ctag_reference/assembly.urdf';tree=ET.parse(path).getroot()
    manifest=json.loads((assets/'asset_manifest.json').read_text())['files'];sources={}
    def record(p):
        rel=str(p.resolve().relative_to(assets.resolve()));h=hashlib.sha256(p.read_bytes()).hexdigest()
        if manifest[rel]['sha256']!=h:raise ValueError('ROBOT_ASSET_HASH:'+rel)
        sources[rel]=h
    record(path)
    def vec(s):return np.array([float(v) for v in s.split()])
    links={'Link6'};joints=[];pending=list(tree.findall('joint'))
    while True:
        selected=[j for j in pending if j.find('parent').get('link') in links]
        if not selected:break
        for j in selected:
            child=j.find('child').get('link');links.add(child);pending.remove(j)
            o=j.find('origin');t=np.eye(4);t[:3,3]=vec(o.get('xyz','0 0 0'));t[:3,:3]=Rotation.from_euler('xyz',vec(o.get('rpy','0 0 0'))).as_matrix()
            m=j.find('mimic');a=j.find('axis')
            joints.append({'name':j.get('name'),'type':j.get('type'),'parent':j.find('parent').get('link'),'child':child,
              'origin':t.tolist(),'axis':vec(a.get('xyz')).tolist() if a is not None else [0,0,0],
              'mimic':None if m is None else {'joint':m.get('joint'),'multiplier':float(m.get('multiplier','1')),'offset':float(m.get('offset','0'))}})
    supports=[]
    for side in ('Left','Right'):
        name='ctag_'+side+'_Support_Link';collision=tree.find(f"link[@name='{name}']/collision")
        mesh=collision.find('geometry/mesh');p=(path.parent/mesh.get('filename')).resolve();record(p)
        assert mesh.get('scale') is None and collision.find('origin').get('xyz')=='0 0 0' and collision.find('origin').get('rpy')=='0 0 0'
        m=trimesh.load(p);v=m.vertices[m.vertices[:,1]>.04];v=v[v[:,0]<v[:,0].min()+.001]
        supports.append({'link':name,'pad_vertices':v.tolist(),'collision_hull_vertices':m.convex_hull.vertices.tolist(),
            'pad_definition':'existing scene subset local y>0.04m and x<selected_min_x+0.001m; collision is entire support hull, not this pad subset'})
    return {'version':'ctag.robot_only_contact_calibration.v1','master_joint':'ctag_Left_1_Joint','source_hashes':sources,'joints':joints,'supports':supports,
      'nominal_master_samples_rad':[0,-.15,-.3,-.45,-.6,-.75,-.91],
      'constraints':[
       'move_pose XYZ is pad center at the measured current gripper configuration; orientation is Link6 wxyz. It is not a gripper-configuration-invariant TCP.',
       'gripper(opening) commands master=-0.91*(1-opening), holds arm joint targets, and does NOT compensate pad-center motion. Opening and closing move the pad center.',
       'Samples are nominal ideal-mimic kinematics at the current flange orientation, with flange held fixed. They are predictions, not achieved states, safe clearances or contact outcomes. Rotate the offsets if proposing a different flange orientation.',
       'Contact may latch before the commanded master endpoint. Actual mimic error, arm deflection, preload and contact dynamics can change the path. There is no fixed 13.4mm correction and no task-specific recommended height or opening.',
       'Use current public RGB-D observed target bounds and uncertainty to reason about opposed side contact over closure, and clearance of the entire Support_Link from the public table plane. Hidden object shape/free space remains unknown. Bounds and sampled shapes do not certify continuous collision clearance.',
       'The full Support_Link convex hull is collidable; proximal support edges can contact, not only the distal inner pad face. These two hulls are not a full-arm collision model.',
       'Original contact penetration limit remains 0.002m. Do not use tolerance as an intended penetration. Original IK, path collision, joint limits, STOP and contact guards remain authoritative.',
       'Finite contact latch is not stable holding. After closing, observe and verify contact/visual evidence; trial lift and transport require subsequent measured evidence. No plan following a close may assume it already succeeded.'
      ]}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    with a.out.open('x') as f:json.dump(build(a.assets),f,indent=2,allow_nan=False);f.write('\n')
    print(hashlib.sha256(a.out.read_bytes()).hexdigest())
