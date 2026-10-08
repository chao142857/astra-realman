"""Independent private-trace assessment. Never imported by policy/wire workers."""
import math


def assess_grasp(rows, initial_z, closure=None, *, stopped=False):
    """Closing and contacts alone never establish stable carrying.

    Reuses the existing independent score's 50mm lift, 300-step hold and
    30mm relative-slip limits; requires bilateral contact on every hold sample.
    Does not generate targets, affect controller drives or reclassify old runs.
    """
    run=best=0;minimum=None;window=[];reference=None;previous=None
    for r in rows:
        lift=r['object_pose'][2]-initial_z
        valid=r['closed'] and r['bilateral_contact'] and math.isfinite(lift) and lift>=.05
        relative=[a-b for a,b in zip(r['object_pose'][:3],r['grasp_center'])]
        if previous is not None and r['step']!=previous+1:run=0;window=[];reference=None
        previous=r['step']
        if valid:
            if reference is None:reference=relative
            valid=sum((a-b)**2 for a,b in zip(relative,reference))<=.03**2
        if valid:
            run+=1;window.append(lift)
            if run>best:best=run;minimum=min(window)
        else:run=0;window=[];reference=None
    qualified=bool(closure and closure.get('contact_qualified'))
    failed=stopped or bool(closure and closure.get('grasp_failed'))
    status=('GRASP_FAILED' if failed else 'STABLE_HOLD_VERIFIED' if best>=300 else
            'CONTACT_CONFIRMED_HOLD_NOT_VERIFIED' if qualified else 'NOT_ESTABLISHED')
    return {'source':'INDEPENDENT_PRIVATE_TRACE_NOT_POLICY_INPUT','status':status,
        'close_command_completed':closure.get('command_completed') if closure else None,
        'contact_qualified_after_close':qualified,'stable_hold_seen':best>=300,
        'longest_bilateral_hold_above_50mm_steps':best,'minimum_lift_in_longest_hold_m':minimum,
        'full_pick_place_success':'NOT_DETERMINED_BY_THIS_ASSESSMENT'}
