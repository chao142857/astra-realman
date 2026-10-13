"""Reuse the existing production sandbox/worker/infer; mock never gets truth."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .schema import read, write, strict_json

HARNESS=Path(__file__).resolve().parents[3]/'astra_realman_harness'
MODEL='gpt-6-astra'
PARAMETERS={'model':MODEL,'model_reasoning_effort':'medium','provider':'openai','ephemeral':True}
TIMING_MODES=('standard','qualification')


def execution_timing(mode):
    """Reuse production timing profiles; never add timing to the model input."""
    if str(HARNESS) not in sys.path:sys.path.insert(0,str(HARNESS))
    from sim_skills.full_pnp.timing import timing_limits
    limits=timing_limits(mode)
    deadline_s=max(90,limits['request_timeout_s']+5)
    return {'mode':mode,'request_timeout_s':limits['request_timeout_s'],
            'worker_deadline_s':deadline_s,'launcher_timeout_s':deadline_s+15}


def production_imports():
    if str(HARNESS) not in sys.path:sys.path.insert(0,str(HARNESS))
    from sim_skills.full_pnp.infer_process import InferConfig, sandbox_command, isolated_preflight
    from scripts.structured_outputs import compile_schema
    return InferConfig,sandbox_command,isolated_preflight,compile_schema


def environment_config():
    """Optional host path only. Model, timing and security switches are immutable."""
    InferConfig,*_=production_imports()
    path=os.environ.get('SPATIAL_EVAL_ENV_CONFIG')
    if not path:return InferConfig()
    data=read(path)
    if set(data)!={'cli_executable'}:raise ValueError('ENV_CONFIG_ONLY_CLI_EXECUTABLE')
    executable=data['cli_executable']
    if not isinstance(executable,str) or not Path(executable).is_absolute():
        raise ValueError('ENV_CONFIG_ABSOLUTE_CLI_REQUIRED')
    return InferConfig(executable=executable)


def environment_sandbox(run):
    """Preserve production mounts; additionally expose a venv's interpreter runtime."""
    _,sandbox_command,*_=production_imports()
    cmd,env=sandbox_command(run,environment_config())
    base=Path(sys.base_prefix).resolve()
    if base!=Path(sys.prefix).resolve() and not base.is_relative_to('/usr'):
        # venv executables may symlink into Conda. Mount precisely that runtime,
        # never its home, project workspace, simulator or evaluator directories.
        pos=cmd.index('--chdir')
        cmd[pos:pos]=['--ro-bind',str(base),str(base)]
    return cmd,env


def preflight(output):
    # The original preflight uses sandbox_command internally. Preserve its
    # normal path when no separate interpreter mount is needed.
    InferConfig,_,probe,_=production_imports()
    base=Path(sys.base_prefix).resolve()
    if base==Path(sys.prefix).resolve() or base.is_relative_to('/usr'):
        return probe(environment_config(),Path(output))
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    (root/'input_only').mkdir();(root/'runtime').mkdir()
    report={'status':'FAIL','model_calls':0,'source':'LOCAL_CODEX_ASTRA_RAW'}
    try:
        cmd,env=environment_sandbox(root);cmd+=['--preflight']
        write(root/'command.json',cmd)
        proc=subprocess.run(cmd,stdin=subprocess.DEVNULL,capture_output=True,text=True,env=env,
                            cwd=root/'input_only',timeout=50)
        (root/'stdout.json').write_text(proc.stdout);(root/'stderr.log').write_text(proc.stderr)
        worker=json.loads(proc.stdout);report.update(return_code=proc.returncode,worker=worker)
        if proc.returncode==0 and worker['status']=='PASS':report['status']='PASS'
    except Exception as exc:report['error']=repr(exc)
    write(root/'preflight.json',report)
    return report


