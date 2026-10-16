"""Single full-task episode. No expert pickup; zero-generation/mock entry only."""
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
    p.add_argument('--real',action='store_true')
    a=p.parse_args()
    if a.real:raise SystemExit('BLOCKED: no new full pick-handoff-place generation authorization; historical ledgers cannot be used.')
    if not a.mock_bridge_config or not 1<=a.max_decisions<=16:p.error('new mock config and 1..16 decisions required')
    root=Path(__file__).resolve().parent
    os.environ['RM65_LAYOUT']=str(root/'scene_v4_ready_transfer_1100.json')
    from dual_scene import DualScene,CONFIG,CONTROLLER
    from diagnose_decision4 import relocate_runtime_mesh_paths
    from action_interface import MacBridgeConfig,accept_result,execute_action
    from full_handoff_task import FullAdapter,context_from_observation
    from evaluate_process import evaluate
    relocate_runtime_mesh_paths(CONFIG)
    adapter=FullAdapter(MacBridgeConfig.load(a.mock_bridge_config))
    report={'task':'handoff_place_full','source':'MOCK_NOT_ASTRA','model_requests':0,
            'controller':CONTROLLER,'decisions':0,'expert_initialization_actions':0,'status':'RUNNING'}
    w=None;history=[];started=time.monotonic()
    try:
        w=DualScene(a.output);w.start_video()
        # Only the normal physical reset/settle has run. No prepare_left import.
        assert all(x.state()['actual_pad_gap_m']>.085 for x in w.arms.values())
        assert not any(x.bilateral_pad_contact() for x in w.arms.values())
        report['model_takeover_step']=w.steps;obs=w.observe(w.output/'table_initial')
        for i in range(a.max_decisions):
            c,images=context_from_observation(obs,history);d=w.output/f'decision_{i:03d}';before=w.steps
            response=adapter.infer(c,images,d,timeout_s=180)
            assert w.steps==before,'PHYSICS_ADVANCED_DURING_INFERENCE'
            action=accept_result(d);report['decisions']+=1
            (d/'proposal.json').write_text(json.dumps(action,indent=2)+'\n')
            receipt={'ok':False,'executed':False,'reason':'NOT_EXECUTED'}
            try:receipt=execute_action(w,action)
            except Exception as exc:
                receipt={'ok':False,'executed':'PARTIAL' if w.steps>before else False,'reason':repr(exc)}
                raise
            finally:
                (d/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
                (d/'timing.json').write_text(json.dumps({'inference_wall_s':response['wall_latency_s'],
                    'inference_physics_steps':0,'execution_physics_steps':w.steps-before},indent=2)+'\n')
            history.append({'proposal':action,'receipt':receipt})
            if action['done']:
                report['status']='MODEL_STOP_NOT_AUTOMATIC_SUCCESS';break
            obs=w.observe(w.output/f'observation_{i+1:03d}')
        else:report['status']='DECISION_LIMIT_TRUNCATED'
        w.phase_name='terminal_passive_hold';w.tick(500)
    except Exception as exc:report.update(status='STOPPED',error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            w.observe(w.output/'final_observation');report.update(physics_steps=w.steps,sim_time_s=w.steps*w.dt)
            w.close();report['historical_full_process_score_unchanged']=evaluate(w.output)
            report['episode_wall_s']=time.monotonic()-started
            (w.output/'episode.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if report['status']=='STOPPED':raise SystemExit(1)


if __name__=='__main__':main()
