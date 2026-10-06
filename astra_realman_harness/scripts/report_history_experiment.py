#!/usr/bin/env python3
"""Per-step durations and independently labelled outcomes; no inferred physical success."""
import argparse
import json
import statistics
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import read_json, write_json, new_run
from history_diagnostics import decode, PROFILES


def optional(path):
    return read_json(path) if path.exists() else {}


def report(run):
    summary = optional(run/'summary.json')
    profile = optional(run/'history_profile.json')
    profile.update(optional(run/'gui_launch.json').get('settings',{}))
    rows = []
    for step in sorted(run.glob('step-*')):
        timing = optional(step/'timing.json')
        stages = timing.get('stages',[])
        backend = optional(step/'decision/backend_result.json')
        execution = optional(step/'execution_result.json')
        check = optional(step/'feasibility.json')
        def stage(name):
            matches = [s['duration_s'] for s in stages if s['stage']==name]
            return sum(matches) if matches else None
        row = {'step':step.name,'step_total_s':timing.get('step_total_s'),
               'capture_input_s':stage('capture.input'),'capture_pre_execution_s':stage('capture.pre-execution'),
               'capture_between_channels_s':stage('capture.between-channels'),'capture_after_s':stage('capture.after'),
               'capture_failure_readback_s':stage('capture.failure-readback'),
               'request_context_s':stage('request_context'),
               'backend_total_s':backend.get('inference_latency_s'),
               'request_preparation_s':backend.get('request_preparation_s'),
               'transport_including_remote_cli_s':backend.get('transport_including_remote_cli_s'),
               'model_cli_s':backend.get('cli_latency_s'),
               'transport_only_s':None, 'ik_s':check.get('latency_s',stage('ik')),
               'executor_total_s':stage('executor') if stages else execution.get('execution_latency_s'),
               'arm_command_s':stage('arm_command'),'gripper_communication_s':stage('gripper_communication'),
               'gripper_settle_s':stage('gripper_settle'),
               'token_usage':backend.get('token_usage'),'execution_status':execution.get('status'),
               'ik_status':check.get('status'),'hardware_commands_sent':execution.get('hardware_commands_sent'),
               'camera_metrics':{}}
        for capture in ('input','pre-execution','between-channels','after','failure-readback'):
            capture_obs = optional(step/capture/'observation.json')
            if capture_obs.get('camera_capture'):
                row['camera_metrics'][capture] = capture_obs['camera_capture']
        # Only directly measured, disjoint step children are subtracted from the step parent.
        children = [s['duration_s'] for s in stages if s['parent']=='step']
        row['step_other_s'] = max(0,row['step_total_s']-sum(children)) if row['step_total_s'] is not None else None
        rows.append(row)
    metrics = {}
    for key in (rows[0] if rows else {}):
        if key.endswith('_s'):
            values = [row[key] for row in rows if isinstance(row.get(key),(int,float))]
            metrics[key] = {'available_steps':len(values),'total_s':sum(values) if values else None,
                            'median_s':statistics.median(values) if values else None}
    labels = optional(run/'independent_observation.json')
    success = labels.get('actual_stable_in_basket','unknown')
    if labels.get('episode_id') != summary.get('episode_id') or not labels.get('evidence') or not labels.get('observer'):
        success = 'unknown'
    invalid_steps = labels.get('ineffective_action_steps',[])
    invalid_outputs = 0
    for step in run.glob('step-*'):
        raw = step/'decision/astra_raw.txt'
        if raw.exists() and profile.get('profile') in PROFILES:
            try:decode(raw.read_text(),profile['profile'])
            except (ValueError,TypeError):invalid_outputs += 1
    return {'run':str(run),'synthetic':bool(profile.get('synthetic') or (run/'SYNTHETIC.json').exists()),'profile':profile,'summary':summary,'steps':rows,'timing_totals_and_medians':metrics,
            'independent_labels':labels,'independent_success':success,
            'ik_rejections':sum(r['ik_status']=='REJECTED_IK' for r in rows),
            'noop_actions':sum(r['execution_status']=='NOOP' for r in rows),
            'invalid_model_outputs':invalid_outputs,
            'independently_labelled_ineffective_actions':len(invalid_steps) if labels else None,
            'timing_semantics':{
                'episode':['step_total','setup/cleanup/other (not separately measured)'],
                'step':['capture.input','capture.pre-execution','request_context','backend','ik','executor','capture.after','step_other'],
                'executor':['arm_command','capture.between-channels','gripper_communication','gripper_settle','capture.failure-readback','other'],
                'backend':['request_preparation','transport including remote CLI','other'],
                'transport':'Includes remote CLI. Transport-only unavailable; no subtraction across clocks/boundaries.',
                'missing':'null = unavailable or not invoked; no fabricated precision; do not sum parent and child rows'}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs',type=Path,nargs='+')
    p.add_argument('--output',type=Path,required=True,help='New report directory under harness')
    a = p.parse_args()
    results = [report(run) for run in a.runs]
    new_run(a.output)
    write_json(a.output/'report.json',results)
    counts = {}
    for result in results:
        phase = result['profile'].get('phase','unknown')
        profile = result['profile'].get('profile','unknown')
        key = ('synthetic/' if result['synthetic'] else 'real/')+phase+'/'+profile
        count = counts.setdefault(key,{'episodes':0,'independently_observed_successes':0,'unknown_outcomes':0,'model_done':0})
        count['episodes'] += 1
        count['independently_observed_successes'] += result['independent_success'] is True
        count['unknown_outcomes'] += result['independent_success'] not in (True,False)
        count['model_done'] += result['summary'].get('status')=='MODEL_DONE'
    write_json(a.output/'counts_by_phase_profile.json',counts)
    lines = ['# Astra experiment report','',
             'Null/unavailable is missing or uninvoked. Durations are parent/child; never add nested totals.',
             'Placement and full pick/place are separate phases. Model done is not independent success.','']
    for r in results:
        lines += ['## '+r['run'],'',
                  'Profile: '+str(r['profile'].get('profile'))+'; phase: '+str(r['profile'].get('phase')),
                  'Status: '+str(r['summary'].get('status'))+'; independent stable-in-basket: '+str(r['independent_success']),
                  'Model calls: '+str(r['summary'].get('model_calls'))+'; IK rejections: '+str(r['ik_rejections']),
                  'Episode seconds: '+str(r['summary'].get('episode_total_s')),'',
                  '| Measured stage | Available steps | Total s | Median s |','|---|---:|---:|---:|']
        for key,value in r['timing_totals_and_medians'].items():
            lines.append('| '+key+' | '+' | '.join(str(value[k]) if value[k] is not None else 'unavailable' for k in ('available_steps','total_s','median_s'))+' |')
        lines += ['','| Step | Total s | CLI s | IK s | Executor s | Arm s | Gripper s | Settle s |','|---|---:|---:|---:|---:|---:|---:|---:|']
        for row in r['steps']:
            lines.append('| '+' | '.join(str(row[k]) if row[k] is not None else 'unavailable' for k in ('step','step_total_s','model_cli_s','ik_s','executor_total_s','arm_command_s','gripper_communication_s','gripper_settle_s'))+' |')
        lines += ['']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(a.output/'report.md')

if __name__ == '__main__':
    main()
