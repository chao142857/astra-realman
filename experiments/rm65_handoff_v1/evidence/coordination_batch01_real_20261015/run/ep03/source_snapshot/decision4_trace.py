"""Read-only, post-hoc trace for the single archived fourth-decision incident."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import numpy as np


def read_rows(folder, name='physics.jsonl'):
    p = Path(folder) / name
    data = p.read_bytes() if p.exists() else gzip.decompress(p.with_suffix(p.suffix + '.gz').read_bytes())
    return [json.loads(x) for x in data.decode().splitlines() if x.strip()]


def rotation(q):
    w, x, y, z = np.asarray(q, float) / np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def angle(a, b):
    return float(np.degrees(np.arccos(np.clip((np.trace(a.T @ b)-1)/2, -1, 1))))


def relative(row, side='left'):
    arm = row['arms'][side]
    r = rotation(arm['flange_pose_world'][3:])
    return r.T @ (np.asarray(row['object_pose'][:3])-arm['actual_grasp_center_world']), r.T @ rotation(row['object_pose'][3:])


def pad_penetration(row):
    result = {}
    for c in row['contacts']:
        if 'target_cube' not in c['names']:
            continue
        for n in c['names']:
            if 'Support_Link' in n:
                result[n] = max(0., -min(x['separation'] for x in c['points'])) * 1000
    return result


def compare_start(actual, reference):
    """Strict comparability checks, separate from unchanged task/safety scoring."""
    ap, ar = relative(actual); rp, rr = relative(reference)
    metrics = {'step_difference': actual['step']-reference['step'],
               'object_position_error_m': float(np.linalg.norm(np.asarray(actual['object_pose'][:3])-reference['object_pose'][:3])),
               'object_rotation_error_deg': angle(rotation(actual['object_pose'][3:]), rotation(reference['object_pose'][3:])),
               'object_relative_position_error_m': float(np.linalg.norm(ap-rp)),
               'object_relative_rotation_error_deg': angle(ar, rr)}
    checks = [metrics['step_difference'] == 0, metrics['object_position_error_m'] <= 1e-5,
              metrics['object_rotation_error_deg'] <= .01,
              metrics['object_relative_position_error_m'] <= 1e-5,
              metrics['object_relative_rotation_error_deg'] <= .01]
    for side in ('left', 'right'):
        a, b = actual['arms'][side], reference['arms'][side]
        d = {'max_joint_error_rad': float(np.max(np.abs(np.asarray(a['qpos'])-b['qpos']))),
             'gap_error_m': abs(a['actual_pad_gap_m']-b['actual_pad_gap_m']),
             'max_drive_target_error_rad': float(np.max(np.abs(np.asarray(actual['drive_targets'][side])-reference['drive_targets'][side])))}
        metrics[side] = d
        checks.extend((d['max_joint_error_rad'] <= 1e-4, d['gap_error_m'] <= 1e-5, d['max_drive_target_error_rad'] <= 1e-6))
    def contact_pairs(r):
        return sorted(sorted(c['names']) for c in r['contacts'] if 'target_cube' in c['names'])
    metrics['object_contact_pairs_match'] = contact_pairs(actual) == contact_pairs(reference)
    metrics['bilateral_contact_match'] = actual['bilateral_contact'] == reference['bilateral_contact']
    pa, pr = pad_penetration(actual), pad_penetration(reference)
    metrics['max_pad_penetration_difference_mm'] = max([0.] + [abs(pa.get(k, 0)-pr.get(k, 0)) for k in pa.keys() | pr.keys()])
    checks.extend((metrics['object_contact_pairs_match'], metrics['bilateral_contact_match'], metrics['max_pad_penetration_difference_mm'] <= .01))
    return {'comparable': all(checks), 'metrics': metrics,
            'note': 'Predeclared state-match tolerances only, not changed physical success criteria. Full contacts/state saved separately.'}


def analyze(folder, output, start_step=3467):
    folder, output = Path(folder), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows = read_rows(folder)
    ref = next(r for r in rows if r['step'] == start_step)
    dt = json.loads((folder/'configuration.json').read_text())['dt']
    p0, r0 = relative(ref); tcp0 = rotation(ref['arms']['left']['flange_pose_world'][3:])
    gap0 = ref['arms']['left']['actual_pad_gap_m']
    pen0 = max(pad_penetration(ref).values(), default=0.)
    engine = {}
    if (folder/'measurements.jsonl').exists() or (folder/'measurements.jsonl.gz').exists():
        engine = {x['step']: x for x in read_rows(folder, 'measurements.jsonl')}
    trace = []
    for i, row in enumerate(rows):
        if row['step'] < start_step-99:
            continue
        p, r = relative(row); arm = row['arms']['left']; pen = pad_penetration(row)
        sample = {'step': row['step'], 'time_from_action4_s': (row['step']-start_step)*dt,
                  'phase': row['phase'], 'relative_translation_mm': float(np.linalg.norm(p-p0))*1000,
                  'relative_rotation_deg': angle(r0, r),
                  'tcp_rotation_from_start_deg': angle(tcp0, rotation(arm['flange_pose_world'][3:])),
                  'gap_mm': arm['actual_pad_gap_m']*1000,
                  'gap_change_mm': (arm['actual_pad_gap_m']-gap0)*1000,
                  'absolute_gap_change_mm': abs(arm['actual_pad_gap_m']-gap0)*1000,
                  'maximum_pad_penetration_mm': max(pen.values(), default=0.),
                  'penetration_increase_mm': max(pen.values(), default=0.)-pen0,
                  'left_bilateral': row['bilateral_contact']['left'],
                  'right_bilateral': row['bilateral_contact']['right'],
                  'object_engine_speed_m_s': float(np.linalg.norm(row['object_velocity'])),
                  'contacts_json': json.dumps(row['contacts'], separators=(',', ':'))}
        for k in range(3):
            sample['tcp_xyz_m_'+str(k)] = arm['actual_grasp_center_world'][k]
            sample['object_relative_xyz_m_'+str(k)] = float(p[k])
        for name, depth in pen.items():
            sample[name+'_penetration_mm'] = depth
        for side in ('left', 'right'):
            a = row['arms'][side]
            for j, name in enumerate(a['joint_names']):
                key = side+'_'+name
                sample[key+'_q_rad'] = a['qpos'][j]
                sample[key+'_drive_target_rad'] = row['drive_targets'][side][j]
                sample[key+'_finite_difference_qvel_rad_s'] = (a['qpos'][j]-rows[i-1]['arms'][side]['qpos'][j])/dt
                if row['step'] in engine:
                    sample[key+'_engine_qvel_rad_s'] = engine[row['step']]['qvel'][side][j]
                    sample[key+'_drive_velocity_target_rad_s'] = engine[row['step']]['drive_velocity_targets'][side][j]
        trace.append(sample)
    fields = sorted(set().union(*(x.keys() for x in trace)))
    with (output/'trace.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(trace)
    active = [x for x in trace if x['step'] > start_step]
    thresholds = {'relative_translation_mm': [.01, .05, .1, .25, .5, 1.],
                  'relative_rotation_deg': [.05, .1, .5, 1.],
                  'absolute_gap_change_mm': [.01, .05, .1, .25, .5, 1.],
                  'penetration_increase_mm': [.01, .05, .1, .25, .5, 1.]}
    crossings = {}
    for metric, levels in thresholds.items():
        crossings[metric] = []
        for level in levels:
            first = next((x for x in active if x[metric] >= level), None)
            sustained = next((active[i] for i in range(len(active)-2) if all(x[metric] >= level for x in active[i:i+3])), None)
            crossings[metric].append({'descriptive_level': level,
                                     'first_step': None if first is None else first['step'],
                                     'first_three_consecutive_steps_start': None if sustained is None else sustained['step']})
    stable = [x for x in trace if x['step'] <= start_step]
    result = {'start_step': start_step, 'dt': dt, 'recorded_steps': len(rows),
              'pre_action4_last_100_steps_ranges': {k: [min(x[k] for x in stable), max(x[k] for x in stable)] for k in thresholds},
              'level_crossings': crossings,
              'level_note': 'Descriptive levels, not new scoring or stability thresholds. Ordering depends on units/level. Three samples = 12 ms sampling coverage; not a causal test.',
              'left_master_target_range_rad': [min(x['left_ctag_Left_1_Joint_drive_target_rad'] for x in trace), max(x['left_ctag_Left_1_Joint_drive_target_rad'] for x in trace)],
              'joint_velocity_source': 'Finite differences plus PhysX measurements sidecar' if engine else 'Original archive has qpos only: same-reference, dt=.004 finite differences; not relabeled as engine qvel.',
              'first_action_step': active[0] if active else None, 'last_step': trace[-1]}
    (output/'trace_summary.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--episode', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); analyze(a.episode, a.output)
