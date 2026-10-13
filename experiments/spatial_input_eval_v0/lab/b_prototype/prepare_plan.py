"""Freeze a future 36-client-request proposal, never authorizes or dispatches anything."""
import argparse,hashlib,json,time,shutil,tempfile
from pathlib import Path
SCENES=('p02_b_open_minus','p02_b_open_plus','p02_c_slot_030','p02_c_slot_120')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def prepare(module,evidence):
 suite=module/'evidence/pilot02_preview_20261013/suite_v2';broot=evidence/'inputs_B';entries={};timings=[]
 for scene in SCENES:
  entries[scene]={}
  a=read(suite/scene/'model_inputs/RGB_MULTI_VIEW/context.json')
  for label,folder in [('A',suite/scene/'model_inputs/RGB_MULTI_VIEW'),('B',broot/scene),('C',suite/scene/'model_inputs/RGB_ORACLE_3D')]:
   context=read(folder/'context.json');common=dict(context);common['geometry']=None;assert common==a
   images=[folder/f'image-{i}.png' for i in range(3)];assert [sha(x) for x in images]==[x['sha256'] for x in a['attachments']]
   entries[scene][label]={'context':str((folder/'context.json').relative_to(module)),'context_sha256':sha(folder/'context.json'),'rgb_sha256':[sha(x) for x in images],'context_utf8_bytes':(folder/'context.json').stat().st_size,'character_count_not_token_count':len((folder/'context.json').read_text())}
   t=time.perf_counter()
   with tempfile.TemporaryDirectory(prefix='b-input-prepare-') as tmp:
    for file in [folder/'context.json',*images]:shutil.copyfile(file,Path(tmp)/file.name)
    elapsed=time.perf_counter()-t
   timings.append({'scene':scene,'condition':label,'copy_existing_input_s':elapsed,'includes_reconstruction':False,'scope':'one warm-filesystem copy observation; not a model or full end-to-end run'})
 jobs=[]
 for repetition in range(3):
  for si,scene in enumerate(SCENES):
   order=['A','B','C'];shift=(repetition+si)%3;order=order[shift:]+order[:shift]
   for label in order:jobs.append({'order':len(jobs)+1,'scene':scene,'repeat':repetition+1,'condition':label,**entries[scene][label]})
 plan={'version':'abc_repeated_plan.v1','status':'OFFLINE_PROPOSAL_NOT_AUTHORIZED','real_generation_budget_now':0,'future_client_dispatches_if_separately_authorized':36,'scenes':list(SCENES),'repeats_per_scene_condition':3,'order_design':'fixed cyclic Latin positions per scene; all conditions occupy each within-triplet position once; deterministic, not randomized or fully carryover-balanced','jobs':jobs,'model':'gpt-6-astra','reasoning':'medium','client_deadline_s':180,'server_deadline_s':190,'workers':1,'ephemeral':True,'automatic_retries':0,'prompt_schema_task_policy':'identical to frozen Pilot02 A/C; geometry field only varies','scoring':'unchanged pilot02_contract.score; original protocol validity checks retained','failure_policy':'valid geometry failure scores zero and continues; protocol/transport/native top-level error/reconnect/timeout/drift stops; reserve before dispatch; never resume old ledgers','cache_recording':{'raw_usage':True,'input_tokens':True,'output_tokens':True,'reasoning_tokens':True,'cached_input_tokens':'record exact reported value; missing=null; no cache-busting prompt changes','analyses':['all valid new repeated pairs','secondary pairs excluding any reported cache hit','report unknown-cache rows separately']},'timing':{'end_to_end_start':'immediately before loading frozen public observations for this sample','end_to_end_end':'after response validity check, independent geometry scoring and archival','stages':['public input load','B-only reconstruction or A/C prepared-geometry load','context assembly and RGB copy','client request wall time','validation/scoring/archive'],'B_reconstruction':'run the frozen estimator separately for each B repetition; verify resulting geometry hash; no amortization against other requests','acquisition':'same historical sensor capture for all conditions; report original capture provenance separately; do not pretend cached replay measures live acquisition','offline_timings':'current measurements contain no model stage and are not future total latency'},'historical_results':'reference only; none counts as a new repeated sample','eligibility_note':'B v1 has documented false occupied space under floating rails and 5 mm footprint quantization vs 2 mm clearance. This proposal fixes all four scenes regardless of results. A future authorization must explicitly accept this prototype or freeze a separately versioned successor before any call. Do not tune v1 from GT diagnostics.','input_modality_note':'B uses depth unavailable to A. Compare practical RGB versus RGB-D derived geometry, not a pure representation-only causal effect. C geometry originates from simulator truth; missing visual geometry remains a confound to report.'}
 write(evidence/'future_abc_plan.json',plan);write(evidence/'input_preparation_timings.json',timings)
 write(evidence/'future_plan_hash.json',{'sha256':sha(evidence/'future_abc_plan.json'),'new_astra_requests':0})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--module',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args();prepare(a.module,a.evidence)
