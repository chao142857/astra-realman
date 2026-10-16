"""Receipt semantics only. No servo changes, object inference or injected motion."""
VERSION='rm65.gripper_state.v3'


def annotate(receipt):
    for row in receipt.get('gripper_execution',{}).values():
        established=bool(row['latched'] and row['bilateral_contact_at_end'])
        row.update(state_semantics_version=VERSION,command_execution='EXECUTED',
            contact_hold_state=('ESTABLISHED_AT_COMMAND_END' if established else
                'NOT_ESTABLISHED' if row['contact_mode']=='bilateral_hold' else 'NOT_REQUESTED'),
            stable_grasp='NOT_ASSESSED_BY_SERVO')
    if receipt.get('reason')=='GRIPPER_BILATERAL_HOLD_NOT_ESTABLISHED':
        # Keep the original false hold-condition result and raw contacts. It is
        # recoverable at the episode level, not permission to continue this chunk.
        receipt.update(failure_scope='REQUESTED_CONTACT_HOLD_CONDITION',
            recoverable_action_feedback=True,task_grasp_verdict='NOT_DETERMINED',
            requires_new_model_decision=True)
    return receipt
