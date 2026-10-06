#!/usr/bin/env python3
"""Freeze one recorded decision and completed prefix; never roll out counterfactual actions."""
import argparse
import copy
import json
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, new_run, read_json, write_json
from history_diagnostics import PROFILES, TransitionHistory, schema_path, decode, build_transition
from left_terminal import call_astra


def decision_observation(step):
    for path in (step/'input_observation.json', step/'input/observation.json'):
        if path.exists():
            return read_json(path)
    raise ValueError('DECISION_OBSERVATION_MISSING:'+str(step))


def ready_time(obs):
    return obs.get('decision_ready_at', max([obs['captured_at'],obs['canonical_states']['left']['timestamp']]
                                           + [c['captured_at'] for c in obs['cameras']]))


def import_legacy(step, episode):
    """Only complete final logs qualify; never reconstruct from raw after/observation.json."""
    required = ['next_observation.json','parsed_action.json','executed_action.json','execution_result.json',
                'feasibility.json','pre-execution/observation.json']
    missing = [n for n in required if not (step/n).is_file()]
    if missing:
        raise ValueError('LEGACY_FINAL_RECORDS_MISSING:'+str(missing))
    decision = decision_observation(step)
    after = read_json(step/'next_observation.json')
    execution = read_json(step/'execution_result.json')
    if execution['executed_action'] != read_json(step/'executed_action.json'):
        raise ValueError('LEGACY_DISPATCH_RECORD_MISMATCH')
    return build_transition(episode,int(step.name.split('-')[-1]),decision,
        read_json(step/'pre-execution/observation.json'),after,read_json(step/'parsed_action.json'),
        execution,read_json(step/'feasibility.json'),completed_at=ready_time(after))


def prepare(run, step_number, output, *, profiles=PROFILES, allow_legacy=False, infer=False):
    step = run/('step-%02d'%step_number)
    obs = decision_observation(step)
    obs['decision_ready_at'] = ready_time(obs)
    episode = obs.get('episode_id', run.name)
    records = []
    for n in range(1,step_number):
        prefix_step = run/('step-%02d'%n)
        path = prefix_step/'transition.json'
        if path.exists():
            t = read_json(path)
        elif allow_legacy:
            t = import_legacy(prefix_step, episode)
        else:
            raise ValueError('FINAL_TRANSITION_MISSING:'+str(path))
        if t['step'] != n:
            raise ValueError('PREFIX_STEP_MISMATCH')
        records.append(t)
    new_run(output)
    write_json(output/'replay_manifest.json', {
        'source_run':str(run),'decision_step':step_number,'observation_id':obs['observation_id'],
        'completed_prefix_steps':[t['step'] for t in records],
        'mode':'FIXED_OBSERVATION_NOT_ROLLOUT','synthetic':obs.get('source','').startswith('SYNTHETIC'),
        'warning':'Alternative actions have no observed outcomes. Never score old future images as their results.'})
    write_json(output/'final_transitions.json',records)
    for profile in profiles:
        folder = new_run(output/profile)
        history = TransitionHistory(profile,episode)
        for t in records:
            history.append(t)
        schema = schema_path(profile)
        context = history.context(obs,read_json(schema),step_number)
        write_json(folder/'model_input.json',context)
        decision = new_run(folder/'decision')
        if infer:
            raw = call_astra(context,decision,read_json(ROOT/'config/decision_backend.json'),
                             'gpt-6-astra',threading.Event(),lambda *v:print(*v,flush=True),
                             schema_path=schema,decoder=lambda raw:decode(raw,profile)[1])
            (folder/'raw_proposal.txt').write_text(raw)
            diagnostics,action = decode(raw,profile)
            write_json(folder/'parsed_action.json',action)
            if diagnostics is not None:
                write_json(folder/'diagnostics.json',diagnostics)
        else:
            (decision/'prompt.txt').write_text(json.dumps(context,ensure_ascii=False,allow_nan=False))
            write_json(decision/'attachments.json',context['images_in_attachment_order'])
            write_json(decision/'backend_result.json',{'backend':'PREPARED_ONLY_NO_MODEL','model_calls':0})
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--step',type=int,required=True)
    p.add_argument('--output',type=Path,required=True,help='New directory under harness; exclusive writes.')
    p.add_argument('--profiles',nargs='+',choices=PROFILES,default=PROFILES)
    p.add_argument('--import-legacy',action='store_true',help='Require final next_observation + dispatch logs; fail on missing evidence.')
    p.add_argument('--infer',action='store_true',help='One REAL model call per profile; never hardware. Default prepares only.')
    a = p.parse_args()
    if a.step < 1 or len(set(a.profiles)) != len(a.profiles):
        p.error('positive step and distinct profiles required')
    print(prepare(a.run,a.step,a.output,profiles=a.profiles,allow_legacy=a.import_legacy,infer=a.infer))

if __name__ == '__main__':
    main()
