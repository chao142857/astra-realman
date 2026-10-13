"""Independent Pilot02 input/scorer supplement; frozen V0 files remain unchanged.

Snapshots retain V0 transport geometry. A public task_policy.json supplements the
V0 task with a structured orientation rule, identically attached to A and C.
Using V0 scoring alone for Pilot02 is explicitly insufficient for free-yaw tasks.
"""
import copy
import hashlib
import json
import math
from spatial_eval.inputs import build_input
from spatial_eval.schema import parse_prediction
from spatial_eval.scoring import evaluate
from spatial_eval.geometry import axes, dot

VERSION='astra.pilot02.task_policy.v1'
POLICY_INSTRUCTION=('The public task_policy is part of the task constraints; '
                    'satisfy it as well as task.constraints.')

def validate_policy(policy):
    if set(policy)!={'version','task_id','orientation'} or policy['version']!=VERSION or policy['task_id']!='plan':
        raise ValueError('PILOT02_POLICY_CONTRACT')
    o=policy['orientation']
    if o['mode']=='upright_free_yaw':
        if o!={'mode':'upright_free_yaw','local_axis':[0,0,1],'world_axis':[0,0,1],'max_tilt_rad':.02}:
            raise ValueError('PILOT02_UPRIGHT_RULE')
    elif o['mode']=='fixed':
        if o!={'mode':'fixed','quaternion_wxyz':[1.,0.,0.,0.],'tolerance_rad':.02}:
            raise ValueError('PILOT02_FIXED_RULE')
    else: raise ValueError('PILOT02_ORIENTATION_MODE')


def policy_for(spec):
    p={'version':VERSION,'task_id':'plan','orientation':copy.deepcopy(spec['orientation_policy'])}
    validate_policy(p)
    return p


def validate_binding(task, policy):
    validate_policy(policy)
    if task['task_id']!=policy['task_id']:
        raise ValueError('PILOT02_TASK_POLICY_ID_MISMATCH')
    o=policy['orientation']; c=task['constraints']
    if o['mode']=='upright_free_yaw':
        if c['required_quaternion_wxyz'] is not None:
            raise ValueError('FREE_YAW_WITH_TARGET_QUATERNION')
    elif (c['required_quaternion_wxyz']!=o['quaternion_wxyz'] or
          c['orientation_tolerance_rad']!=o['tolerance_rad']):
        raise ValueError('PILOT02_FIXED_RULE_MISMATCH')


def build(snapshot, task, condition, policy):
    validate_binding(task,policy)
    context,manifest,images=build_input(snapshot,task,condition)
    context['instruction']+=' '+POLICY_INSTRUCTION
    context['task_policy']=copy.deepcopy(policy)
    manifest['pilot02_contract']=VERSION
    manifest['task_policy_sha256']=hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()
    manifest['v0_base_task_prompt_sha256']=manifest['task_prompt_sha256']
    prompt={'instruction':context['instruction'],'task':task,'task_policy':policy}
    manifest['task_prompt_sha256']=hashlib.sha256(json.dumps(prompt,sort_keys=True).encode()).hexdigest()
    manifest['full_public_task_sha256']=manifest['task_prompt_sha256']
    return context,manifest,images


def score(snapshot, task, prediction, policy):
    validate_binding(task,policy)
    parse_prediction(json.dumps(prediction),task)
    result=evaluate(snapshot,task,prediction)
    result=copy.deepcopy(result)
    result['scorer_contract']=VERSION
    if result['status']!='SCORED': return result
    o=policy['orientation']
    if o['mode']=='upright_free_yaw':
        local_z=axes(prediction['quaternion_wxyz'])[2]
        cosine=dot(local_z,[0,0,1])/math.sqrt(dot(local_z,local_z))
        tilt=math.acos(max(-1.,min(1.,cosine)))
        result['upright_tilt_rad']=tilt
        result['constraints']['upright_local_positive_z']=tilt<=o['max_tilt_rad']
    result['success']=all(result['constraints'].values())
    result['score']=float(result['success'])
    result['error_types']=[k for k,v in result['constraints'].items() if not v]
    return result
