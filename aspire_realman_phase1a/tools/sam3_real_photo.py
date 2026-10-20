"""Real sealed-photo SAM3 inference; completion, candidates, and recognition differ.
Requires an inspected-image prompt. Never auto-download weights or synthesize masks.
"""
import argparse,hashlib,importlib.metadata,json,sys,time,traceback
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'aspire_realman_phase1b/tools'))
from rgbd_evidence import load_snapshot
from sam3_results import save_predictions


def guard(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ['127.0.0.1','::1']:
        raise PermissionError('OFFLINE_SAM3_NO_EXTERNAL_NETWORK_OR_ROBOT_ENDPOINTS')
sys.addaudithook(guard)
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--image',type=Path,required=True);p.add_argument('--image-sha256',required=True)
p.add_argument('--snapshot',type=Path);p.add_argument('--checkpoint',type=Path)
p.add_argument('--source-lock',type=Path,default=Path(__file__).resolve().parents[1]/'sam3.lock.json')
p.add_argument('--output',type=Path,required=True)
p.add_argument('--prompt',required=True,help='Named visible target selected after inspecting the source image')
p.add_argument('--prompt-evidence',required=True,help='Why this target is visibly present; not generic object')
p.add_argument('--score-threshold',type=float,default=.5)
p.add_argument('--native-http',action='store_true');p.add_argument('--aspire-source',type=Path,default=ROOT/'.cache/ASPIRE')
a=p.parse_args()
if not a.prompt.strip() or a.prompt.strip().lower()=='object' or not a.prompt_evidence.strip():p.error('INSPECTED_TARGET_PROMPT_AND_EVIDENCE_REQUIRED')
if not 0<=a.score_threshold<=1:p.error('score threshold must be 0..1')
a.output=a.output.resolve();a.output.relative_to(ROOT);a.output.parent.mkdir(parents=True,exist_ok=True)
if a.output.exists():raise SystemExit('NEW_OUTPUT_REQUIRED_PRESERVE_PRIOR_EVIDENCE')
assets=a.output.with_suffix('');assets.mkdir(exist_ok=False)
rgb,z,meta,provenance=load_snapshot(a.snapshot or a.image.parent/'snapshot.json')
if a.image.resolve()!=Path(meta['assets']['rgb.png']['path']).resolve() or a.image_sha256!=provenance['rgb_sha256']:
    raise SystemExit('SOURCE_IMAGE_NOT_MATCHED_TO_SEALED_RGBD')
result={'status':'BLOCKED','official_source_commit':'7f473cfd983d5eb43040ff608f66bff0d7bdcb53',
    'provenance':provenance,'prompt':a.prompt,'prompt_evidence':a.prompt_evidence,
    'score_threshold':a.score_threshold,'inference_completed':False,'mask_count':None,
    'target_candidates_present':False,'target_identification_success':False,'visual_validation':'NOT_RUN',
    'model_loaded':False,'model_load_time_s':None,'runs':[],'peak_vram_allocated_bytes':None,
    'peak_vram_reserved_bytes':None,'world_pose':None,'hardware_actions':0,'blockers':[]}
model=processor=torch=None
try:
    lock=json.loads(a.source_lock.read_text())
    if not a.checkpoint or not a.checkpoint.is_file():
        result['blockers'].append('AUTHORIZED_OFFICIAL_CHECKPOINT_PATH_UNAVAILABLE')
    else:
        with a.checkpoint.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        result['checkpoint']={'path':str(a.checkpoint.resolve()),'sha256':digest}
        if digest!=lock['checkpoint_sha256']:result['blockers'].append('OFFICIAL_CHECKPOINT_HASH_MISMATCH')
    import torch,sam3
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor
    package=Path(sam3.__file__).resolve().parent.parent
    for name,expected in lock['source_sha256'].items():
        if hashlib.sha256((package/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('OFFICIAL_SOURCE_HASH_MISMATCH:'+name)
    result['official_source_files_verified']=len(lock['source_sha256'])
    result['environment']={n:importlib.metadata.version(n) for n in ['sam3','torch','torchvision','numpy']}
    result['official_import_ok']=True;result['cuda_available']=torch.cuda.is_available()
    result['torch_cuda_runtime']=torch.version.cuda
    if result['cuda_available']:
        result['gpu_name']=torch.cuda.get_device_name()
        result['gpu_total_memory_bytes']=torch.cuda.get_device_properties(0).total_memory
    sys.path[:0]=[str(a.aspire_source/'src'),str(ROOT/'aspire_realman_phase05/tests')]
    if not result['blockers']:
        if not torch.cuda.is_available():raise RuntimeError('CUDA_UNAVAILABLE')
        torch.cuda.reset_peak_memory_stats();started=time.perf_counter()
        try:
            model=build_sam3_image_model(checkpoint_path=str(a.checkpoint),load_from_HF=False,enable_inst_interactivity=True,device='cuda')
            processor=Sam3Processor(model,device='cuda',confidence_threshold=0.0)
            torch.cuda.synchronize();result['model_loaded']=True
        finally:result['model_load_time_s']=time.perf_counter()-started
        from PIL import Image
        for i in range(3):
            torch.cuda.synchronize();started=time.perf_counter()
            with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                state=processor.set_image(Image.fromarray(rgb));output=processor.set_text_prompt(state=state,prompt=a.prompt)
            torch.cuda.synchronize();elapsed=time.perf_counter()-started
            to_np=lambda t:t.detach().float().cpu().numpy()
            row=save_predictions(to_np(output['masks']),to_np(output['boxes']),to_np(output['scores']),
                rgb,z,meta,assets,f'official-run{i+1}',a.score_threshold,geometry=i==2)
            row.update(run=i+1,kind='cold_first_call' if i==0 else 'warm_call',inference_latency_s=elapsed)
            result['runs'].append(row)
            # Saved predictions are CPU data. Do not retain an old image feature
            # state while encoding the next image or entering the native service.
            del state,output
        result.update({k:result['runs'][-1][k] for k in ['status','inference_completed','mask_count','target_candidates_present','target_identification_success','visual_validation']})
except Exception as exc:
    result['status']='FAILED_REAL_RUNTIME' if result['model_load_time_s'] is not None else 'BLOCKED'
    result['blockers'].append(type(exc).__name__+':'+str(exc));result['real_error_traceback']=traceback.format_exc()
finally:
    if torch is not None and result['model_load_time_s'] is not None:
        try:
            result['peak_vram_allocated_bytes']=torch.cuda.max_memory_allocated()
            result['peak_vram_reserved_bytes']=torch.cuda.max_memory_reserved()
            result['official_peak_vram_allocated_bytes']=result['peak_vram_allocated_bytes']
            result['official_peak_vram_reserved_bytes']=result['peak_vram_reserved_bytes']
        except Exception as exc:result['vram_query_error']=str(exc)
if a.native_http and result['status']=='FAILED_REAL_RUNTIME':
    result['native_http']={'status':'SKIPPED_AFTER_REAL_RUNTIME_FAILURE',
        'reason':'Preserve first real runtime error; no repeated model attempts after OOM/CUDA/PTX failure'}
elif a.native_http:
    try:
        from native_sam3_photo import probe_native
        result['native_http']=probe_native(model,processor,rgb,z,meta,assets,a.prompt,a.score_threshold)
        for field in ['peak_vram_allocated_bytes','peak_vram_reserved_bytes']:
            native_peak=result['native_http'].get(field)
            if native_peak is not None:result[field]=max(result[field] or 0,native_peak)
        if result['runs'] and result['native_http']['calls'][-1].get('predictions'):
            direct=result['runs'][-1]['predictions'];native=result['native_http']['calls'][-1]['predictions']
            from PIL import Image
            compare=[]
            for d,n in zip(direct,native):
                dm=np.array(Image.open(d['mask']['path']))>0;nm=np.array(Image.open(n['mask']['path']))>0
                union=np.count_nonzero(dm|nm)
                compare.append({'direct_rank':d['rank'],'native_rank':n['rank'],'iou':float(np.count_nonzero(dm&nm)/union) if union else None,
                                'score_abs_diff':abs(d['score']-n['score'])})
            result['official_vs_native_top5_comparison']=compare
    except Exception as exc:result['native_http_error']={'error':type(exc).__name__+':'+str(exc),'traceback':traceback.format_exc()}
a.output.write_text(json.dumps(result,indent=2,allow_nan=False))
print(json.dumps({'output':str(a.output),'status':result['status'],'mask_count':result['mask_count'],
    'inference_completed':result['inference_completed'],'target_identification_success':result['target_identification_success'],
    'blockers':result['blockers'],'native_http_status':result.get('native_http',{}).get('status')},indent=2))
raise SystemExit(not result['inference_completed'])
