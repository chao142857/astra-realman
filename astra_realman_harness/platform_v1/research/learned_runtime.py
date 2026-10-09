"""Host-only, explicit learned-worker mounts. Never accept this config over policy RPC."""
import hashlib
import json
import subprocess
from pathlib import Path

def validate_config(config):
    required={'backend','venv','weights','weights_sha256','config_sha256','device','process_res','timeout_s','source_revision'}
    if set(config)!=required or config['backend']!='da3_small_v1': raise ValueError('LEARNED_CONFIG_FIELDS')
    venv=Path(config['venv']).resolve();weights=Path(config['weights']).resolve()
    if not (venv/'bin/python').is_file() or not (venv/'pyvenv.cfg').is_file(): raise ValueError('LEARNED_VENV_MISSING')
    check=subprocess.run([str(venv/'bin/python'),'-I','-c',
        "import importlib.util,json; print(json.dumps({n:bool(importlib.util.find_spec(n)) for n in ('torch','depth_anything_3','safetensors','huggingface_hub','numpy','scipy','PIL')}))"],
        capture_output=True,text=True,timeout=10)
    if check.returncode or not all(json.loads(check.stdout).values()): raise ValueError('LEARNED_DEPENDENCIES_MISSING')
    if config['device']!='cuda:0' or config['process_res'] not in (252,336,504): raise ValueError('LEARNED_DEVICE_OR_RESOLUTION')
    if type(config['timeout_s']) not in (int,float) or not 1<=config['timeout_s']<=90: raise ValueError('LEARNED_TIMEOUT')
    for name,key in [('model.safetensors','weights_sha256'),('config.json','config_sha256')]:
        path=weights/name
        if not path.is_file(): raise ValueError('LEARNED_WEIGHTS_MISSING')
        if path.resolve().parent!=weights: raise ValueError('LEARNED_WEIGHTS_SYMLINK')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=config[key]: raise ValueError('LEARNED_WEIGHTS_HASH')
    model_config=json.loads((weights/'config.json').read_text())
    if model_config.get('model_name')!='da3-small': raise ValueError('DA3_SMALL_CONFIG_REQUIRED')
    if len(config['source_revision'])!=40 or any(c not in '0123456789abcdef' for c in config['source_revision']):
        raise ValueError('PIN_DA3_SOURCE_REVISION')
    devices=[Path('/dev/nvidia0'),Path('/dev/nvidiactl'),Path('/dev/nvidia-uvm')]
    if any(not p.exists() for p in devices): raise ValueError('CUDA_DEVICES_UNAVAILABLE')
    return venv,weights,devices

def sandbox_parts(config):
    venv,weights,devices=validate_config(config)
    # Remap to a neutral path: binding a host workspace path would expose its
    # ancestor and correctly trip the worker's private-workspace assertion.
    args=['--ro-bind',str(venv),'/lwh-venv','--ro-bind',str(weights),'/weights']
    for device in devices: args+=['--dev-bind',str(device),str(device)]
    if Path('/etc/ld.so.cache').exists(): args+=['--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache']
    return args,'/lwh-venv/bin/python'
