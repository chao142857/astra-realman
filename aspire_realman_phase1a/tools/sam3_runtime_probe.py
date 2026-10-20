"""Official imports + CUDA prerequisite smoke only; never reports model VRAM."""
import importlib.metadata as m,json,hashlib,subprocess,sys,time
from pathlib import Path
import sysconfig
def network_guard(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ['127.0.0.1','::1']:
        raise PermissionError('OFFLINE_SAM3_PROBE_NO_EXTERNAL_NETWORK')
sys.addaudithook(network_guard)

ROOT=Path(__file__).resolve().parents[2]
result={'scope':'official imports and small BF16 CUDA matmul only; not SAM3 inference',
    'python':sys.version,'official_source_commit':'7f473cfd983d5eb43040ff608f66bff0d7bdcb53',
    'official_import_ok':False,'cuda_smoke_ok':False,'model_loaded':False,'model_peak_vram_bytes':None,
    'model_inference_latency_s':None,'errors':[]}
try:
    import sam3
    lock=json.loads((ROOT/'aspire_realman_phase1a/sam3.lock.json').read_text())
    base=Path(sam3.__file__).resolve().parent.parent
    for name,expected in lock['source_sha256'].items():
        p=base/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('OFFICIAL_PACKAGE_SOURCE_MISMATCH:'+name)
    result['official_source_files_verified']=len(lock['source_sha256'])
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor
    result['official_import_ok']=True
except Exception as exc:result['errors'].append('IMPORT:'+type(exc).__name__+':'+str(exc))
try:
    import torch
    result['torch_version']=torch.__version__;result['torch_cuda_runtime']=torch.version.cuda
    result['cuda_available']=torch.cuda.is_available()
    result['nvidia_smi']=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used','--format=csv'],text=True).strip()
    if torch.cuda.is_available():
        result['device_capability']=torch.cuda.get_device_capability(0)
        result['bf16_supported']=torch.cuda.is_bf16_supported()
        result['memory_free_total_bytes']=list(torch.cuda.mem_get_info())
        torch.cuda.reset_peak_memory_stats()
        started=time.perf_counter()
        a=torch.ones((64,64),device='cuda',dtype=torch.bfloat16); b=a@a
        torch.cuda.synchronize()
        assert torch.all(b==64).item()
        result['cuda_smoke_ok']=True;result['smoke_latency_s']=time.perf_counter()-started
        result['smoke_peak_vram_bytes']=torch.cuda.max_memory_allocated()
except Exception as exc:result['errors'].append('CUDA_SMOKE:'+type(exc).__name__+':'+str(exc))
result['status']='READY_FOR_CHECKPOINT' if result['official_import_ok'] and result['cuda_smoke_ok'] else 'BLOCKED'
site_root=Path(sysconfig.get_paths()['purelib']).resolve()
result['environment']={dist.metadata['Name']:dist.version for dist in m.distributions() if Path(dist.locate_file('')).resolve()==site_root}
check=subprocess.run([sys.executable,'-m','pip','check'],capture_output=True,text=True)
result['pip_check']={'exit_code':check.returncode,'stdout':check.stdout.strip(),'stderr':check.stderr.strip()}
if check.returncode:
    result['status']='IMPORT_AND_CUDA_PASS_WITH_DEPENDENCY_WARNING' if result['official_import_ok'] and result['cuda_smoke_ok'] else 'BLOCKED'
p=ROOT/'evidence/sam3-runtime-probe.json';p.write_text(json.dumps(result,indent=2));print(p.read_text())

raise SystemExit(result['status']=='BLOCKED')