def prepare(context, images, folder, *, real=False):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    inp=folder/'input_only';inp.mkdir();(folder/'runtime').mkdir()
    blobs=[]
    for item,path in zip(context['attachments'],images):
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('FROZEN_IMAGE_HASH')
        (inp/item['file']).write_bytes(data);blobs.append(base64.b64encode(data).decode())
    authoritative=context['output_schema']
    schema=authoritative
    if real:
        *_,compile_schema=production_imports();schema,_=compile_schema(authoritative)
    payload={'context':context,'images':blobs,'schema':schema,'authoritative_schema':authoritative}
    write(inp/'wire.json',context);write(inp/'payload.json',payload)
    write(folder/'request.json',payload)
    write(folder/'model_parameters.json',PARAMETERS)
    return payload


def mock_raw(context):
    """Deliberately simplistic smoke predictor; no accuracy or A/C improvement claim."""
    task=context['task']
    if task['kind']=='understanding':
        answers=[]
        for q in task['questions']:
            a={'question_id':q['question_id'],'relation':None,'scalar_m':None,'vector_m':None,'fits':None}
            slot={'relation':'relation','height':'scalar_m','gap':'scalar_m','size':'vector_m','position':'vector_m','fit':'fits'}[q['type']]
            a[slot]={'relation':'equal','scalar_m':0.,'vector_m':[0.,0.,0.],'fits':False}[slot]
            answers.append(a)
        return json.dumps({'answers':answers})
    c=task['constraints']
    return json.dumps({'object_id':c['object_id'],'position_m':[0.,0.,0.],
                       'quaternion_wxyz':c['required_quaternion_wxyz'] or [1,0,0,0],
                       'waypoints_m':[[0.,0.,0.]] if task['kind']=='path' else []})


def infer(context, images, folder, *, real=False, fixture_response=None, timing_mode='standard'):
    timing=execution_timing(timing_mode)
    folder=Path(folder).resolve();prepare(context,images,folder,real=real)
    started=time.monotonic()
    if not real:
        raw=Path(fixture_response).read_text() if fixture_response else mock_raw(context)
        result={'raw':raw,'events':'','error':None,'return_code':0,'usage':None,
                'usage_status':'NOT_APPLICABLE_MOCK','source':'MOCK_NOT_ASTRA','model_calls':0}
    else:
        if fixture_response:raise ValueError('FIXTURE_CANNOT_ENTER_REAL_MODEL')
        InferConfig,sandbox_command,_,_=production_imports()
        command,env=environment_sandbox(folder)
        inp=folder/'input_only'
        command+=['--sha256',hashlib.sha256((inp/'wire.json').read_bytes()).hexdigest(),
                  '--payload-sha256',hashlib.sha256((inp/'payload.json').read_bytes()).hexdigest(),
                  '--deadline',str(time.monotonic()+timing['worker_deadline_s'])]
        if timing_mode!='standard':command+=['--mode',timing_mode]
        write(folder/'execution_timing.json',timing)
        write(folder/'worker_command.json',command)
        try:
            proc=subprocess.run(command,capture_output=True,text=True,env=env,timeout=timing['launcher_timeout_s'],cwd=inp)
            (folder/'worker_stdout.txt').write_text(proc.stdout);(folder/'worker_stderr.txt').write_text(proc.stderr)
            record=folder/'infer_output/worker_record.json'
            result=read(record) if record.exists() else {'raw':'','error':'WORKER_START_FAILED','return_code':proc.returncode,'usage':None}
            result.update(source='REAL_ASTRA_ATTEMPT',model_calls=int((folder/'infer_output/infer_started.json').exists()))
            if proc.returncode and not result.get('error'):result['error']='WORKER_EXIT_NONZERO'
        except subprocess.TimeoutExpired as exc:
            result={'raw':'','error':'WORKER_TIMEOUT','return_code':None,'usage':None,'source':'REAL_ASTRA_ATTEMPT',
                    'model_calls':int((folder/'infer_output/infer_started.json').exists())}
            (folder/'worker_stdout.txt').write_bytes(exc.stdout or b'');(folder/'worker_stderr.txt').write_bytes(exc.stderr or b'')
    result['wall_latency_s']=time.monotonic()-started
    (folder/'raw.txt').write_text(result.get('raw',''));write(folder/'response.json',result)
    return result
