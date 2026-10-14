"""Runnable paused-time loop. This revision permits fake local Bridge ONLY."""
import argparse,json,time,traceback
from pathlib import Path
from action_interface import HandoffBridgeAdapter,MacBridgeConfig,context_from_observation,accept_result,execute_action

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--mock-bridge-config',type=Path);p.add_argument('--max-decisions',type=int,default=16);p.add_argument('--real',action='store_true');a=p.parse_args()
 if a.real:raise SystemExit('BLOCKED: full physical handoff baseline is not accepted; this task has zero real-generation authorization.')
 if not a.mock_bridge_config or not 1<=a.max_decisions<=16:raise SystemExit('Offline mock Bridge config and 1..16 decisions required')
 bridge=HandoffBridgeAdapter(MacBridgeConfig.load(a.mock_bridge_config));from dual_scene import DualScene
 from prepare_initial import prepare_left
 w=DualScene(a.output);history=[];report={'model_calls':0,'source':'MOCK_PROTOCOL_NOT_ASTRA','decisions':0,'status':'RUNNING'}
 try:
  w.start_video();obs=prepare_left(w)
  for i in range(a.max_decisions):
   c,images=context_from_observation(obs,history);folder=w.output/f'decision_{i:03d}';step_before=w.steps;t=time.monotonic()
   response=bridge.infer(c,images,folder);assert w.steps==step_before
   report['decisions']+=1;action=accept_result(folder);(folder/'proposal.json').write_text(json.dumps(action,indent=2))
   receipt=execute_action(w,action);(folder/'receipt.json').write_text(json.dumps(receipt,indent=2));(folder/'timing.json').write_text(json.dumps({'inference_wall_s':response['wall_latency_s'],'whole_step_wall_s':time.monotonic()-t,'inference_physics_steps':0,'execution_physics_steps':w.steps-step_before}))
   history.append({'proposal':action,'receipt':receipt})
   if action['done']:report['status']='MODEL_STOP_REQUEST_NOT_SUCCESS';break
   obs=w.observe(w.output/f'observation_{i+1:03d}')
  else:report['status']='DECISION_LIMIT_TRUNCATED'
 except Exception as e:report.update(status='STOPPED',error=repr(e),traceback=traceback.format_exc())
 finally:w.close();(a.output/'episode.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
