"""Private CAD/FK calibration on archived physical states; no state restoration."""
import argparse, gzip, json, os
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation


def read_rows(p):
    if p.exists(): return [json.loads(s) for s in p.read_text().splitlines()]
    with gzip.open(str(p)+'.gz','rt') as f: return [json.loads(s) for s in f]


def geometry(arm, q, object_pose=None):
    model=arm.motion.pinocchio_model; model.compute_forward_kinematics(np.asarray(q))
    surfaces=[]
    for name, vertices in arm.pad_vertices.items():
        tf=arm.calibration_world_from_model@model.get_link_pose(arm.motion.link_name_2_idx[arm.prefix+name]).to_transformation_matrix()
        center=vertices.mean(0); _,_,vh=np.linalg.svd(vertices-center); normal=vh[-1]
        residual=(vertices-center)@normal
        basis=vh[:2]; polygon=ConvexHull((vertices-center)@basis.T)
        surfaces.append({'name':name, 'center':tf[:3,:3]@center+tf[:3,3],
            'normal':tf[:3,:3]@normal, 'basis':tf[:3,:3]@basis.T,
            'hull':polygon,'residual_mm':float(np.max(abs(residual))*1000),
            'vertices_world':vertices@tf[:3,:3].T+tf[:3,3]})
    centers=np.array([s['center'] for s in surfaces]);axis=centers[1]-centers[0];axis/=np.linalg.norm(axis)
    center=(np.asarray(object_pose[:3]) if object_pose is not None else centers.mean(0))
    ts=[np.dot(s['normal'],s['center']-center)/np.dot(s['normal'],axis) for s in surfaces]
    result={'representative_distance_mm':float(np.linalg.norm(centers[1]-centers[0])*1000),
        'local_contact_plane_gap_mm':float(abs(ts[1]-ts[0])*1000),
        'plane_gap_definition':'Infinite fitted inner-face planes intersected along closing axis through object center; valid only inside actual pad footprint, NOT global minimum mesh distance.',
        'planes':[]}
    for s in surfaces:
        v=(center-s['center'])@s['basis']; margins=-(s['hull'].equations[:,:2]@v+s['hull'].equations[:,2])
        result['planes'].append({'name':s['name'],'plane_fit_max_residual_mm':s['residual_mm'],
            'center_projection_inside_pad':bool(np.min(margins)>=0),
            'center_projection_boundary_margin_mm':float(np.min(margins)*1000)})
    if object_pose is not None:
        R=Rotation.from_quat(np.roll(object_pose[3:],-1)).as_matrix()
        result['cube_width_along_closing_axis_mm']=float(2*np.sum(abs(R.T@axis)*.025)*1000)
    return result,surfaces


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    from dual_scene import DualScene,CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    relocate_runtime_mesh_paths(CONFIG)
    w=DualScene(a.output);arm=w.arms['right'];arm.init_planner()
    # Pinocchio FK is in its model frame, not the shared SAPIEN world.
    # Calibrate the constant transform from the same actual q and flange, then
    # verify both pad representative points against the actual physical links.
    model=arm.motion.pinocchio_model;model.compute_forward_kinematics(arm.robot.get_qpos())
    flange=model.get_link_pose(arm.motion.link_name_2_idx[arm.prefix+'Link6']).to_transformation_matrix()
    arm.calibration_world_from_model=arm.links['Link6'].pose.to_transformation_matrix()@np.linalg.inv(flange)
    _,surfaces=geometry(arm,arm.robot.get_qpos())
    fk_error=float(np.max(abs(np.array([s['center'] for s in surfaces])-arm.pads())))
    assert fk_error<1e-6, 'FK_WORLD_FRAME_MISMATCH'
    source=root/'evidence/full_handoff_restore_20261015/full_numeric_known_d3_urdf_effort_04'
    archived=read_rows(source/'physics.jsonl');report={'model_requests':0,'physics_state_writes':False,'source':str(source),'mapping':[],'samples':[],
        'world_from_pinocchio_model':arm.calibration_world_from_model.tolist(),'actual_pad_fk_max_abs_error_m':fk_error}
    q=np.asarray(archived[7017]['arms']['right']['qpos'])
    for opening in [1.,.55,.5,.45,0.]:
        qq=q.copy();qq[arm.master]=-.91*(1-opening)
        for name,(parent,m,offset) in arm.mimics.items():qq[arm.names.index(name)]=qq[arm.names.index(parent)]*m+offset
        value,_=geometry(arm,qq);report['mapping'].append(dict(value,opening_fraction=opening,ideal_master_target_rad=float(qq[arm.master])))
    for r in archived:
        if r['step'] not in [6698,7018,7050,7150,7280,7283,7316]:continue
        state=r['arms']['right'];value,surfaces=geometry(arm,state['qpos'],r['object_pose'])
        value.update(step=r['step'],actual_master_rad=state['qpos'][arm.master],master_target_rad=r['drive_targets']['right'][arm.master],contacts=[])
        for c in r['contacts']:
            if 'target_cube' not in c['names']:continue
            for surface in surfaces:
                if arm.prefix+surface['name'] not in c['names']:continue
                for point in c['points']:
                    uv=(np.array(point['p'])-surface['center'])@surface['basis']
                    margins=-(surface['hull'].equations[:,:2]@uv+surface['hull'].equations[:,2])
                    value['contacts'].append({'pad':surface['name'],'position_world':point['p'],
                        'within_pad_plane_footprint':bool(np.min(margins)>=-1e-4),
                        'pad_boundary_margin_mm':float(np.min(margins)*1000),
                        'impulse_Ns':point['impulse'],'separation_mm':point['separation']*1000})
        report['samples'].append(value)
    w.close();(a.output/'calibration.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'mapping':report['mapping'],'samples':[{k:v for k,v in s.items() if k!='contacts'} for s in report['samples']]},indent=2))


if __name__=='__main__':main()
