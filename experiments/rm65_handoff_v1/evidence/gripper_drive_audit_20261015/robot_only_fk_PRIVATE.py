"""Robot-geometry decomposition only. No PhysX state writes, IK, or rollout."""
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import mplib

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from decision4_trace import read_rows
assets=Path(os.environ['RM65_ASSETS'])
rows=read_rows(ROOT/'evidence/decision4_diagnosis_20261015/A_physical_01')
before=rows[3466];after=rows[-1];names=before['arms']['left']['joint_names']
tree=ET.parse(ROOT/'runtime_config/assembly.urdf').getroot()
mimics={j.get('name'):(j.find('mimic').get('joint'),float(j.find('mimic').get('multiplier')),float(j.find('mimic').get('offset','0'))) for j in tree.findall('joint') if j.find('mimic') is not None}
# Direct mplib's file loader prefixes its mesh directory. Use a FK-only copy
# with relative filenames; do not touch the runtime or frozen physical URDF.
view=Path(__file__).with_name('fk_path_view');view.mkdir(exist_ok=False)
planning=ET.parse(ROOT/'runtime_config/planning.urdf')
for mesh in planning.getroot().iter('mesh'):
    mesh.set('filename',os.path.relpath(mesh.get('filename'),view))
planning.write(view/'planning.urdf')
model=mplib.Planner(urdf=str(view/'planning.urdf'),srdf=str(ROOT/'runtime_config/assembly.srdf'),move_group='Link6',user_joint_names=names)
vertices={}
for side in ('Left','Right'):
    mesh=trimesh.load(assets/f'vendor/target_models_20260921/crt_ctag2f90d_gripper_visualization/meshes/{side}_Support_Link.STL')
    v=mesh.vertices[mesh.vertices[:,1]>.04];vertices['ctag_'+side+'_Support_Link']=v[v[:,0]<v[:,0].min()+.001]
def ideal(q):
    q=q.copy();done=set()
    def fill(n):
        if n in mimics and n not in done:
            p,m,b=mimics[n];fill(p);q[names.index(n)]=m*q[names.index(p)]+b;done.add(n)
    for n in mimics:fill(n)
    return q
def gap(q):
    model.pinocchio_model.compute_forward_kinematics(q);points=[]
    for name,v in vertices.items():
        t=model.pinocchio_model.get_link_pose(model.link_name_2_idx[name]).to_transformation_matrix()
        points.append((v@t[:3,:3].T+t[:3,3]).mean(0))
    return float(np.linalg.norm(points[0]-points[1]))
out={}
for label,r in [('before_D4',before),('guard_step',after)]:
    q=np.array(r['arms']['left']['qpos']);measured=r['arms']['left']['actual_pad_gap_m']
    out[label]={'measured_gap_m':measured,'FK_actual_q_gap_m':gap(q),'FK_ideal_mimic_same_master_gap_m':gap(ideal(q)),
                'FK_vs_physical_gap_error_m':gap(q)-measured,'master_q_rad':q[names.index('ctag_Left_1_Joint')]}
b,a=out['before_D4'],out['guard_step']
out['additive_geometric_decomposition_mm']={
 'measured_gap_change':1000*(a['measured_gap_m']-b['measured_gap_m']),
 'ideal_single_DOF_master_closure_component':1000*(a['FK_ideal_mimic_same_master_gap_m']-b['FK_ideal_mimic_same_master_gap_m']),
 'mimic_deviation_component':1000*((a['FK_actual_q_gap_m']-a['FK_ideal_mimic_same_master_gap_m'])-(b['FK_actual_q_gap_m']-b['FK_ideal_mimic_same_master_gap_m'])),
 'FK_physical_residual_component':1000*((a['measured_gap_m']-a['FK_actual_q_gap_m'])-(b['measured_gap_m']-b['FK_actual_q_gap_m']))}
out['interpretation']='Kinematic decomposition, not force/cause identification. Actual q is never imposed on a PhysX body. No idealized state is executed.'
Path(__file__).with_name('robot_only_fk_decomposition.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
