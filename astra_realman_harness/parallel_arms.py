"""One model decision -> one bounded arm group. Existing per-arm action semantics."""
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io_utils import strict_json, write_json
from arm_stack import schema_for
from left_terminal import parse


def group_schema(states):
    item=schema_for(states)
    item['properties']['done']={'type':'boolean','enum':[False]}
    return {'type':'object','additionalProperties':False,'required':['done','execution','actions'],
            'properties':{'done':{'type':'boolean'},'execution':{'type':'string','enum':['parallel','sequential']},
                          'actions':{'type':'array','minItems':0,'maxItems':2,'items':item}},
            'description':'One decision for both arms. At most one action per arm; omitted arm holds. Each arm uses its own controller work/tool frame. Parallel is for independent actions, not a synchronized handoff. done=true requires no actions.'}


def parse_group(raw,states):
    group=strict_json(raw) if isinstance(raw,str) else copy.deepcopy(raw)
    if not isinstance(group,dict) or set(group)!={'done','execution','actions'}:raise ValueError('GROUP_FIELDS')
    if type(group['done']) is not bool or group['execution'] not in ('parallel','sequential'):raise ValueError('GROUP_TYPE')
    actions=group['actions']
    if not isinstance(actions,list) or len(actions)>2:raise ValueError('MAX_ONE_ACTION_PER_ARM')
    if group['done'] and actions:raise ValueError('DONE_WITH_ACTIONS')
    seen=set()
    for action in actions:
        arm=action.get('arm') if isinstance(action,dict) else None
        if arm not in states or arm in seen:raise ValueError('DUPLICATE_OR_UNKNOWN_ARM')
        s=states[arm];parse(json.dumps(action,allow_nan=False),arm,s['work_frame']['id'],s['tool_frame']['id'])
        if action['done']:raise ValueError('USE_GROUP_DONE')
        seen.add(arm)
    return group


class GroupCoordinator:
    """Workers own disjoint SDK processes. Parent owns the model and group ordering."""
    def __init__(self,workers,stop):self.workers=workers;self.stop=stop;self.active=False;self.consumed=set()
    def run(self,group,step,*,execute=False):
        if self.active:raise RuntimeError('GROUP_ALREADY_RUNNING')
        if self.stop.is_set():raise RuntimeError('HUMAN_STOP')
        key=str(step.resolve())
        if key in self.consumed:raise RuntimeError('GROUP_ALREADY_CONSUMED')
        self.consumed.add(key);self.active=True;start=time.monotonic()
        write_json(step/'parsed_group.json',group)
        result={'status':'STARTED','execution':group['execution'],'arms':{},'held_arms':sorted(set(self.workers)-{a['arm'] for a in group['actions']})}
        try:
            if group['done']:result['status']='MODEL_DONE';return result
            # Complete ALL checks before dispatching EITHER arm.
            prepared={}
            for action in group['actions']:
                arm=action['arm'];prepared[arm]=self.workers[arm].prepare(action,step/arm)
            write_json(step/'group_preflight.json',prepared)
            if any(p['status']=='CHECK_ERROR' for p in prepared.values()):raise RuntimeError('GROUP_CHECK_FAULT')
            if any(p['status']=='REJECTED_IK' for p in prepared.values()):
                result.update(status='REJECTED_IK',preflight=prepared);return result
            if any(p['status'] not in ('PASS_IK','NOT_REQUIRED') for p in prepared.values()):raise RuntimeError('UNKNOWN_PREFLIGHT')
            if not execute:result.update(status='SHADOW_ONLY',preflight=prepared);return result
            if self.stop.is_set():raise RuntimeError('HUMAN_STOP')
            if group['execution']=='parallel':
                # Both RPCs start without waiting for the other SDK blocking move to finish.
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures={pool.submit(self.workers[a['arm']].execute):a['arm'] for a in group['actions']}
                    for future in as_completed(futures):
                        arm=futures[future]
                        try:result['arms'][arm]=future.result()
                        except Exception as exc:
                            self.stop.set();result['arms'][arm]={'status':'FAULT','error':str(exc)}
                    # Do not kill an in-flight worker or report that its command was cancelled.
            else:
                for index,action in enumerate(group['actions']):
                    arm=action['arm']
                    if self.stop.is_set():break
                    # First command may block for seconds. Refresh remaining arm preflight.
                    if index:
                        refreshed=self.workers[arm].refresh()
                        if refreshed['status']=='REJECTED_IK':result['arms'][arm]={'status':'REJECTED_IK'};break
                        if refreshed['status'] not in ('PASS_IK','NOT_REQUIRED'):raise RuntimeError('REFRESH_CHECK_FAULT')
                    try:result['arms'][arm]=self.workers[arm].execute()
                    except Exception as exc:
                        self.stop.set();result['arms'][arm]={'status':'FAULT','error':str(exc)};break
            if self.stop.is_set() or any(r['status']=='FAULT' for r in result['arms'].values()):
                result['status']='STOPPED';raise RuntimeError('GROUP_STOPPED_SEE_ARM_RESULTS')
            result['status']='REJECTED_IK' if any(r['status']=='REJECTED_IK' for r in result['arms'].values()) else 'COMPLETED'
            return result
        except Exception as exc:
            self.stop.set();result.update(status='STOPPED',error=str(exc));raise
        finally:
            result['elapsed_s']=time.monotonic()-start
            write_json(step/'group_result.json',result);self.active=False
