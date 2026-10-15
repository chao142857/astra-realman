"""Transfer-only loop: gated real shadow first, then a separately selected execution.

Same transport, parser and numeric executor. No expert code after left pickup.
"""
import argparse
import json
import os
import time
import traceback
from pathlib import Path
from action_interface import (HandoffBridgeAdapter, MacBridgeConfig, context_from_observation,
                              accept_result, execute_action)
from transfer_gate import Gate, prepare


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',choices=['handoff_transfer_only'],required=True)
    p.add_argument('--output',type=Path)
    p.add_argument('--prepare-budget',type=Path)
    p.add_argument('--budget-root',type=Path)
    p.add_argument('--authorization',type=Path)
    p.add_argument('--preflight',type=Path)
    p.add_argument('--bridge-config',type=Path)
    p.add_argument('--mock-bridge-config',type=Path)
    p.add_argument('--max-decisions',type=int,default=16)
    p.add_argument('--mode',choices=['shadow','execute'],default='shadow')
    p.add_argument('--real',action='store_true')
    a=p.parse_args()
    if a.prepare_budget:
        if a.real:raise ValueError('PREPARE_NEVER_AUTHORIZES_GENERATION')
        print(json.dumps(prepare(a.prepare_budget),indent=2));return
    if a.output is None or not 1<=a.max_decisions<=16:raise ValueError('NEW_OUTPUT_AND_1_TO_16_DECISIONS_REQUIRED')
    if a.output.exists():raise ValueError('EPISODE_OUTPUT_EXISTS_NO_RETRY')
    gate=None
    if a.real:
        if a.mock_bridge_config or any(x is None for x in (a.budget_root,a.authorization,a.preflight,a.bridge_config)):raise ValueError('NEW_AUTHORIZATION_AND_PRODUCTION_CHECK_REQUIRED')
        if not a.output.resolve().is_relative_to(a.budget_root.resolve()):raise ValueError('AUTHORIZED_OUTPUT_SCOPE')
        gate=Gate(a.budget_root,a.authorization,a.preflight,a.bridge_config,a.mode)
        config=MacBridgeConfig.load(a.bridge_config)
    else:
        if not a.mock_bridge_config or a.bridge_config:raise ValueError('MOCK_CONFIG_REQUIRED_WITHOUT_REAL_AUTHORIZATION')
        config=MacBridgeConfig.load(a.mock_bridge_config)
    adapter=HandoffBridgeAdapter(config,offline_test=not a.real,task_id=a.task)
    root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    from dual_scene import DualScene
    from initial_transfer import prepare_left
    from evaluate_transfer import assess
    w=None;history=[]
    report={'task':a.task,'mode':a.mode,'source':'REAL_ASTRA' if a.real else 'MOCK_NOT_ASTRA',
            'real_client_dispatches':0,'decisions':0,'numeric_refusals':0,'phase':'initialization','status':'RUNNING'}
    try:
        w=DualScene(a.output);w.start_video();w.observe(w.output/'ready_observation')
        obs=prepare_left(w)
        report['phase']='decision_loop'
        for index in range(1 if a.mode=='shadow' else a.max_decisions):
            if gate and gate.state['reserved_budget']>=gate.limit:
                report['status']='BUDGET_LIMIT_TRUNCATED';break
            context,images=context_from_observation(obs,history,task_id=a.task)
            folder=w.output/f'decision_{index:03d}';before=w.steps;start=time.monotonic()
            reservation=gate.reserve(folder,context) if gate else None
            if gate:adapter._reserved_dispatch=True
            report['real_client_dispatches']+=int(a.real)
            try:
                response=adapter.infer(context,images,folder,real=a.real,timeout_s=180)
                report['decisions']+=1
                if w.steps!=before:raise RuntimeError('PHYSICS_ADVANCED_DURING_INFERENCE')
                action=accept_result(folder)
                if gate:gate.complete(reservation,folder)
            except Exception:
                if gate:gate.stop('MODEL_PROTOCOL_OR_TRANSPORT_OR_UNKNOWN')
                report['status']='MODEL_OUTPUT_OR_INFRASTRUCTURE_FAILURE';raise
            (folder/'proposal.json').write_text(json.dumps(action,indent=2)+'\n')
            receipt={'ok':True,'executed':False,'reason':'SHADOW_ONLY_NO_ACTION_EXECUTED'}
            try:
                if a.mode=='execute':receipt=execute_action(w,action)
                if a.mode=='execute' and action['done']:
                    w.phase_name='model_stop_passive_hold';w.tick(500)
            except Exception as exc:
                receipt={'ok':False,'executed':'PARTIAL_OR_SAFETY_STOP','reason':str(exc)}
                report['status']='PHYSICAL_EXECUTION_FAILURE'
                if gate:gate.stop('PHYSICAL_EXECUTION_FAILURE')
                raise
            finally:
                (folder/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
                category=('PHYSICAL_EXECUTION_FAILURE' if report['status']=='PHYSICAL_EXECUTION_FAILURE' else
                          'SHADOW_NO_EXECUTION' if a.mode=='shadow' else
                          'IK_COLLISION_OR_GENERIC_LIMIT_REJECTION' if not receipt['ok'] else 'ACCEPTED')
                report['numeric_refusals']+=int(category=='IK_COLLISION_OR_GENERIC_LIMIT_REJECTION')
                (folder/'decision_outcome.json').write_text(json.dumps({'category':category,'proposal_modified':False,'receipt_is_raw':True},indent=2)+'\n')
                (folder/'timing.json').write_text(json.dumps({'inference_wall_s':response['wall_latency_s'],
                    'whole_step_wall_s':time.monotonic()-start,'inference_physics_steps':0,
                    'execution_physics_steps':w.steps-before,'usage':response.get('usage'),
                    'usage_kind':response.get('usage_status'),'cache':'Preserved verbatim in raw usage; absent means unavailable.'},indent=2)+'\n')
            history.append({'proposal':action,'receipt':receipt})
            if a.mode=='shadow':report['status']='SHADOW_VALID_NO_EXECUTION';break
            if action['done']:report['status']='MODEL_STOP_REQUEST_NOT_AUTOMATIC_SUCCESS';break
            obs=w.observe(w.output/f'observation_{index+1:03d}')
        else:report['status']='DECISION_LIMIT_TRUNCATED'
    except BaseException as exc:
        if report['status']=='RUNNING':report['status']='INITIALIZATION_FAILURE' if report['phase']=='initialization' else 'INPUT_INTEGRITY_OR_CLIENT_FAILURE'
        if not isinstance(exc,Exception):report['status']='INTERRUPTED_OR_UNKNOWN'
        if gate:gate.stop(report['status'])
        report.update(error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            report['private_physical_assessment']=assess(w.records,w.dt)
            report.update(physics_steps=w.steps,sim_time_s=w.steps*w.dt)
            w.close();(w.output/'episode.json').write_text(json.dumps(report,indent=2)+'\n')
        elif a.output.exists():(a.output/'episode.json').write_text(json.dumps(report,indent=2)+'\n')
        if gate:
            if a.mode=='execute' and gate.state['status']=='READY':
                gate.state.update(status='FINISHED',episode_status=report['status']);gate.flush()
            gate.close()
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
