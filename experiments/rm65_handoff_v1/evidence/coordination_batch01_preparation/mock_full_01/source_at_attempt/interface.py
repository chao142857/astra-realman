"""New task validator on the existing four-image transport and action schema."""
import copy
import importlib.util
import time
from pathlib import Path
import action_interface as original
from .contract import INSTRUCTION, validate_policy


def validate_context(context, images):
    if set(context) != {'instruction','conventions','output_schema','observations','recent_history','attachments','task_policy'}:
        raise ValueError('CAMPAIGN_PUBLIC_FIELDS')
    if context['instruction'] != INSTRUCTION or context['conventions'] != original.workspace_conventions():
        raise ValueError('CAMPAIGN_CONTRACT_CHANGED')
    validate_policy(context['task_policy'])
    # Delegate RGB, state/history allowlists, action schema and GT isolation to
    # the original validator; the task-specific policy was checked above.
    check=copy.deepcopy(context);check.pop('task_policy')
    check.update(instruction=original.INSTRUCTION,conventions=original.CONVENTIONS)
    original.validate_context(check,images)


def context_from_observation(obs,history,public):
    context,images=original.context_from_observation(obs,history)
    context.update(instruction=INSTRUCTION,conventions=original.workspace_conventions(),task_policy=copy.deepcopy(public))
    validate_context(context,images)
    return context,images


# Reuse the implementation file, not a copied HTTP implementation. Isolated
# module globals let the old and new task validators coexist unchanged.
spec=importlib.util.spec_from_file_location('spatial_eval._coordination_transport',original.V0/'spatial_eval/mac_bridge.py')
transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)
transport.validate_context=validate_context
transport.parameter_audit=lambda result:original.full_command_audit(result.get('command'))


class Adapter(transport.MacBridgeAdapter):
    def __init__(self,config,*,offline_test=False,deadline=None):
        super().__init__(config,offline_test=offline_test,timeout_limit_s=180)
        self.deadline=deadline
        self.reserved=False

    def _post(self,path,body,token,timeout_s):
        if path=='/decide' and self.deadline is not None:
            remaining=self.deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('CAMPAIGN_DEADLINE_NO_NEW_DISPATCH')
            timeout_s=min(timeout_s,remaining)
        # The existing transport cancels once on timeout. /cancel is cleanup,
        # not a generation or retry, and can take up to 3 s after the deadline.
        return super()._post(path,body,token,timeout_s)

    def infer(self,context,images,folder,*,real=False,timeout_s=180):
        if not self.reserved:raise ValueError('CAMPAIGN_ATOMIC_RESERVATION_REQUIRED')
        self.reserved=False
        if timeout_s!=180:raise ValueError('CLIENT_180_SECOND_CEILING_REQUIRED')
        return super().infer(context,images,folder,real=real,timeout_s=timeout_s)
