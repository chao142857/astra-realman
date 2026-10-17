"""Bounded measured transitions and separately labelled model judgments. No policy."""
import copy
from collections import deque
from gripper_telemetry import telemetry

RULES = ('History is oldest first, at most 8 completed transitions. Only CURRENT RGB images are attached; '
 'historical images are not supplied. measured contains controller readbacks, not object tracking. '
 'model_judgment contains prior model claims/intents, not established facts. Compare prior correction '
 'intent with what was actually executed. Opening reached and TCP lift do not prove object grasp. '
 'Grasp/contact/object-motion confirmation remains unknown without independent evidence. '
 'Each per-arm action executes TCP motion first, then gripper opening, with state readback between; '
 'to close before lifting, issue separate decisions. Sequential lists arms in order; parallel overlaps '
 'independent arms. Omitted arm holds. Position tolerance is 1 raw count out of 1000, not force control. '
 'dof_state=3 is force-control reached stop, not object grasp or device fault. A previous gripper target may remain active during arm motion even without a new gripper command. Missing telemetry is unknown. '
 'All targets and recovery choices remain yours; no automatic lift, route or grip target selection.')


def compact(s):
    return {k:copy.deepcopy(s.get(k)) for k in ('ee_pose','joint_deg','timestamp','system_error')} | {
        'opening_raw':s.get('gripper_state',{}).get('position'),
        'opening_speed_raw':telemetry(s.get('gripper_state',{}))['speed'],
        'gripper_telemetry':telemetry(s.get('gripper_state',{}))}


def transition(step, group, diagnostics, before, after, result):
    measured={}
    for arm,b in before.items():
        a=after.get(arm,{})
        xyz0=b.get('ee_pose',{}).get('xyz_m');xyz1=a.get('ee_pose',{}).get('xyz_m')
        receipt=result.get('arms',{}).get(arm,{})
        executed=receipt.get('executed_action',{})
        measured[arm]={'before':compact(b),'after':compact(a),
            'tcp_delta_m':[y-x for x,y in zip(xyz0,xyz1)] if xyz0 and xyz1 else None,
            'executed_commands':copy.deepcopy(executed),'status':receipt.get('status',result.get('status')),
            'error':receipt.get('error'),'gripper_after_evaluation':copy.deepcopy(receipt.get('gripper_after_evaluation')),'gripper_evaluation':copy.deepcopy(receipt.get('gripper_evaluation')),
            'between_channels':copy.deepcopy(receipt.get('between_channels')),
            'closure_tcp_xyz_m':copy.deepcopy(receipt.get('gripper_command_tcp_xyz_m')),
            'closure_position_note':'exact command-time readback when present; do not infer from proposal',
            'grasp_confirmed':'UNKNOWN','object_motion':'UNKNOWN'}
    return {'step':step,'proposed_action':copy.deepcopy(group),'model_judgment':copy.deepcopy(diagnostics),
            'measured':measured,'execution_status':result.get('status'),'failure':result.get('error'),
            'preflight_feedback':copy.deepcopy(result.get('preflight'))}


class ParallelHistory:
    def __init__(self):self.items=deque(maxlen=8);self.total=0
    def append(self,t):self.items.append(copy.deepcopy(t));self.total+=1
    def context(self):return {'version':'parallel_history_v1','capacity':8,'completed_count':self.total,
        'omitted_older_count':max(0,self.total-len(self.items)),'rules':RULES,'transitions':copy.deepcopy(list(self.items))}
