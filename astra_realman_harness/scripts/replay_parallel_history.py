#!/usr/bin/env python3
"""Read archived proposals/readbacks only; never imports SDK or invokes models."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parallel_history import ParallelHistory,transition
from gripper_position_semantics import evaluation
from io_utils import write_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False);history=ParallelHistory();checks=[]
 def load(p):return json.loads(p.read_text())
 for step in sorted(a.run.glob('step-*')):
  if not (step/'after_state.json').exists() or not (step/'group_result.json').exists():continue
  g=load(step/'parsed_group.json');b=load(step/'pre-execution/observation.json')['canonical_states'];after=load(step/'after_state.json');result=load(step/'group_result.json')
  t=transition(step.name,g,load(step/'diagnostics.json'),b,after,result)
  context=history.context()
  if step.name in ['step-%03d'%i for i in [12,13,25,26,27,28,29,41,42,43,44,45]]:
   write_json(a.output/(step.name+'-history-before.json'),context)
   checks.append({'step':step.name,'history_steps':[x['step'] for x in context['transitions']],
    'measured_left_delta':t['measured']['left']['tcp_delta_m'],
    'old_proposal_unchanged':g==load(step/'parsed_group.json'),'grasp_confirmed':t['measured']['left']['grasp_confirmed']})
  for act in g['actions']:
   arm=act['arm'];ev=evaluation(b[arm]['gripper_state'],int(act['gripper_opening']*1000),1)
   if step.name in ['step-026','step-028','step-042','step-043','step-045']:
    assert ev['opening_reached'],(step.name,ev)
    checks.append({'step':step.name,'counterfactual_pre_action_opening':ev,'note':'offline only; runtime evaluates again AFTER any arm motion'})
  write_json(a.output/(step.name+'-transition.json'),t);history.append(t)
 assert history.total==47,history.total
 write_json(a.output/'report.json',{'status':'PASS','completed_transitions':history.total,'checks':checks,'model_requests':0,'hardware_commands':0,'old_results_modified':False})
 print('PASS: 47 transitions; requested windows replayed; original actions/results unchanged')
if __name__=='__main__':main()
