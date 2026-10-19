"""Read-only host audit: run via ssh ... python3 -B - < this_file.
No SDK import, socket connection to robots, camera open, service or environment writes.
"""
import datetime, glob, hashlib, json, os, pathlib, re, subprocess
P=pathlib.Path
ROOTS=[P('/home/tongji/alex/astra_onsite_1011'),P('/home/tongji/alex/realman-chunk-gui-migration-20261017')]
def cmd(args):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=25)
    return {'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
def meta(p):
    p=P(p)
    try:
        b=p.read_bytes()
        return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    except (OSError,ValueError) as e:return {'path':str(p),'error':str(e)}
a={'timestamp':datetime.datetime.now().astimezone().isoformat(),'hostname':cmd(['hostname']), 'method':'filesystem/proc/sysfs/git/nvidia-smi only; no SDK/camera/model initialization','repos':{},'processes':[],'cameras_sysfs':[],'python_environments':{}}
for root in ROOTS:
    a['repos'][str(root)]={k:cmd(['git','--no-optional-locks','-C',str(root)]+v) for k,v in {'head':['rev-parse','HEAD'],'status':['status','--short','--branch'],'remote':['remote','-v']}.items()}
for p in P('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        argv=(p/'cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]
        if not argv or not re.search('python|astra|realsense|uvicorn|robot|camera|sam3|curobo|ollama|vllm', ' '.join(argv),re.I):continue
        if any(x in ' '.join(argv) for x in ['audit_remote.py','python3 -B -','ss -ltnp']):continue
        # Never preserve credentials or inline shell/python script contents.
        if os.path.basename(argv[0]) in ['bash','sh','ssh','timeout']:argv=argv[:1]+['<arguments omitted>']
        argv=[re.sub(r'(?i)((token|secret|password|api.key)=)[^\s]+',r'\1<redacted>',x) for x in argv]
        for i,x in enumerate(argv[:-1]):
            if re.search('token|password|secret|api.key',x,re.I):argv[i+1]='<redacted>'
        fds=[]
        for f in (p/'fd').iterdir():
            try:
                dst=os.readlink(str(f))
                if dst.startswith('/dev/video') or dst.startswith('/dev/bus/usb/'):fds.append(dst)
            except OSError:pass
        a['processes'].append({'pid':int(p.name),'argv':argv,'cwd':os.readlink(str(p/'cwd')),'device_fds':sorted(set(fds))})
    except (OSError,PermissionError):pass
for v in sorted(P('/sys/class/video4linux').glob('video*')):
    def read(n):
        try:return (v/n).read_text().strip()
        except OSError:return None
    a['cameras_sysfs'].append({'device':'/dev/'+v.name,'name':read('name'),'sysfs':str(v.resolve())})
a['usb_camera_devices']=[]
for p in P('/sys/bus/usb/devices').glob('*'):
    try:
        if (p/'idVendor').read_text().strip()=='8086':
            a['usb_camera_devices'].append({k:(p/k).read_text().strip() for k in ['idVendor','idProduct','serial','product'] if (p/k).exists()})
    except OSError:pass
for py in ['/usr/bin/python3','/home/tongji/miniconda3/bin/python']+glob.glob('/home/tongji/miniconda3/envs/*/bin/python'):
    if not P(py).exists():continue
    code="import sys,json,importlib.metadata as m; wanted=['torch','numpy','scipy','opencv-python','pyrealsense2','mcp','curobo','sam3','mujoco','fastapi','uvicorn','pydantic']; ds={d.metadata.get('Name','').lower().replace('_','-'):d.version for d in m.distributions()}; print(json.dumps({'python':sys.version,'executable':sys.executable,'packages':{k:ds.get(k) for k in wanted}}))"
    a['python_environments'][py]=cmd([py,'-I','-B','-c',code])
for k,v in {'gpu':['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used','--format=csv'],'cuda':['nvidia-smi'],'listeners':['ss','-ltnp'],'video_owners':['fuser']+glob.glob('/dev/video*')}.items():
    try:a[k]=cmd(v)
    except (OSError,subprocess.TimeoutExpired) as e:a[k]={'error':str(e)}
a['cuda_toolkits']=[str(p) for p in P('/usr/local').glob('cuda*')]
a['source_fingerprints']=[]
files=['realman_api2_readonly.py','arm_stack.py','arm_worker.py','left_executor.py','lab_gripper_adapter.py','gripper_telemetry.py','onsite_sequence.py','real_calibration_status.py','lab_cameras.py','camera_hub.py','config/lab.json','scripts/capture_onsite_rgbd.py','scripts/record_onsite_sequence.py']
for root in ROOTS:
    for f in files:
        p=root/'astra_realman_harness'/f
        if p.exists():a['source_fingerprints'].append(meta(p))
a['calibration_files']=[]
for root in ROOTS:
    h=root/'astra_realman_harness'
    for p in (h/'config/engineering').glob('*.json'):
        if not p.name.startswith('._'):a['calibration_files'].append(meta(p))
    for name in ['calibration_handoff_1011.json','controller_geometry_readback_20261011.json','wrist_handeye_candidate_20261011.json','overhead_extrinsic_validation_20261011.json','tabletop_pair_calibration_20261011-session2.json']:
        p=h/'logs'/name
        if p.exists():a['calibration_files'].append(meta(p))
a['sdk_candidates']=[]
for base in [P('/home/tongji/DP'),P('/home/tongji/alex'),P('/home/tongji/Downloads'),P('/home/tongji/Desktop')]:
    for d,dirs,files in os.walk(str(base)):
        dirs[:]=[x for x in dirs if x not in ['.git','logs','evidence','node_modules','__pycache__','site-packages']]
        if len(P(d).relative_to(base).parts)>6:dirs[:]=[];continue
        for f in files:
            if f in ['rm_robot_interface.py','libapi_c.so','rm_ctypes_wrap.py'] or (('realman' in f.lower() or 'rm_api' in f.lower()) and f.endswith('.so')):
                a['sdk_candidates'].append(meta(P(d)/f))
print(json.dumps(a,indent=2,ensure_ascii=False))
