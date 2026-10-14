"""New study binding of the unchanged Pilot02 transport, acceptance and scorer."""
import copy,importlib.util,json,re
from pathlib import Path
from spatial_eval.schema import read,write
from astra_ac.verify import verify
M=Path(__file__).resolve().parents[2];PLAN=M/'evidence/astra_ac_plan_20261014';ORDER=PLAN/'future_ac_order.json'
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
r=module('_astra_ac_original_runtime',M/'lab/pilot02_runtime.py')
sha=r.sha
RELEASE_SHA=sha(PLAN/'release_manifest.json')  # checked against immutable literal below
EXPECTED_RELEASE_SHA='ca1924a33a93c4133c4bb4cad93af91cccb3f4f09929108100bf558c26a8db1e'
def frozen():
 if sha(PLAN/'release_manifest.json')!=EXPECTED_RELEASE_SHA:raise ValueError('AC_RELEASE_CHANGED')
 verify(PLAN);return read(ORDER)
def job_input(job):
 if job not in read(ORDER)['ordered_samples']:raise ValueError('UNFROZEN_AC_JOB')
 folder=(PLAN/job['input_directory']).resolve()
 if not folder.is_relative_to(PLAN/'inputs'):raise ValueError('AC_INPUT_SCOPE')
 context=read(folder/'context.json');images=[folder/f'image-{i}.png' for i in range(3)]
 if sha(folder/'context.json')!=job['context_sha256'] or [sha(p) for p in images]!=job['rgb_sha256']:raise ValueError('AC_INPUT_CHANGED')
 row=next(x for x in read(PLAN/'task_catalog.json') if x['scene']==job['scene']);snapshot_path=M/row['private_snapshot']
 if sha(snapshot_path)!=row['snapshot_sha256']:raise ValueError('AC_GT_CHANGED')
 snapshot=read(snapshot_path);task=snapshot['task'][0];policy=read(snapshot_path.parent/'task_policy.json')
 if context['task']!=task or context['task_policy']!=policy:raise ValueError('AC_TASK_POLICY_CHANGED')
 r.validate_public(context,images);return context,images,snapshot,task,policy
# Only the private module's study bindings change. Its HTTP/event/scoring source is identical.
r.ORDER=ORDER;r.verify_frozen=frozen;r.job_input=job_input
original_assess=r.assess
def assess(folder,job):
 result=original_assess(folder,job)
 if result['status']=='VALID':
  response=read(Path(folder)/'response.json');events=response['events'];stderr=response.get('stderr','')
  # Top-level error/turn.failed is already rejected by original acceptance.
  # Also reject reconnect diagnostics even if a final completed event follows.
  diagnostics=[]
  for line in events.splitlines():
   event=json.loads(line)
   if event.get('type') in ('error','turn.failed') or 'reconnect' in str(event.get('type','')).lower():diagnostics.append(event)
   if event.get('type') not in ('item.completed','item.updated','item.started') and re.search(r'\breconnect(?:ing|ed|ion)?\b',json.dumps(event),re.I):diagnostics.append(event)
  if diagnostics or re.search(r'\breconnect(?:ing|ed|ion)?\b',stderr,re.I):
   result.update(status='NOT_SCORED',score=None,failure='NATIVE_CLI_ERROR_OR_RECONNECT');result.pop('evaluation',None)
  transport=read(Path(folder)/'transport.json');result['request_id']=transport['request_id']
  usage=result.get('usage') or {};details=usage.get('output_tokens_details') or {};inp=usage.get('input_tokens_details') or {}
  result['reported_reasoning_tokens']=details.get('reasoning_tokens',usage.get('reasoning_output_tokens'))
  result['cached_input_tokens']=usage.get('cached_input_tokens',inp.get('cached_tokens'))
  result['upstream_generation_attempts']='NOT_MEASURED; distinct from client dispatch and CLI reconnect diagnostics'
 return result
r.assess=assess
Adapter=r.Pilot02MacBridgeAdapter
MacBridgeConfig=r.MacBridgeConfig
record_and_rescore=r.record_and_rescore
# Reuse original cancellation and archive lifecycle, isolated from historical globals.
b=module('_astra_ac_original_dispatcher',M/'lab/pilot02_dispatcher.py')
b.job_input=job_input;b.Pilot02MacBridgeAdapter=Adapter;b.record_and_rescore=record_and_rescore
perform=b.perform;save=b.save;now=b.now;lock=b.lock
