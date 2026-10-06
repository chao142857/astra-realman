#!/usr/bin/env python3
"""Prepare six paired placement trials; never starts hardware or model calls."""
import argparse
import shlex
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import new_run, write_json, ROOT

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New experiment directory under harness')
    p.add_argument('--task',help='Otherwise enter the common verbatim task once')
    p.add_argument('--max-steps',type=int,default=10)
    p.add_argument('--wall-budget-s',type=float,default=480)
    a=p.parse_args()
    if not 1<=a.max_steps<=50 or not 0<a.wall_budget_s<float('inf'):
        p.error('positive finite budget and 1..50 steps required')
    task=a.task if a.task is not None else input('Common placement task (verbatim): ')
    if not task.strip():p.error('task required')
    new_run(a.output)
    conditions=[('L1','H5D0'),('L1','H5D1'),('L2','H5D1'),('L2','H5D0'),('L3','H5D0'),('L3','H5D1')]
    trials=[];commands=[]
    for n,(layout,profile) in enumerate(conditions,1):
        trial='placement-%02d'%n
        command=[str(ROOT/'run_official_astra_history_diagnostics.sh'),'execute','--profile',profile,
                 '--layout-id',layout,'--trial-id',trial,'--phase','placement','--max-steps',str(a.max_steps),
                 '--wall-budget-s',str(a.wall_budget_s),'--task',task]
        trials.append({'trial_id':trial,'layout_id':layout,'profile':profile,'run':None,
                       'initial_images':None,'initial_pose':None,'ball_reliably_held':'unknown',
                       'human_intervention':'unknown','starting_state_deviation':'unknown',
                       'independent_stable_in_basket':'unknown','evidence':None,'notes':''})
        commands += ['# '+trial+' — restore this layout/start/ball/cameras before this single episode.',shlex.join(command),'']
    write_json(a.output/'plan.json',{'task':task,'phase':'placement','model':'gpt-6-astra','reasoning_effort':'low',
        'speed_percent':1,'max_steps':a.max_steps,'wall_budget_s':a.wall_budget_s,'trials':trials,
        'candidate_selection':{'profile':None,'reason':None,'full_pick_place_runs':[]},
        'rules':'Same budgets for all six. Independent stable-in-basket evidence, never model done. Up to three subsequent full pick/place runs; report separately.'})
    (a.output/'commands.txt').write_text('\n'.join(commands))
    print(a.output/'commands.txt')

if __name__=='__main__':main()
