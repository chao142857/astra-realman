"""Pilot02 policy adapter and strict assessment, reusing the sealed V0 transport.

The original transport module is loaded into a private namespace, with its sole
validation function bound before use. No shared V0 global is patched, no HTTP code
is copied, and the original source and production bridge remain byte-identical.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from spatial_eval.schema import read, write, strict_json, parse_prediction, fields
from spatial_eval.mac_bridge import validate_context as v0_validate, MacBridgeConfig
from spatial_eval.inputs import load_snapshot
from pilot02_contract import validate_binding, score

MODULE=Path(__file__).resolve().parents[1]
REPO=MODULE.parents[1]
ORDER=MODULE/'evidence/pilot02_freeze_20261013/future_ac_order.json'
SEAL=MODULE/'evidence/pilot02_freeze_20261013/artifact_seal.json'
SEAL_SHA='420fab24dabff66ba9239d67308d8ddc643b96b39ae1c62b6742c41a99121828'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def verify_frozen():
    if sha(SEAL)!=SEAL_SHA:raise ValueError("FROZEN_SEAL_CHANGED")
    seal=read(SEAL)
    if sha(ORDER)!=seal['future_order_sha256']:raise ValueError('FROZEN_ORDER_CHANGED')
    for rel,digest in seal['entries'].items():
        # The seal contains no Pilot01 ledger; never open any historical ledger.
        if Path(rel).name=='ledger.json':raise ValueError('HISTORICAL_LEDGER_FORBIDDEN')
        if sha(REPO/rel)!=digest:raise ValueError('FROZEN_FILE_CHANGED:'+rel)
    order=read(ORDER)
    if len(order['ordered_samples'])!=20 or order['future_protocol']['concurrency']!=1 or order['future_protocol']['client_deadline_s']!=180:
        raise ValueError('FROZEN_PROTOCOL')
    return order

def job_input(job):
    folder=(MODULE/job['input_directory']).resolve()
    expected_root=(MODULE/'evidence/pilot02_preview_20261013/suite_v2').resolve()
    if not folder.is_relative_to(expected_root):raise ValueError('INPUT_DIRECTORY_SCOPE')
    context=read(folder/'context.json')
    if sha(folder/'context.json')!=job['context_sha256']:raise ValueError('FROZEN_CONTEXT_CHANGED')
    images=[folder/f'image-{i}.png' for i in range(3)]
    if [sha(p) for p in images]!=job['rgb_sha256']:raise ValueError('FROZEN_RGB_CHANGED')
    scene=folder.parent.parent
    snapshot=load_snapshot(scene/'snapshot.json');task=snapshot['task'][0];policy=read(scene/'task_policy.json')
    if context['task']!=task or context.get('task_policy')!=policy:raise ValueError('FROZEN_TASK_POLICY_CHANGED')
    validate_public(context,images)
    return context,images,snapshot,task,policy

def validate_public(context,images):
    fields(context,['instruction','coordinate_system','task','output_schema','attachments','observations','geometry','task_policy'])
    validate_binding(context['task'],context['task_policy'])
    base=copy.deepcopy(context);base.pop('task_policy');v0_validate(base,images)

# Load identical source under a private package namespace: relative imports work,
# while V0 clients keep their own strict seven-field validator unchanged.
_transport_path=MODULE/'spatial_eval/mac_bridge.py'
_spec=importlib.util.spec_from_file_location('spatial_eval._pilot02_transport',_transport_path)
_transport=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_transport)
_transport.validate_context=validate_public

class Pilot02MacBridgeAdapter(_transport.MacBridgeAdapter):
    def __init__(self,config,job,*,offline_test=False):
        verify_frozen()
        self.job=copy.deepcopy(job)
        official=read(ORDER)['ordered_samples']
        if job not in official:raise ValueError('UNFROZEN_JOB')
        self.expected,self.expected_images,*_=job_input(job)
        super().__init__(config,offline_test=offline_test,timeout_limit_s=180)

    def infer(self,context,images,folder,*,real=False,timeout_s=180):
        # Real calls are made only through the budgeted dispatcher; the adapter
        # requires a one-use reservation capability rather than a boolean alone.
        if real and not getattr(self,'_reserved_dispatch',False):raise ValueError('DISPATCH_RESERVATION_REQUIRED')
        if real and timeout_s!=180:raise ValueError('REAL_DEADLINE_MUST_BE_180')
        verify_frozen()
        validate_public(context,images)
        if context!=self.expected or [sha(p) for p in images]!=self.job['rgb_sha256']:
            raise ValueError('FROZEN_PAYLOAD_CHANGED')
        self._reserved_dispatch=False
        return super().infer(context,images,folder,real=real,timeout_s=timeout_s)


def bridge_module():
    path=REPO/'astra_realman_harness/scripts/codex_astra_mac_bridge.py'
    if str(path.parent.parent) not in sys.path:sys.path.insert(0,str(path.parent.parent))
    spec=importlib.util.spec_from_file_location('_p02_command_only',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def full_command_audit(command):
    if not isinstance(command,list):return False
    try:
        inp=Path(command[command.index('--cd')+1])
        if inp.name!='input_only':return False
        expected=bridge_module().command(inp.parent,[inp/f'image-{i}.png' for i in range(3)])
        return command==expected
    except (ValueError,IndexError,TypeError):return False


def assess(folder,job):
    """Reopen archived raw/transport; invalid infrastructure never becomes score 0."""
    folder=Path(folder);context,images,snapshot,task,policy=job_input(job)
    result={'status':'NOT_SCORED','score':None,'failure':None,'source':None,'usage':None,'latency_s':None}
    try:
        response=read(folder/'response.json');transport=read(folder/'transport.json');wire=read(folder/'bridge_request.json')
        result.update(source=response['source'],latency_s=response.get('wall_latency_s'),usage=response.get('usage'),usage_kind=response.get('usage_status'))
        if wire['context']!=context:raise ValueError('ARCHIVED_CONTEXT_MISMATCH')
        import base64
        if [hashlib.sha256(base64.b64decode(b,validate=True)).hexdigest() for b in wire['images']]!=job['rgb_sha256']:
            raise ValueError('ARCHIVED_RGB_MISMATCH')
        bridge_module().validate_payload(wire)
        if wire['authoritative_schema']!=context['output_schema']:raise ValueError('ARCHIVED_SCHEMA_MISMATCH')
        if transport.get('http_status')!=200 or transport.get('dispatch_attempts')!=1 or transport.get('retries')!=0 or transport.get('cancel_attempts')!=0:
            raise ValueError('TRANSPORT_FAILURE_OR_UNKNOWN')
        if type(response.get('return_code')) is not int or response['return_code']!=0 or response.get('error') is not None:
            raise ValueError('REMOTE_ERROR')
        if transport.get('request_id')!=wire.get('request_id'):raise ValueError('REQUEST_ID_MISMATCH')
        if response['source']=='REAL_ASTRA_ATTEMPT' and transport.get('timeout_s')!=180:raise ValueError('DEADLINE_DRIFT')
        original=read(folder/'bridge_result.json')
        if original.get('return_code')!=response['return_code'] or original.get('error')!=response['error']:
            raise ValueError('REMOTE_RECEIPT_MISMATCH')
        if transport.get('remote_model_parameter_audit')!='PASS' or not full_command_audit(original.get('command')):
            raise ValueError('MODEL_OR_CODE_MODE_DRIFT')
        raw=(folder/'raw.txt').read_text();events=(folder/'events.jsonl').read_text()
        if raw!=response['raw'] or events!=response['events'] or raw!=original['raw'] or events!=original['events']:
            raise ValueError('ARCHIVE_INCONSISTENT')
        if not raw.strip():raise ValueError('EMPTY_OUTPUT')
        rows=[strict_json(line) for line in events.splitlines() if line.strip()]
        if any(not isinstance(r,dict) for r in rows):raise ValueError('EVENT_OBJECT_REQUIRED')
        completed=[r for r in rows if r.get('type')=='turn.completed']
        starts=[r for r in rows if r.get('type')=='thread.started']
        if len(completed)!=1 or len(starts)!=1 or any(r.get('type') in ('turn.failed','error') for r in rows):
            raise ValueError('COMPLETION_NOT_CONFIRMED')
        thread=starts[0].get('thread_id')
        if not isinstance(thread,str) or not thread:raise ValueError('THREAD_ID_REQUIRED')
        usage=completed[0].get('usage')
        if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('input_tokens','output_tokens')):
            raise ValueError('USAGE_MISSING_OR_INVALID')
        prediction=parse_prediction(raw,task)
        evaluated=score(snapshot,task,prediction,policy)
        if evaluated['status']!='SCORED':raise ValueError('GT_UNAVAILABLE')
        result.update(status='VALID',score=evaluated['score'],evaluation=evaluated,thread_id=thread,usage=usage,
                      usage_kind='FIXTURE_NOT_MODEL_USAGE' if response['source'].startswith('FAKE') else 'CLI_REPORTED',
                      input_sha256=job['context_sha256'],raw_sha256=sha(folder/'raw.txt'),model_parameters={'model':'gpt-6-astra','reasoning':'medium','ephemeral':True})
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result['failure']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
    return result


def record_and_rescore(folder,job):
    folder=Path(folder);first=assess(folder,job);write(folder/'assessment.json',first)
    # Independent reread/strict parse/scoring, not copying the first evaluation.
    second=assess(folder,job);write(folder/'independent_rescore.json',second)
    if first!=second:raise ValueError('INDEPENDENT_RESCORE_MISMATCH')
    return first
