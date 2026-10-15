"""One-shot sequential campaign on the original simulator/executor. Dry-run default."""
import argparse
import gc
import json
import os
import time
import traceback
from pathlib import Path
from action_interface import MacBridgeConfig,accept_result,execute_action
from transfer_gate import save,now
from .contract import ROOT,SPEC,ORDER,prepare_initial,assess,rescore
from .gate import Gate,Limit,prepare
from .interface import Adapter,context_from_observation


def episode(gate,entry,adapter):
    os.environ['RM65_LAYOUT']=str(ROOT/SPEC['layout'])
    from dual_scene import DualScene,CONFIG
    from diagnose_decision4 import relocate_runtime_mesh_paths
    relocate_runtime_mesh_paths(CONFIG)
    class BoundedScene(DualScene):
        def tick(self,n):
            for _ in range(n):
                gate.check_time()
                super().tick(1)
    folder=gate.root/entry['episode_id'];start=time.monotonic();w=None;history=[]
    report={**{k:entry[k] for k in ('episode_id','condition_id','repeat')},
            'source':'MOCK_NOT_ASTRA' if gate.offline else 'REAL_ASTRA','status':'RUNNING',
            'decisions':0,'numeric_refusals':0,'executed_action_groups':0,'safety_stop':False,
            'phase':'INITIALIZATION','score':{'status':'NOT_SCORED'},'model_history_at_reset':[],
            'started_at':now(),'corrections_after_refusal':[],'rejections':[]}
    gate.begin_episode(entry)
    campaign_stop=None
    try:
        gate.check_time();w=BoundedScene(folder);w.start_video();w.observe(w.output/'ready_observation')
        obs=prepare_initial(w,entry['condition_id']);report['task_start_step']=w.task_start_step
        report['initialization_action_groups']=w.group_count
        report['phase']='DECISION_LOOP';last_refusal=None
        for index in range(7):
            gate.check_new_dispatch()
            context,images=context_from_observation(obs,history,w.campaign_policy)
            decision=w.output/f'decision_{index:03d}';before=w.steps;step_start=time.monotonic()
            row=gate.reserve(entry,decision,context)
            adapter.deadline=gate.deadline;adapter.reserved=True
            effective=min(180.,max(0.,gate.deadline-time.monotonic()))
            try:
                response=adapter.infer(context,images,decision,real=not gate.offline,timeout_s=180)
                if w.steps!=before:raise RuntimeError('PHYSICS_ADVANCED_DURING_INFERENCE')
                action=accept_result(decision);gate.complete(row,decision)
            except Exception:
                campaign_stop='WALL_TIME_LIMIT_COMPLETION_UNKNOWN' if gate.elapsed()>=3600 else 'PROTOCOL_TRANSPORT_OR_UNKNOWN'
                report['status']='BUDGET_TRUNCATED' if gate.elapsed()>=3600 else 'INFRASTRUCTURE_FAILURE'
                archived=decision/'response.json'
                failed=json.loads(archived.read_text()) if archived.exists() else {}
                try:
                    events=[json.loads(line) for line in failed.get('events','').splitlines() if line.strip()]
                    known=failed.get('return_code')==0 and sum(e.get('type')=='turn.completed' for e in events)==1
                except ValueError:known=False
                report['completion_unknown']=not known
                raise
            report['decisions']+=1
            save(decision/'proposal.json',action)
            receipt={'ok':False,'executed':False,'reason':'NOT_EXECUTED'}
            try:
                gate.check_time()
                receipt=execute_action(w,action)
            except Limit:
                receipt={'ok':False,'executed':'PARTIAL','reason':'CAMPAIGN_WALL_TIME_LIMIT'}
                raise
            except Exception:
                report.update(status='TASK_FAILURE',safety_stop=True)
                campaign_stop='PHYSICAL_SAFETY_OR_EXECUTION_ABORT'
                receipt={'ok':False,'executed':'PARTIAL_OR_SAFETY_STOP','reason':traceback.format_exc()}
                raise
            finally:
                save(decision/'receipt.json',receipt)
                report['executed_action_groups']+=sum(bool(r.get('executed')) for r in receipt.get('receipts',[receipt]))
                timing={'inference_wall_s':response['wall_latency_s'],'whole_step_wall_s':time.monotonic()-step_start,
                        'inference_physics_steps':0,'execution_physics_steps':w.steps-before,
                        'usage':response.get('usage'),'usage_status':response.get('usage_status'),
                        'client_timeout_ceiling_s':180,'effective_campaign_bounded_request_timeout_s':effective}
                save(decision/'timing.json',timing)
            if last_refusal is not None:
                report['corrections_after_refusal'].append({'decision':index+1,
                    'changed_proposal':action!=last_refusal,'accepted':receipt['ok'],
                    'note':'Observed change/acceptance, not an inferred internal reasoning process.'})
            last_refusal=action if not receipt['ok'] else None
            report['numeric_refusals']+=int(not receipt['ok'])
            if not receipt['ok']:
                text=json.dumps(receipt)
                category=('COLLISION_REJECTION' if 'COLLISION' in text else 'IK_REJECTION' if 'IK' in text else
                          'LIMIT_REJECTION' if 'WORKSPACE' in text or 'LIMIT' in text else
                          'TRACKING_MISS' if receipt.get('executed') is True else 'GENERIC_REJECTION')
                report['rejections'].append({'decision':index+1,'category':category,'receipt':receipt})
            history.append({'proposal':action,'receipt':receipt})
            if action['done']:
                report['termination']='MODEL_STOP';break
            obs=w.observe(w.output/f'observation_{index+1:03d}')
        else:report['termination']='EPISODE_DECISION_LIMIT'
    except Limit as exc:
        report.update(status='BUDGET_TRUNCATED',termination=str(exc))
        if str(exc)!='EPISODE_DECISION_LIMIT':campaign_stop=str(exc)
    except Exception as exc:
        if report['status']=='RUNNING':
            report['status']='INFRASTRUCTURE_FAILURE';campaign_stop='INITIALIZATION_OR_INPUT_FAILURE'
        report.update(error=repr(exc),traceback=traceback.format_exc())
    finally:
        if w:
            if hasattr(w,'campaign_policy'):
                report.setdefault('task_start_step',w.task_start_step)
                if report['status'] in ('RUNNING','BUDGET_TRUNCATED') and gate.elapsed()<3600:
                    try:
                        w.phase_name='campaign_terminal_hold_2s';report['terminal_hold_start_step']=w.steps
                        w.tick(500);report['terminal_hold_end_step']=w.steps
                    except Limit:
                        report.update(status='BUDGET_TRUNCATED',termination='WALL_TIME_LIMIT');campaign_stop='WALL_TIME_LIMIT'
                    except Exception as exc:
                        report.update(status='TASK_FAILURE',safety_stop=True,error=repr(exc));campaign_stop='PHYSICAL_SAFETY_OR_EXECUTION_ABORT'
                score=assess([r for r in w.records if r['step']>=w.task_start_step],w.dt,w.campaign_policy,safety_stop=report['safety_stop'])
                report['posthoc_actual_state_score']=score
                if report['status']=='INFRASTRUCTURE_FAILURE' or report.get('completion_unknown'):
                    report['score']={'status':'NOT_SCORED_INFRASTRUCTURE_OR_UNKNOWN'}
                else:
                    report['score']=score
                    if score['pass']:report['status']='SUCCESS'
                    elif report['status']=='RUNNING':
                        report['status']='BUDGET_TRUNCATED' if report.get('termination')=='EPISODE_DECISION_LIMIT' else 'TASK_FAILURE'
            report.update(physics_steps=w.steps,sim_time_s=w.steps*w.dt)
            if 'task_start_step' in report:report['task_sim_time_s']=(w.steps-report['task_start_step'])*w.dt
            w.observe(w.output/'final_observation');w.close()
        else:folder.mkdir(parents=True,exist_ok=True)
        report.update(episode_wall_s=time.monotonic()-start,finished_at=now())
        report['client_dispatches']=sum(r['episode_id']==entry['episode_id'] for r in gate.state['dispatches'])
        group_receipts=[]
        for p in sorted(folder.glob('group_*/receipt.json')):
            if report['phase']=='DECISION_LOOP' and int(p.parent.name.split('_')[1])>report.get('initialization_action_groups',0):
                group_receipts.append(json.loads(p.read_text()))
        report['completed_action_groups']=sum(r.get('executed') is True for r in group_receipts)
        report['partial_action_groups']=sum(isinstance(r.get('executed'),str) for r in group_receipts)
        report['executed_action_groups']=report['completed_action_groups']+report['partial_action_groups']
        save(folder/'episode.json',report)
        if w and hasattr(w,'campaign_policy'):
            independent=rescore(folder)
            if independent!=report['posthoc_actual_state_score']:raise RuntimeError('INDEPENDENT_RESCORE_MISMATCH')
        entry.update(status=report['status'],decisions=report['decisions'],episode_wall_s=report['episode_wall_s'],
                     artifact=entry['episode_id'],score=report['score'],numeric_refusals=report['numeric_refusals'],
                     executed_action_groups=report['executed_action_groups'],finished_at=report['finished_at'])
        gate.flush()
    return campaign_stop


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare',type=Path);p.add_argument('--budget-root',type=Path)
    p.add_argument('--authorization',type=Path);p.add_argument('--preflight',type=Path)
    p.add_argument('--bridge-config',type=Path);p.add_argument('--mock-bridge-config',type=Path)
    p.add_argument('--real',action='store_true')
    a=p.parse_args()
    if a.prepare:
        if a.real:raise ValueError('PREPARE_IS_NOT_AUTHORIZATION')
        print(json.dumps(prepare(a.prepare),indent=2));return
    if not a.real and a.mock_bridge_config is None:
        print(json.dumps({'mode':'DRY_RUN','real_requests':0,'order':ORDER},indent=2));return
    if any(v is None for v in (a.budget_root,a.authorization,a.preflight)) or (a.real and (a.bridge_config is None or a.mock_bridge_config)):
        raise ValueError('NEW_BOUND_AUTHORIZATION_AND_PREFLIGHT_REQUIRED')
    config_path=a.bridge_config if a.real else a.mock_bridge_config
    config=MacBridgeConfig.load(config_path)
    if a.real and config.endpoint!='http://127.0.0.1:18766':raise ValueError('DEDICATED_PRODUCTION_TUNNEL_REQUIRED')
    gate=Gate(a.budget_root,a.authorization,a.preflight,config_path,offline=not a.real)
    adapter=Adapter(config,offline_test=not a.real)
    try:
        for entry in gate.state['episodes']:
            try:gate.check_new_dispatch()
            except Limit as exc:gate.finish('LIMIT_REACHED',str(exc));break
            stop=episode(gate,entry,adapter)
            gc.collect()
            if stop:
                gate.finish('LIMIT_REACHED' if stop in ('GLOBAL_DISPATCH_LIMIT','WALL_TIME_LIMIT') else 'STOPPED',stop);break
            try:gate.check_new_dispatch()
            except Limit as exc:gate.finish('LIMIT_REACHED',str(exc));break
        else:gate.finish('FINISHED','FROZEN_ORDER_COMPLETED')
    except BaseException as exc:
        gate.finish('STOPPED','UNEXPECTED_OR_INTERRUPTED:'+type(exc).__name__)
        raise
    finally:
        gate.close()
        from .summary import summarize
        summarize(gate.root)


if __name__=='__main__':main()
