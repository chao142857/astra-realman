"""Independent read-only comparison of the finite interface replays. No scoring edits."""
import argparse,gzip,hashlib,json
from pathlib import Path
import numpy as np


def rows(path):
    p=path/'physics.jsonl'
    packed=p.with_suffix('.jsonl.gz')
    data=gzip.decompress(packed.read_bytes()) if packed.exists() else p.read_bytes()
    return [json.loads(s) for s in data.splitlines()]


def pad_depth(row):
    return max([0.]+[-p['separation'] for c in row['contacts']
        if 'target_cube' in c['names'] and any('Support_Link' in n for n in c['names']) for p in c['points']])


def event_rows(path):
    packed=path.with_suffix(path.suffix+'.gz')
    data=gzip.decompress(packed.read_bytes()) if packed.exists() else path.read_bytes()
    return [json.loads(s) for s in data.splitlines()]


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    root=a.root;source=Path(__file__).resolve().parent
    legacy=json.loads((root/'legacy_d1_physics_01/replay.json').read_text())
    assert legacy['status']=='REPRODUCED_ORIGINAL_PRECHECK_REJECTION'
    assert all(legacy['archived_start_state_exact_checks'].values())
    baseline=rows(root/'legacy_d1_physics_01')[-1]
    d1=rows(root/'contact_d1_physics_01');matched=next(r for r in d1 if r['step']==11675)
    keys=('step','object_pose','object_velocity','drive_targets','bilateral_contact','contacts','arms')
    prefix={k:matched[k]==baseline[k] for k in keys}
    prefix.update({s+'_qpos':matched['arms'][s]['qpos']==baseline['arms'][s]['qpos'] for s in ('left','right')})
    assert all(prefix.values())
    group=root/'contact_d1_physics_01/group_052'
    guard=json.loads((group/'contact_guard_summary_PRIVATE.json').read_text())
    events=event_rows(root/'contact_d1_physics_01/left/events.jsonl')
    latch=[e for e in events if e['event']=='explicit_contact_hold']
    assert len(latch)==1
    closure=[r for r in d1 if r['step']>=11675]
    unexpected=[]
    for r in closure:
        for c in r['contacts']:
            own=[n for n in c['names'] if n.startswith('L__ctag_')]
            if own and ('table' in c['names'] or ('target_cube' in c['names'] and not any('Support_Link' in n for n in own))):
                unexpected.append({'step':r['step'],'contact':c})
    d4=json.loads((root/'sequential_d4_physics_01/replay.json').read_text())
    assert d4['new_receipt']['ok'] and all(d4['archived_start_state_exact_checks'].values())
    original=rows(source/'evidence/full_task_real_20261016/episode')
    old_prefix={r['step']:r for r in original if r['step'] in (11675,27325)}
    d4_prefix=next(r for r in rows(root/'sequential_d4_physics_01') if r['step']==27325)
    full_archived_checks={str(step):{key:actual[key]==old_prefix[step][key] for key in keys}
        for step,actual in ((11675,baseline),(27325,d4_prefix))}
    assert all(all(c.values()) for c in full_archived_checks.values())
    duplicates=[g for g in d4['new_receipt']['groups'] if g['stage_index']==2]
    assert [g['input_action_indices']['left'] for g in duplicates]==[0,1]
    assert duplicates[1]['receipt']['start_step']==duplicates[0]['receipt']['end_step']
    assert duplicates[1]['operation_start_measured_tcp']['left'][:3]==duplicates[0]['receipt']['actual_states']['left']['actual_grasp_center_world']
    negative=json.loads((root/'vacant_table_physics_01/negative_control.json').read_text())
    assert negative['status']=='PASS_TABLE_COLLISION_STOP' and negative['first_bilateral_step']['left'] is None
    positive=json.loads((root/'known_grasp_release_physics_01/acceptance.json').read_text())
    assert positive['status']=='PASS_INTERFACE_ONLY_NOT_FULL_TASK' and positive['release_regression']['pass']
    environment=json.loads((root/'migration_environment.json').read_text())
    after={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in environment['historical_ledger_hashes']}
    assert after==environment['historical_ledger_hashes']
    summary={'real_model_requests':0,'bridge_connections':0,'historical_ledgers_unchanged':True,
        'archived_ledger_count':len(after),'asset_file_count':environment['asset_file_count'],
        'native_physics_only_no_rgb_or_video':True,
        'full_archived_state_contact_checks':full_archived_checks,
        'original_d1':{'old_refusal':'INTERPOLATED_COLLISION:left:105','matched_before_closure':prefix,
            'closure_start_step':11675,'first_bilateral_step':guard['first_bilateral_step']['left'],
            'contact_latch_events':latch,'stop_step':d1[-1]['step'],'stop_reason':guard['execution_abort'],
            'maximum_pad_penetration_m':max(map(pad_depth,closure)),
            'measured_forbidden_fcl_before_stop':guard['first_danger'],
            'table_or_nonpad_contacts_before_stop':unexpected,
            'requested_opening_fraction':.15,'requested_empty_space_master_rad':-.91*(1-.15),
            'actual_master_at_stop_rad':d1[-1]['arms']['left']['gripper_master_rad'],
            'conclusion':'Empty-space precheck was not a valid prediction of the latched closure. Actual bilateral contact precedes a native 2mm pad penetration stop. The unchanged answer is not safe; old predicted table/nonpad collision was not observed before this stop.'},
        'original_d4':{'start_state_exact_checks':d4['archived_start_state_exact_checks'],
            'numeric_groups':len(d4['new_receipt']['groups']),'start_step':d4['new_execution_start_step'],
            'end_step':d4['new_execution_end_step'],'duplicate_operations':duplicates,
            'conclusion':'Both original repeated left operations executed separately in list order; second starts from measured predecessor state. All D4 groups completed; this answer contains no gripper command and does not establish a grasp.'},
        'normal_grasp':positive['post_lift_private_evidence'],'normal_release':positive['release_regression'],
        'vacant_table_negative':{'stop_step':negative['physics_steps'],'first_danger':negative['first_table_danger'],
            'first_bilateral_step':negative['first_bilateral_step']},
        'full_pick_handoff_place':'NOT_VALIDATED_NOT_COMPLETED_BY_THESE_REPLAYS'}
    (root/'independent_analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
    # Ordinary scientific plot of measured PhysX samples, never a synthetic RGB.
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    # Read the loaded configuration rather than assuming the linkage joint order.
    names=d1[-1]['arms']['left']['joint_names']
    import xml.etree.ElementTree as ET
    cfg=json.loads((source/'runtime_config/assembly.json').read_text());master=names.index(cfg['gripper_master'])
    t=np.array([(r['step']-11675)*.004 for r in closure])
    fig,axes=plt.subplots(3,1,figsize=(8,7),sharex=True)
    axes[0].plot(t,[r['arms']['left']['gripper_master_rad'] for r in closure],label='Measured master')
    axes[0].plot(t,[r['drive_targets']['left'][master] for r in closure],label='Servo target')
    axes[0].set_ylabel('rad');axes[0].legend()
    axes[1].plot(t,[r['arms']['left']['actual_pad_gap_m']*1000 for r in closure]);axes[1].set_ylabel('Pad centre gap (mm)')
    axes[2].plot(t,[pad_depth(r)*1000 for r in closure]);axes[2].axhline(2,color='red',label='Unchanged native limit')
    axes[2].set_ylabel('Max pad penetration (mm)');axes[2].set_xlabel('Physics time since closure began (s)');axes[2].legend()
    for ax in axes:
        ax.axvline((guard['first_bilateral_step']['left']-11675)*.004,color='green',ls='--')
        ax.axvline((latch[0]['step']-11675)*.004,color='orange',ls=':');ax.grid(alpha=.2)
    fig.suptitle('Original Decision 1: actual contact-dependent closure, real PhysX\nGreen: first bilateral; orange: latch. No RGB/video: GPU unavailable.')
    fig.tight_layout();fig.savefig(root/'decision1_contact_timing.png',dpi=160);plt.close(fig)
    print(json.dumps({'all_assertions_passed':True,'d1_stop_step':d1[-1]['step'],'d1_max_pad_penetration_mm':summary['original_d1']['maximum_pad_penetration_m']*1000,'d4_groups':len(d4['new_receipt']['groups']),'ledgers_unchanged':len(after)},indent=2))


if __name__=='__main__':main()
