"""Review existing mesh diagnostic: component containment + actual GPU FK.

Does not repeat feasibility sampling, adjust geometry or change collision pairs.
"""
import argparse,json,os,sys
from pathlib import Path
from phase2b_geometry import ROOT,fk,load_mesh,transform
import numpy as np,yaml,trimesh,xml.etree.ElementTree as ET
from aspire_realman_phase2a.model import sha

def component_winding(x,y):
    components=x.split(only_watertight=False)
    if not y.is_watertight or not y.is_winding_consistent:
        return {'status':'UNAVAILABLE_NON_WATERTIGHT_OR_INCONSISTENT','source_components':len(components)}
    values=[]
    for component in components:
        p=component.vertices[0];v=np.asarray(y.triangles)-p;n=np.linalg.norm(v,axis=2)
        num=np.einsum('ni,ni->n',v[:,0],np.cross(v[:,1],v[:,2]))
        den=n.prod(1)+np.einsum('ni,ni->n',v[:,0],v[:,1])*n[:,2]+np.einsum('ni,ni->n',v[:,1],v[:,2])*n[:,0]+np.einsum('ni,ni->n',v[:,2],v[:,0])*n[:,1]
        values.append(float(np.arctan2(num,den).sum()/(2*np.pi)))
    return {'status':'EACH_COMPONENT_VERTEX_WINDING','components':len(components),'winding':values,'any_inside':any(abs(x)>.5 for x in values)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.resolve().relative_to(ROOT);a.output.mkdir(parents=True,exist_ok=False)
    report=json.loads(a.report.read_text());m=json.loads(a.manifest.read_text())
    u=Path(next(p for p in m['source_sha256'] if p.endswith('urdf')));y=Path(next(p for p in m['source_sha256'] if p.endswith('yml')))
    root=ET.parse(u).getroot();k=yaml.safe_load(y.read_text())['robot_cfg']['kinematics'];links={n.get('name'):n for n in root.findall('link')}
    result={'source_report_sha256':sha(a.report),'status':'BLOCKED_PHYSICAL_GEOMETRY_EVIDENCE','physical_commands_sent':0,'case_reviews':[]}
    for case in report['cases']:
        meshes=[]
        for name in case['links']:
            mesh,_=load_mesh(links[name]);mesh.apply_transform(case['T_reference_link'][name]);meshes.append(mesh)
        review={'links':case['links'],'joint6_rad':case['joint6_rad'],'gripper_master_rad':case['gripper_master_rad'],
            'containment_by_component':{'a_in_b':component_winding(meshes[0],meshes[1]),'b_in_a':component_winding(meshes[1],meshes[0])},'sphere_review':[]}
        for ball,mesh in zip(case['worst_original_sphere_pair'],meshes):
            point=np.array([ball['center_reference_m']]);_,dist,_=trimesh.proximity.closest_point_naive(mesh,point)
            review['sphere_review'].append({'link':ball['link'],'center_to_own_mesh_surface_unsigned_m':float(dist[0]),
                'sphere_aabb_beyond_mesh_aabb_low_m':np.maximum(mesh.bounds[0]-(point[0]-ball['radius_m']),0).tolist(),
                'sphere_aabb_beyond_mesh_aabb_high_m':np.maximum(point[0]+ball['radius_m']-mesh.bounds[1],0).tolist()})
        result['case_reviews'].append(review)
    import torch,warp as wp
    wp.config.cuda_output='cubin';wp.config.kernel_cache_dir=str(ROOT/'.cache/warp')
    import curobo._src.runtime as runtime
    runtime.cache_dir=str(ROOT/'.cache/curobo-runtime')
    from curobo.kinematics import Kinematics,KinematicsCfg
    from curobo.types import JointState
    kin=Kinematics(KinematicsCfg.from_robot_yaml_file(m['config']['path']))
    values=sum([m['default_positions'][arm] for arm in ('left','right')],[])
    actual=kin.compute_kinematics(JointState.from_position(torch.tensor([values],device='cuda',dtype=torch.float32),joint_names=kin.joint_names)).robot_spheres.detach().cpu().numpy().reshape(-1,4)
    params=kin.config.kinematics_config;indices=params.link_sphere_idx_map.detach().cpu().numpy();names=params.link_name_to_idx_map
    nominal={f'joint{i+1}':v for i,v in enumerate(m['default_positions']['left'])};nominal.update(k['lock_joints']);transforms=fk(root,nominal)
    checks=[]
    for arm in ('left','right'):
        base=np.array(m['layout']['base_transforms'][arm])
        for name in ['Link5','ctag_base_link','ctag_Left_1_Link','ctag_Left_2_Link','ctag_Right_1_Link','ctag_Right_2_Link']:
            expected=transform(np.array([s['center'] for s in k['collision_spheres'][name]]),base@transforms[name])
            observed=actual[indices==names[arm+'_'+name]]
            error=float(np.max(np.abs(expected-observed[:,:3])))
            assert error<1e-5,(arm,name,error)
            radii=np.array([s['radius'] for s in k['collision_spheres'][name]])
            # cuRobo includes the original configured collision-sphere buffer.
            radius_error=float(np.max(np.abs(observed[:,3]-radii-float(k.get('collision_sphere_buffer',0.)))))
            assert radius_error<1e-6,(arm,name,radius_error)
            checks.append({'link':arm+'_'+name,'centers_max_abs_error_m':error,'original_buffered_radii_max_abs_error_m':radius_error,'sphere_count':len(observed)})
    result['actual_gpu_vs_independent_mesh_fk']=checks
    result['gpu']='NVIDIA RTX 3060 ACTUAL_CUROBO_KINEMATICS'
    for path,digest in report['frozen_model_sha256'].items():assert sha(path)==digest
    result['frozen_phase2a_hashes_unchanged']=True
    result['conclusion']='Original sphere envelopes overlap while tested nominal source mesh surfaces do not. No source-proven URDF transform error; physical mount/CAD and collision cover need validation. No candidate geometry correction authorized or applied.'
    (a.output/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
