"""Full task, versioned public chunk schema; existing Mac HTTP transport reused."""
import copy
import importlib.util
import json
from pathlib import Path
import action_interface as original
from full_handoff_task import INSTRUCTION as TASK_INSTRUCTION, POLICY
from numeric_action_chunk import SCHEMA,CONVENTIONS,parse_chunk

INSTRUCTION=TASK_INSTRUCTION.replace('done=false 时给出非空动作组；done=true 时 actions 必须为 []',
    'done=false 时给出非空 stages；done=true 时 stages 必须为 []')


def context_from_observation(obs,history):
    c,images=original.context_from_observation(obs,[])
    c.update(instruction=INSTRUCTION,task_policy=copy.deepcopy(POLICY),output_schema=copy.deepcopy(SCHEMA),
        conventions=copy.deepcopy(CONVENTIONS),recent_history=copy.deepcopy(history[-2:]))
    validate_context(c,images);return c,images


def validate_context(c,images):
    if c.get('instruction')!=INSTRUCTION or c.get('task_policy')!=POLICY or c.get('output_schema')!=SCHEMA or c.get('conventions')!=CONVENTIONS:
        raise ValueError('CHUNK_FULL_TASK_CONTRACT_CHANGED')
    # Reuse the original observation/image allowlist and hashing checks.
    check=copy.deepcopy(c);check.pop('task_policy');check.update(instruction=original.INSTRUCTION,
        output_schema=original.SCHEMA,conventions=original.CONVENTIONS,recent_history=[])
    original.validate_context(check,images)
    if len(c['recent_history'])>2:raise ValueError('HISTORY_BOUND')
    for row in c['recent_history']:
        if set(row)!={'proposal','receipt'}:raise ValueError('HISTORY_FIELDS')
        parse_chunk(json.dumps(row['proposal'],allow_nan=False))
    def private_fields(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k.lower() in {'ground_truth','oracle','witness','object_pose','object_velocity','contacts','expert_trajectory','target_grasp','bilateral_contact_at_end','latched'}:
                    raise ValueError('PRIVATE_FIELD:'+k)
                private_fields(v)
        elif isinstance(value,list):
            for v in value:private_fields(v)
    private_fields(c['recent_history'])


spec=importlib.util.spec_from_file_location('spatial_eval._chunk_handoff_transport',original.V0/'spatial_eval/mac_bridge.py')
transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)
transport.validate_context=validate_context
transport.parameter_audit=lambda r:original.full_command_audit(r.get('command'))


class ChunkAdapter(transport.MacBridgeAdapter):
    def __init__(self,config,*,offline_test=True):
        if offline_test and config.token_file.read_text().strip()!='full-task-mock-only':
            raise ValueError('OFFLINE_CHUNK_REQUIRES_SYNTHETIC_TOKEN')
        super().__init__(config,offline_test=offline_test,timeout_limit_s=180)

    def infer(self,context,images,folder,*,real=False,timeout_s=180):
        if real:
            reservation=getattr(self,'_reservation',None);self._reservation=None
            if self.offline_test or reservation is None or timeout_s!=180:
                raise ValueError('NEW_FULL_TASK_AUTHORIZATION_REQUIRED')
            gate,row=reservation
            if gate.state['status']!='READY' or row is not gate.state['runs'][-1] or row['status']!='RESERVED' or str(Path(folder).resolve().relative_to(gate.root))!=row['artifact']:
                raise ValueError('BOUND_FULL_TASK_RESERVATION_REQUIRED')
            import hashlib
            digest=hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
            if digest!=row['context_sha256'] or gate.hashes()!=gate.state['source_hashes']:
                raise ValueError('RESERVED_INPUT_OR_SOURCE_CHANGED')
        return super().infer(context,images,folder,real=real,timeout_s=timeout_s)


def accept_result(folder):return original.accept_result(folder,parser=parse_chunk)
