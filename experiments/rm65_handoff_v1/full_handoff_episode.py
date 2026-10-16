"""Single full-task episode. No expert pickup; real entry requires a new, batch-bound grant."""
import argparse
import json
import os
import time
import traceback
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',choices=['handoff_place_full'],default='handoff_place_full')
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--mock-bridge-config',type=Path)
    p.add_argument('--max-decisions',type=int,default=16)
    p.add_argument('--right-hold-control',choices=['original','master_damping0_v3'],default='original')
    p.add_argument('--action-interface',choices=['numeric_v1','chunk_v2'],default='numeric_v1')
    p.add_argument('--budget-root',type=Path)
    p.add_argument('--authorization',type=Path)
    p.add_argument('--preflight',type=Path)
    p.add_argument('--bridge-config',type=Path)
    p.add_argument('--real',action='store_true')
    a=p.parse_args()
    if a.real and not all((a.budget_root,a.authorization,a.preflight,a.bridge_config)):raise SystemExit('BLOCKED: no new full pick-handoff-place generation authorization; historical ledgers cannot be used.')
    if not 1<=a.max_decisions<=16 or (not a.real and not a.mock_bridge_config):p.error('new mock config and 1..16 decisions required')
    if a.real and (a.action_interface!='chunk_v2' or a.right_hold_control!='master_damping0_v3' or a.max_decisions!=16):p.error('frozen chunk/controller/16-decision parameters required')
    root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    from dual_scene import DualScene,CONFIG,CONTROLLER
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from action_interface import MacBridgeConfig,accept_result,execute_action
    from full_handoff_task import FullAdapter,context_from_observation
    if a.action_interface=='chunk_v2':
        from chunk_handoff_task import ChunkAdapter as FullAdapter,context_from_observation,accept_result
        from numeric_action_chunk import execute_chunk as execute_action
    from evaluate_process import evaluate
    if a.right_hold_control!='original' and CONTROLLER!='urdf_effort_hold_v2':
        p.error('master_damping0_v3 was validated with explicit RM65_CONTROLLER=urdf_effort_hold_v2')
    relocate_runtime_mesh_paths(CONFIG)
    gate=None
    if a.real:
        from full_task_gate import Gate
        if a.output.resolve()!=a.budget_root.resolve()/'episode' or a.output.exists():p.error('new dedicated episode output required')
        gate=Gate(a.budget_root,a.authorization,a.preflight,a.bridge_config)
        adapter=FullAdapter(MacBridgeConfig.load(a.bridge_config),offline_test=False)
    else:adapter=FullAdapter(MacBridgeConfig.load(a.mock_bridge_config))
    report={'task':'handoff_place_full','source':'MOCK_NOT_ASTRA','model_requests':0,
            'controller':CONTROLLER,'action_interface':a.action_interface,'decisions':0,'expert_initialization_actions':0,'status':'RUNNING'}
    if a.action_interface=='chunk_v2' and a.right_hold_control!='master_damping0_v3':
        p.error('chunk_v2 declares the validated master_damping0_v3 controller; select it explicitly')
    if a.real:report.update(source='REAL_ASTRA_ATTEMPT',batch_id=gate.state['batch_id'])
    w=None;history=[];started=time.monotonic()
    try:
        w=DualScene(a.output)
        if a.right_hold_control=='master_damping0_v3':
            from right_hold_velocity_v3 import install
            report['right_hold_control']=install(w)
        w.start_video()
        # Only the normal physical reset/settle has run. No prepare_left import.
        assert all(x.state()['actual_pad_gap_m']>.085 for x in w.arms.values())
        assert not any(x.bilateral_pad_contact() for x in w.arms.values())
        report['model_takeover_step']=w.steps;obs=w.observe(w.output/'table_initial')
        for i in range(a.max_decisions):
            c,images=context_from_observation(obs,history);d=w.output/f'decision_{i:03d}';before=w.steps
            if gate:
                row=gate.reserve(d,c);adapter._reservation=(gate,row)
            response=adapter.infer(c,images,d,real=a.real,timeout_s=180)
            if gate:gate.complete(row,d)
            assert w.steps==before,'PHYSICS_ADVANCED_DURING_INFERENCE'
            action=accept_result(d);report['decisions']+=1
            (d/'proposal.json').write_text(json.dumps(action,indent=2)+'\n')
            receipt={'ok':False,'executed':False,'reason':'NOT_EXECUTED'}
            try:receipt=execute_action(w,action)
            except BaseException as exc:
                receipt={'ok':False,'executed':'PARTIAL' if w.steps>before else False,'reason':repr(exc)}
                raise
            finally:
                (d/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
                (d/'timing.json').write_text(json.dumps({'inference_wall_s':response['wall_latency_s'],
                    'inference_physics_steps':0,'execution_physics_steps':w.steps-before},indent=2)+'\n')
            if a.action_interface=='chunk_v2':
                from numeric_action_chunk import public_receipt
                feedback=public_receipt(receipt)
                (d/'public_feedback.json').write_text(json.dumps(feedback,indent=2)+'\n')
            else:feedback=receipt
            history.append({'proposal':action,'receipt':feedback})
            if action['done']:
                report['status']='MODEL_STOP_NOT_AUTOMATIC_SUCCESS';break
            obs=w.observe(w.output/f'observation_{i+1:03d}')
        else:report['status']='DECISION_LIMIT_TRUNCATED'
        w.phase_name='terminal_passive_hold';w.tick(500)
    except BaseException as exc:
        report.update(status='STOPPED',error=repr(exc),traceback=traceback.format_exc())
        if gate:gate.stop(repr(exc))
    finally:
        try:
            if w:
                w.observe(w.output/'final_observation');report.update(physics_steps=w.steps,sim_time_s=w.steps*w.dt)
                w.close();report['historical_full_process_score_unchanged']=evaluate(w.output)
                # Independent invocation, not a copied score from the first pass.
                independent=evaluate(w.output)
                report['independent_rescore_matches']=independent==report['historical_full_process_score_unchanged']
                (w.output/'independent_score.json').write_text(json.dumps(independent,indent=2)+'\n')
                report['episode_wall_s']=time.monotonic()-started
        except BaseException as exc:
            report.update(status='STOPPED',finalization_error=repr(exc))
        finally:
            if gate:
                report['model_requests']=gate.state['reserved_budget']
                if report['status']=='STOPPED':gate.stop(report.get('error',report.get('finalization_error','UNKNOWN_STOP')))
                else:
                    gate.state.update(status='FINISHED' if report['status']=='MODEL_STOP_NOT_AUTOMATIC_SUCCESS' else 'TRUNCATED',episode_status=report['status']);gate.flush()
                gate.close()
            if w:(w.output/'episode.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if report['status']=='STOPPED':raise SystemExit(1)


if __name__=='__main__':main()
