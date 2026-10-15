"""Independent private transfer-only physical assessment; never model feedback."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

CRITERIA=json.loads((Path(__file__).parent/'transfer_criteria_v1.json').read_text())


def assess(rows,dt):
    c=CRITERIA;segments=[];segment=None;drops=[];interarm=[];max_pen=0.;initial=[]
    initial_started=False;initial_poses=[];left_duration=0.;legacy_speed=[]
    for r in rows:
        xyz=np.asarray(r['object_pose'][:3]);obj_R=Rotation.from_quat(np.roll(r['object_pose'][3:],-1))
        contacts=[x for x in r['contacts'] if 'target_cube' in x['names']]
        left_contact=any(any(n.startswith('L__') for n in x['names']) for x in contacts)
        table=any('table' in x['names'] for x in contacts)
        for x in r['contacts']:
            names=x['names']
            if any(n.startswith('L__') for n in names) and any(n.startswith('R__') for n in names):interarm.append(r['step'])
            if 'target_cube' in names and any('Support_Link' in n for n in names):max_pen=max(max_pen,-min(p['separation'] for p in x['points']))
        if r['phase']=='transfer_initial_left_hold':
            initial_started=True
            arm=r['arms']['left'];rot=Rotation.from_quat(np.roll(arm['flange_pose_world'][3:],-1))
            initial_poses.append((rot.inv().apply(xyz-np.array(arm['actual_grasp_center_world'])),rot.inv()*obj_R))
            if r['bilateral_contact']['left'] and not table and xyz[2]>.07:left_duration+=dt
        elif initial_started and (table or xyz[2]<.06):drops.append(r['step'])
        independent=r['bilateral_contact']['right'] and not left_contact and not table and r['arms']['left']['actual_pad_gap_m']>c['released_left_gap_m'] and xyz[2]>c['minimum_object_center_z_m']
        legacy_speed.append(float(np.linalg.norm(r['object_velocity'])))
        if not independent:
            segment=None;continue
        arm=r['arms']['right'];rot=Rotation.from_quat(np.roll(arm['flange_pose_world'][3:],-1))
        relative_p=rot.inv().apply(xyz-np.array(arm['actual_grasp_center_world']));relative_R=rot.inv()*obj_R
        left_distance=float(np.linalg.norm(xyz-np.array(r['arms']['left']['actual_grasp_center_world'])))
        if segment is None:
            segment={'start_step':r['step'],'duration_s':0.,'after_exit_s':0.,'max_relative_translation_drift_m':0.,'max_relative_rotation_drift_deg':0.,'max_object_displacement_m':0.}
            segments.append(segment);origin=(xyz.copy(),relative_p,relative_R,left_distance)
        displacement=float(np.linalg.norm(xyz-origin[0]))
        segment['duration_s']+=dt
        segment['max_relative_translation_drift_m']=max(segment['max_relative_translation_drift_m'],float(np.linalg.norm(relative_p-origin[1])))
        segment['max_relative_rotation_drift_deg']=max(segment['max_relative_rotation_drift_deg'],float((origin[2].inv()*relative_R).magnitude()*180/np.pi))
        segment['max_object_displacement_m']=max(segment['max_object_displacement_m'],displacement)
        exited=displacement>=c['exit_object_displacement_m'] and left_distance>=origin[3]+c['exit_left_distance_increase_m']
        segment['after_exit_s']=segment['after_exit_s']+dt if exited else 0.
        retained=segment['max_relative_translation_drift_m']<=c['relative_translation_drift_max_m'] and segment['max_relative_rotation_drift_deg']<=c['relative_rotation_drift_max_deg']
        segment['retention_pass']=retained and segment['duration_s']>=c['independent_hold_s']-1e-8
        segment['retention_and_exit_pass']=segment['retention_pass'] and segment['after_exit_s']>=c['independent_hold_s']-1e-8
    drift=max((float(np.linalg.norm(p-initial_poses[0][0])) for p,_ in initial_poses),default=None)
    angle=max((float((initial_poses[0][1].inv()*r).magnitude()*180/np.pi) for _,r in initial_poses),default=None)
    checks={'initial_left_physical_hold':left_duration>=c['initial_left_hold_s']-1e-8 and drift is not None and drift<=c['relative_translation_drift_max_m'] and angle<=c['relative_rotation_drift_max_deg'],
            'right_independent_hold':any(s.get('retention_pass',False) for s in segments),
            'right_held_exit':any(s.get('retention_and_exit_pass',False) for s in segments),
            'no_drop':not drops,'no_interarm_contact':not interarm,'original_penetration_limit':max_pen<=c['max_pad_penetration_m']}
    return {'criteria':c,'checks':checks,'transfer_only_pass':all(checks.values()),'independent_segments':segments,
            'initial_left_hold_s':left_duration,'initial_left_relative_drift_m':drift,'initial_left_relative_rotation_deg':angle,
            'drop_steps':drops,'interarm_steps':interarm,'maximum_pad_penetration_m':max_pen,
            'reported_world_speed_max_m_s':max(legacy_speed,default=None),'source':'PRIVATE_PHYSICS_NOT_MODEL_INPUT'}


if __name__=='__main__':
    import argparse,gzip
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);a=p.parse_args()
    path=a.folder/'physics.jsonl'
    text=path.read_text() if path.exists() else gzip.decompress(path.with_suffix('.jsonl.gz').read_bytes()).decode()
    result=assess([json.loads(x) for x in text.splitlines()],json.loads((a.folder/'configuration.json').read_text())['dt'])
    (a.folder/'transfer_assessment_v1.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
