"""Single argument mapping shared by terminal launchers and the local GUI."""
import json
import math
import os
import sys
from pathlib import Path
from io_utils import ROOT
from history_diagnostics import PROFILES

ALL_PROFILES = (*PROFILES, 'legacy1', 'legacy5', 'legacy4')
DEFAULTS = {'profile':'H5D0','mode':'shadow','task':'','max_steps':10,'wall_budget_s':480,
            'phase':'placement','layout_id':'L1','trial_id':'trial-01','preview_port':8765}


def validate(settings):
    if not isinstance(settings,dict) or set(settings)-set(DEFAULTS):
        raise ValueError('未知配置项；仅支持 '+', '.join(DEFAULTS))
    s = dict(DEFAULTS,**settings)
    if s['profile'] not in ALL_PROFILES or s['mode'] not in ('shadow','execute'):
        raise ValueError('PROFILE_OR_MODE')
    if type(s['max_steps']) is not int or not 1<=s['max_steps']<=50:
        raise ValueError('max_steps 必须为 1–50 的整数')
    if not isinstance(s['task'],str) or not s['task'].strip() or len(s['task'])>12000:
        raise ValueError('请输入任务（最多 12000 字符）')
    if (type(s['wall_budget_s']) not in (int,float) or not math.isfinite(s['wall_budget_s'])
        or not 0<s['wall_budget_s']<=86400):
        raise ValueError('wall_budget_s 必须大于 0 且不超过 86400')
    if s['phase'] not in ('placement','full-pick-place','diagnostic'):
        raise ValueError('PHASE')
    for key in ('layout_id','trial_id'):
        if not isinstance(s[key],str) or not 1<=len(s[key])<=128:
            raise ValueError(key+' 长度须为 1–128')
    if type(s['preview_port']) is not int or not 1024<=s['preview_port']<=65535:
        raise ValueError('preview_port 必须为 1024–65535')
    return s


def runner_args(settings, *, no_preview=False, lock_path=None):
    s=validate(settings);profile=s['profile']
    entry={'legacy1':'run_left_terminal.py','legacy5':'run_left_threeview_history5.py',
           'legacy4':'run_left_fourview.py'}.get(profile,'run_left_history_diagnostics.py')
    args=[str(ROOT/'scripts'/entry),'--live','--model','gpt-6-astra','--task',s['task'],
          '--max-steps',str(s['max_steps']),'--preview-port',str(s['preview_port'])]
    if s['mode']=='execute':args+=['--execute']
    if no_preview:args+=['--no-preview']
    if profile in PROFILES:
        args+=['--profile',profile,'--wall-budget-s',str(s['wall_budget_s']),
               '--phase',s['phase'],'--layout-id',s['layout_id'],'--trial-id',s['trial_id']]
        if lock_path:args+=['--lock-path',str(lock_path)]
    return args
