"""Read-only post-run analysis of this STOPPED episode; no Bridge/model imports."""
import csv,gzip,hashlib,io,json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def read(path):return json.loads(path.read_text())
def main():
    import jsonschema
    episode=ROOT/'episode';meta=read(episode/'episode.json');ledger=read(ROOT/'final_ledger_PUBLIC_REDACTED.json')
    rows=[json.loads(x) for x in gzip.decompress((episode/'physics.jsonl.gz').read_bytes()).splitlines()]
    decisions=[];threads=[];executed_gripper_commands=0;group_counts={'attempted':0,'executed':0,'rejected_without_motion':0}
    for d in sorted(episode.glob('decision_*')):
        response=read(d/'response.json');transport=read(d/'transport.json');wire=read(d/'bridge_request.json')
        value=json.loads(response['raw']);schema_valid=True
        try:jsonschema.validate(value,wire['context']['output_schema'])
        except jsonschema.ValidationError:schema_valid=False
        events=[json.loads(x) for x in response['events'].splitlines() if x.strip()]
        ids=[x['thread_id'] for x in events if x.get('type')=='thread.started'];threads+=ids
        repeats=[i for i,s in enumerate(value['stages']) if len({x['arm'] for x in s['actions']})!=len(s['actions'])]
        r=read(d/'receipt.json') if (d/'receipt.json').exists() else None
        timing=read(d/'timing.json') if (d/'timing.json').exists() else None
        usage=response.get('usage') or {}
        item={'decision_index':int(d.name.split('_')[-1])+1,'schema_valid':schema_valid,
            'client_action_accepted':r is not None,'duplicate_arm_stages_zero_based':repeats,
            'cli_turn_completed':sum(x.get('type')=='turn.completed' for x in events),
            'http_status':transport.get('http_status'),'return_code':response['return_code'],
            'model_parameter_audit':transport.get('remote_model_parameter_audit'),'thread_id':ids[0] if ids else None,
            'request_id':wire['request_id'],'raw_sha256':hashlib.sha256(response['raw'].encode()).hexdigest(),
            'input_tokens':usage.get('input_tokens'),'cached_input_tokens':usage.get('cached_input_tokens'),
            'output_tokens':usage.get('output_tokens'),'reported_reasoning_tokens':usage.get('reasoning_output_tokens'),
            'inference_wall_s':response['wall_latency_s'],'executed':r.get('executed') if r else False,
            'execution_ok':r.get('ok') if r else None,'execution_reason':r.get('reason') if r else 'DUPLICATE_ARM_IN_STAGE',
            'execution_physics_steps':timing['execution_physics_steps'] if timing else 0,
            'inference_physics_steps':timing['inference_physics_steps'] if timing else 0,
            'inference_pause_evidence':'FROZEN_RUNNER_ASSERTION' if timing else 'NO_TICKS_BETWEEN_OBSERVATION_AND_REJECTED_OUTPUT',
            'chunk_numeric_groups_attempted':r.get('numeric_groups_attempted',0) if r else 0,
            'original_actions':value}
        if r:
            for group in r['groups']:
                gr=group['receipt'];group_counts['attempted']+=1
                if gr.get('executed'):group_counts['executed']+=1
                else:group_counts['rejected_without_motion']+=1
                if gr.get('executed'):
                    executed_gripper_commands+=sum('opening' in c for c in group['commands'].values())
        decisions.append(item)
    totals={k:sum(x[k] for x in decisions) for k in ('input_tokens','cached_input_tokens','output_tokens','reported_reasoning_tokens','inference_wall_s','execution_physics_steps')}
    totals['other_output_tokens']=totals['output_tokens']-totals['reported_reasoning_tokens']
    paths={s:{'actual_tcp_z_range_m':[min(x['arms'][s]['actual_grasp_center_world'][2] for x in rows),max(x['arms'][s]['actual_grasp_center_world'][2] for x in rows)],
        'actual_pad_gap_range_mm':[1000*min(x['arms'][s]['actual_pad_gap_m'] for x in rows),1000*max(x['arms'][s]['actual_pad_gap_m'] for x in rows)],
        'bilateral_contact_ticks':sum(x['bilateral_contact'][s] for x in rows)} for s in ('left','right')}
    summary={'batch_id':ledger['batch_id'],'execution_baseline':'d713a49a115937dcb3183c44bcfd82978d19e49b',
        'task':'handoff_place_full','host':'yanglab','ledger_status':ledger['status'],'actual_dispatches':ledger['reserved_budget'],
        'completed_cli_turns':sum(x['cli_turn_completed'] for x in decisions),'accepted_actions':sum(x['client_action_accepted'] for x in decisions),
        'distinct_ephemeral_threads':len(set(threads)),'unused_budget_not_reusable':16-ledger['reserved_budget'],
        'model_takeover_step':meta['model_takeover_step'],'expert_initialization_actions':meta['expert_initialization_actions'],
        'first_execution_blocker':{'decision':1,'stage_index_zero_based':2,'action':'gripper','requested_opening_fraction':.15,'contact_mode':'bilateral_hold','reason':decisions[0]['execution_reason'],'kind':'EXISTING_GEOMETRIC_PREFLIGHT_REJECTION_NOT_EXECUTED_COLLISION'},
        'stop_cause':{'decision':4,'reason':'DUPLICATE_ARM_IN_STAGE','public_json_schema_valid':decisions[3]['schema_valid'],
            'public_ordering_description':read(episode/'decision_003/bridge_request.json')['context']['conventions']['ordering'],
            'classification':'PUBLIC_SCHEMA_LOCAL_VALIDATOR_CONSTRAINT_MISMATCH','not_a_demonstrated_spatial_reasoning_failure':True,
            'no_schema_or_action_repair_performed':True},
        'model_completed_stages':{'approach_and_height_adjustment_only':True,'left_stable_grasp':False,'handoff':False,'right_independent_hold':False,'right_transport':False,'right_release_and_place':False},
        'full_task_success':False,'frozen_process_score':meta['historical_full_process_score_unchanged'],
        'independent_rescore_matches':meta['independent_rescore_matches'],'executed_gripper_commands':executed_gripper_commands,
        'numeric_groups':group_counts,'actual_arm_traces':paths,
        'cube_height_range_m':[min(x['object_pose'][2] for x in rows),max(x['object_pose'][2] for x in rows)],
        'final_cube_pose_PRIVATE':rows[-1]['object_pose'],'physics_steps':len(rows),'sim_time_s':meta['sim_time_s'],
        'episode_wall_s':meta['episode_wall_s'],'usage_and_time_totals':totals,
        'transport_or_cli_top_level_failures':0,'physical_protection_stops':0,'automatic_retries':0,
        'warning':'Single exploratory episode interrupted by an interface constraint mismatch. No population capability estimate; tokens are reported usage, wall time includes client/server and network overhead.'}
    (ROOT/'analysis_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (ROOT/'decisions_summary.json').write_text(json.dumps(decisions,indent=2)+'\n')
    fields=[k for k in decisions[0] if k!='original_actions']
    with (ROOT/'decisions.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:v for k,v in x.items() if k!='original_actions'} for x in decisions)
    fields=['step','sim_time_s','wall_time','phase','cube_x','cube_y','cube_z']
    for side in ('left','right'):
        fields += [side+'_'+key for key in ('tcp_x','tcp_y','tcp_z','qw','qx','qy','qz','gap_m','master_actual_rad','master_target_rad','bilateral_contact')]
        fields += [side+'_q'+str(i+1) for i in range(6)]
    with (ROOT/'tcp_gripper_trace.csv.gz').open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as z,io.TextIOWrapper(z,newline='') as text:
        w=csv.writer(text);w.writerow(fields)
        for r in rows:
            vals=[r[k] for k in ('step','sim_time_s','wall_time','phase')]+r['object_pose'][:3]
            for side in ('left','right'):
                a=r['arms'][side];idx=a['joint_names'].index('ctag_Left_1_Joint')
                vals+=a['actual_grasp_center_world']+a['flange_pose_world'][3:]+[a['actual_pad_gap_m'],a['gripper_master_rad'],r['drive_targets'][side][idx],r['bilateral_contact'][side]]+a['qpos'][:6]
            w.writerow(vals)
    try:
        import matplotlib;matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(3,1,figsize=(10,8),sharex=True)
        t=[r['sim_time_s'] for r in rows]
        for side in ('left','right'):
            axes[0].plot(t,[r['arms'][side]['actual_grasp_center_world'][2] for r in rows],label=side+' TCP')
            axes[1].plot(t,[r['arms'][side]['actual_pad_gap_m']*1000 for r in rows],label=side+' measured gap')
        axes[2].plot(t,[r['object_pose'][2]*1000 for r in rows],label='cube height (private evaluation)')
        axes[1].ticklabel_format(axis='y',style='plain',useOffset=False)
        axes[0].set_ylabel('TCP height (m)');axes[1].set_ylabel('Pad gap (mm)');axes[2].set_ylabel('Cube height (mm)');axes[2].set_xlabel('Physics simulation time (s), paused during inference')
        for ax in axes:ax.grid(alpha=.25);ax.legend(loc='best')
        fig.suptitle('Actual physical trace: stopped after 4 requests; no grasp established');fig.tight_layout();fig.savefig(ROOT/'actual_tcp_gripper_trace.png',dpi=150);plt.close(fig)
    except ImportError:pass
    print(json.dumps({k:v for k,v in summary.items() if k not in ('frozen_process_score','actual_arm_traces')},indent=2))

if __name__=='__main__':main()
