"""Official SAM3 on an explicit sealed real image. Never downloads weights.

A failed import or missing checkpoint is BLOCKED, never a synthetic mask result.
Supply --checkpoint only after access/license/download authorization is resolved.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time
from PIL import Image

def network_guard(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ['127.0.0.1','::1']:
        raise PermissionError('OFFLINE_SAM3_PROBE_NO_EXTERNAL_NETWORK')
sys.addaudithook(network_guard)

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--image',type=Path,required=True)
p.add_argument('--image-sha256',required=True)
p.add_argument('--checkpoint',type=Path)
p.add_argument('--source-lock',type=Path,default=Path(__file__).resolve().parents[1]/'sam3.lock.json')
p.add_argument('--checkpoint-sha256',default='9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e')
p.add_argument('--output',type=Path,required=True)
p.add_argument('--prompt',default='object')
a=p.parse_args()
a.output.resolve().relative_to(Path(__file__).resolve().parents[2])
result={'status':'BLOCKED','official_source_commit':'7f473cfd983d5eb43040ff608f66bff0d7bdcb53',
 'image':str(a.image.resolve()),'image_sha256':hashlib.sha256(a.image.read_bytes()).hexdigest(),
 'model':'facebook/sam3','weights_downloaded':False,'model_loaded':False,'segmentation_returned':False,
 'inference_latency_s':None,'peak_vram_allocated_bytes':None,'hardware_actions':0,'blockers':[],
 'python':sys.version,'environment':{}}
if result['image_sha256']!=a.image_sha256:
    raise SystemExit('REAL_IMAGE_HASH_MISMATCH')
with Image.open(a.image) as image:
    image.load()
    result['image_size']=list(image.size)
    image=image.convert('RGB')
for n in ['sam3','torch','torchvision','numpy','timm','ftfy','iopath','einops','decord','pycocotools','huggingface-hub']:
    try:result['environment'][n]=importlib.metadata.version(n)
    except importlib.metadata.PackageNotFoundError:result['environment'][n]=None
try:
    import torch
    result['torch_cuda_runtime']=torch.version.cuda
    result['cuda_available']=torch.cuda.is_available()
    if result['cuda_available']:
        result['gpu_name']=torch.cuda.get_device_name()
        result['gpu_total_memory_bytes']=torch.cuda.get_device_properties(0).total_memory
    import sam3
    package_root=Path(sam3.__file__).resolve().parent
    source_lock=json.loads(a.source_lock.read_text())
    for name,expected in source_lock['source_sha256'].items():
        file=package_root.parent/name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('OFFICIAL_SOURCE_HASH_MISMATCH:'+name)
    result['official_source_files_verified']=len(source_lock['source_sha256'])
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor
    result['official_import_ok']=True
except Exception as exc:
    result['official_import_ok']=False
    result['blockers'].append('OFFICIAL_IMPORT_FAILED:'+type(exc).__name__+':'+str(exc))
if not a.checkpoint or not a.checkpoint.is_file():
    result['blockers'].append('OFFICIAL_SAM3_CHECKPOINT_UNAVAILABLE; HF access gated; no automatic download')
else:
    with a.checkpoint.open('rb') as checkpoint_file:
        result['checkpoint_sha256']=hashlib.file_digest(checkpoint_file,'sha256').hexdigest()
    if result['checkpoint_sha256']!=a.checkpoint_sha256:
        result['blockers'].append('CHECKPOINT_HASH_MISMATCH')
if not result['blockers']:
    try:
        torch.cuda.reset_peak_memory_stats()
        started=time.perf_counter()
        model=build_sam3_image_model(checkpoint_path=str(a.checkpoint),load_from_HF=False,enable_inst_interactivity=True,device='cuda')
        processor=Sam3Processor(model,confidence_threshold=0.0)
        torch.cuda.synchronize();result['load_latency_s']=time.perf_counter()-started
        result['model_loaded']=True
        timings=[]
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            for _ in range(3):
                torch.cuda.synchronize();started=time.perf_counter()
                state=processor.set_image(image)
                output=processor.set_text_prompt(state=state,prompt=a.prompt)
                torch.cuda.synchronize();timings.append(time.perf_counter()-started)
        result.update(status='RAN',segmentation_returned=True,inference_latency_s=timings,
            peak_vram_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_vram_reserved_bytes=torch.cuda.max_memory_reserved(),
            mask_count=int(output['masks'].shape[0]),scores=output['scores'].detach().cpu().tolist())
    except Exception as exc:
        result['blockers'].append('OFFICIAL_INFERENCE_FAILED:'+type(exc).__name__+':'+str(exc))
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
raise SystemExit(result['status']!='RAN')
