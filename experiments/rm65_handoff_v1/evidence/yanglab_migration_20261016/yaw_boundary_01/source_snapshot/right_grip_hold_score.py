"""Independent engineering hold criteria v1. Historical scorers remain unchanged."""
import numpy as np
from scipy.spatial.transform import Rotation


def relative(r):
    a=r['arms']['right'];rot=Rotation.from_quat(np.roll(a['flange_pose_world'][3:],-1))
    return rot.inv().apply(np.array(r['object_pose'][:3])-a['actual_grasp_center_world']), rot.inv()*Rotation.from_quat(np.roll(r['object_pose'][3:],-1))


def score(rows, dt=.004, required_s=2., reference=None):
    if not rows:return {'pass':False,'reason':'NO_SAMPLES'}
    base,rotation=relative(reference or rows[0]);max_pos=0.;max_angle=0.;max_pen=0.
    bad={'right_bilateral':[],'left_or_table_support':[],'interarm':[]}
    for r in rows:
        p,q=relative(r);max_pos=max(max_pos,float(np.linalg.norm(p-base)));max_angle=max(max_angle,float(np.degrees((rotation.inv()*q).magnitude())))
        if not r['bilateral_contact']['right']:bad['right_bilateral'].append(r['step'])
        for c in r['contacts']:
            names=c['names']
            if 'target_cube' in names:
                if any(n.startswith('L__') or n=='table' for n in names):bad['left_or_table_support'].append(r['step'])
                if any('Support_Link' in n for n in names):max_pen=max(max_pen,-min(p['separation'] for p in c['points']))
            if any(n.startswith('L__') for n in names) and any(n.startswith('R__') for n in names):bad['interarm'].append(r['step'])
    tests={'duration':len(rows)*dt>=required_s-1e-9,'continuous_bilateral':not bad['right_bilateral'],
        'no_external_support':not bad['left_or_table_support'],'no_interarm_contact':not bad['interarm'],
        'relative_translation_at_most_2mm':max_pos<=.002,'relative_rotation_at_most_5deg':max_angle<=5.,
        'penetration_at_most_2mm':max_pen<=.002,'object_remains_above_table':min(r['object_pose'][2] for r in rows)>.07}
    return {'version':'right_independent_hold_engineering_v1','pass':all(tests.values()),'checks':tests,
        'range_steps':[rows[0]['step'],rows[-1]['step']],'duration_s':len(rows)*dt,'required_s':required_s,
        'max_relative_translation_mm':max_pos*1000,'max_relative_rotation_deg':max_angle,
        'max_pad_penetration_mm':max_pen*1000,'violations':bad,
        'separate_from_historical_velocity_score':True}
