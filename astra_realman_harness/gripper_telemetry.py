"""Lossless first-DOF readback projection; no inference of object contact."""
import math

def telemetry(g):
    raw=g.get('raw') or {}
    def scalar(key):
        value=raw.get(key)
        return value[0] if isinstance(value,(list,tuple)) and value else None
    values={k:scalar(k) for k in ('dof_state','dof_err','current','speed')}
    values.update(position=g.get('position'),sys_state=raw.get('sys_state'))
    valid={k:type(v) in (int,float) and math.isfinite(v) for k,v in values.items()}
    state=values['dof_state']
    return {**values,'validity':valid,'captured_at':g.get('captured_at'),
        'sdk_return_code':g.get('sdk_return_code'),
        'validity_scope':'field present and finite; not sensor calibration or object confirmation',
        'stop_reason':'力控到位停止' if valid['dof_state'] and state==3 else 'UNKNOWN_OTHER_STATE',
        'state_interpretation_source':'device protocol state 3 confirmed by operator; other enum values not inferred',
        'current_units':'raw SDK units; not calibrated force or torque',
        'grasp_confirmed':'UNKNOWN'}
