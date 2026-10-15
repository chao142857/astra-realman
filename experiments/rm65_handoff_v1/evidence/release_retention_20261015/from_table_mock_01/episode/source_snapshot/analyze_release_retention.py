"""Post-hoc diagnostics; never imported by the model context or executor."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def rows(folder, name='physics.jsonl'):
    p = folder/name
    if p.exists(): return [json.loads(x) for x in p.read_text().splitlines()]
    with gzip.open(str(p)+'.gz', 'rt') as f: return [json.loads(x) for x in f]


def cube_relative(row):
    a = row['arms']['right']; fl = np.array(a['flange_pose_world'])
    rot = Rotation.from_quat(np.roll(fl[3:], -1))
    return rot.inv().apply(np.array(row['object_pose'][:3])-np.array(a['actual_grasp_center_world'])), (
        rot.inv()*Rotation.from_quat(np.roll(row['object_pose'][3:], -1)))


def series(rr, release_step=7018):
    base = next(r for r in rr if r['step'] == release_step)
    origin, orientation = cube_relative(base)
    result = []
    previous = None
    for r in rr:
        if r['step'] < release_step-575: previous = r; continue
        a = r['arms']['right']; q = np.array(a['qpos']); relative, rot = cube_relative(r)
        names = a['joint_names']; qi = dict(zip(names, q))
        equations = [('ctag_Left_2_Joint','ctag_Left_1_Joint',1),
            ('ctag_Right_2_Joint','ctag_Left_1_Joint',-1),
            ('ctag_Right_1_Joint','ctag_Left_1_Joint',-1),
            ('ctag_Left_Support_Joint','ctag_Left_1_Joint',-1),
            ('ctag_Right_Support_Joint','ctag_Right_1_Joint',1)]
        errors = {child: qi[child]-m*qi[parent] for child,parent,m in equations}
        impulses = {'left_pad':0.,'right_pad':0.}; pen=0.; left=False; table=False
        for c in r['contacts']:
            if 'target_cube' not in c['names']: continue
            left |= any(n.startswith('L__') for n in c['names']); table |= 'table' in c['names']
            for key, name in [('left_pad','R__ctag_Left_Support_Link'),('right_pad','R__ctag_Right_Support_Link')]:
                if name in c['names']:
                    impulses[key] += sum(float(np.linalg.norm(p['impulse'])) for p in c['points'])
                    pen = max(pen, -min(p['separation'] for p in c['points']))
        result.append({'step':r['step'],'since_release_s':(r['step']-release_step)*.004,
            'right_gap_mm':a['actual_pad_gap_m']*1000,
            'master_rad':q[6], 'target_rad':r['drive_targets']['right'][6],
            'master_fd_rad_s':float((q[6]-previous['arms']['right']['qpos'][6])/.004) if previous else None,
            'mimic_error_rad':errors,'max_mimic_error_rad':max(abs(e) for e in errors.values()),
            'object_xyz_m':r['object_pose'][:3], 'relative_translation_change_mm':float(np.linalg.norm(relative-origin)*1000),
            'relative_rotation_change_deg':float(np.degrees((orientation.inv()*rot).magnitude())),
            'right_bilateral':r['bilateral_contact']['right'], 'left_cube_contact':left,'table_contact':table,
            'right_pad_penetration_mm':pen*1000, 'pad_impulse_norm_sum_Ns':impulses})
        previous = r
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True)
    p.add_argument('--cases',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    original=rows(a.original); indexed={r['step']:r for r in original}
    all_cases=[a.original,*a.cases]; report={'model_requests':0,'cases':{},
        'actuator_and_tendon_actual_torque':'UNKNOWN; qf is an external generalized-force command',
        'notes':['FD velocity uses identical joint/reference and 0.004s samples.',
                 'Contact impulse norms are engine contact impulses, not measured actuator torques.',
                 'No historical score is replaced. Prefix includes table pickup and actual contacts.']}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(5,1,figsize=(12,15),sharex=True)
    for folder in all_cases:
        rr=rows(folder); name=folder.name
        result=json.loads((folder/'result.json').read_text())
        if not any(r['step']==7018 for r in rr):
            report['cases'][name]={'last_step':rr[-1]['step'],'result':result,
                'release_window_available':False,'interpretation':'Earlier pickup failure; NOT a right-grip comparison.',
                'saved_numeric_prefix_proposals_equal':all(json.loads(f.read_text())==json.loads((a.original/f.parent.name/f.name).read_text()) for f in folder.glob('reference_*/proposal_PRIVATE.json'))}
            continue
        ss=series(rr)
        (a.output/(name+'_series.json')).write_text(json.dumps(ss,indent=2)+'\n')
        after=[v for v in ss if v['step']>7018]
        item={'last_step':rr[-1]['step'], 'observations':{},'input_folder':str(folder),
              'historical_score':result.get('historical_process_score_unchanged')}
        for key,test in [('left_contact_absent',lambda x:not x['left_cube_contact']),
                         ('right_bilateral_absent',lambda x:not x['right_bilateral']),
                         ('relative_translation_over_2mm',lambda x:x['relative_translation_change_mm']>2),
                         ('table_contact',lambda x:x['table_contact'])]:
            item['observations'][key]=next((v['step'] for v in after if test(v)),None)
        if folder != a.original:
            compare=[r for r in rr if r['step']<=7018]
            def maximum(field):return max(float(np.max(np.abs(np.array(field(r))-np.array(field(indexed[r['step']]))))) for r in compare)
            item['prefix_to_7018']={'samples':len(compare), 'cube_pose_max_abs_difference':maximum(lambda r:r['object_pose']),
                'left_qpos_max_abs_difference_rad':maximum(lambda r:r['arms']['left']['qpos']),
                'right_qpos_max_abs_difference_rad':maximum(lambda r:r['arms']['right']['qpos']),
                'bilateral_flags_all_equal':all(r['bilateral_contact']==indexed[r['step']]['bilateral_contact'] for r in compare)}
            readback = rows(folder,'readback.jsonl')
            after_rb=[r for r in readback if 7050<=r['before_step']<=7280]
            item['drive_readback']={'unique_master_settings':list({json.dumps(r['arms']['right']['drives']['ctag_Left_1_Joint'],sort_keys=True) for r in readback}),
                'native_master_qvel_range_rad_s':([min(r['arms']['right']['qvel'][6] for r in after_rb),max(r['arms']['right']['qvel'][6] for r in after_rb)] if after_rb else None),
                'external_qf_master_abs_max_Nm':(max(abs(r['arms']['right']['external_qf_command_NOT_measured_torque'][6]) for r in after_rb) if after_rb else None)}
            for v in ss:
                rb=next((r for r in readback if r['before_step']==v['step']),None) if v['step'] in [7018,7050,7100,7150,7200,7250,7280,7283,7316,7356] else None
                if rb:
                    item.setdefault('aligned_samples',[]).append(dict(v,native_master_qvel_before_step_rad_s=rb['arms']['right']['qvel'][6]))
        report['cases'][name]=item
        plot=[v for v in ss if -.5<=v['since_release_s']<=4]
        x=[v['since_release_s'] for v in plot]
        for ax,key in zip(axs,['right_gap_mm','master_fd_rad_s','max_mimic_error_rad','relative_translation_change_mm','right_pad_penetration_mm']):
            ax.plot(x,[v[key] for v in plot],label=name);ax.grid(alpha=.3);ax.set_ylabel(key)
    axs[0].legend(fontsize=8);axs[-1].set_xlabel('Simulation seconds since left open command (step 7018)')
    fig.tight_layout();fig.savefig(a.output/'release_comparison.png',dpi=140);plt.close(fig)
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
