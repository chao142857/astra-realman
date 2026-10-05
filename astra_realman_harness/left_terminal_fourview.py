"""Left-only four-view decision interface; shares existing executor without motion changes."""
import copy, hashlib, json, math, os, subprocess, time
from pathlib import Path
from io_utils import ROOT, strict_json, vector, number, write_json
from decision_backends import codex_command, check_events, redact
from model_step_review import FRAME_FINGERPRINTS

SCHEMA_PATH = ROOT/'schema/left_opening.schema.json'
ROLES = ('left_wrist', 'tabletop', 'overhead', 'additional_view')
WORK = 'realman:left:work:World'
TOOL = 'realman:left:tool:Arm_Tip'

def parse(raw):
    a = strict_json(raw)
    if not isinstance(a, dict) or set(a) != {'action_type','arm','frame','tool_frame','translation_m','rotation_rpy_rad','gripper_opening','done'}:
        raise ValueError('ACTION_FIELDS')
    if (a['action_type'], a['arm'], a['frame'], a['tool_frame']) != ('cartesian_delta','left',WORK,TOOL):
        raise ValueError('ACTION_INTERFACE')
    if not vector(a['translation_m'],3) or not vector(a['rotation_rpy_rad'],3):
        raise ValueError('NONFINITE_OR_INVALID_DELTA')
    if not number(a['gripper_opening']) or not 0 <= a['gripper_opening'] <= 1:
        raise ValueError('OPENING_TARGET_RANGE')
    if type(a['done']) is not bool:
        raise ValueError('DONE_TYPE')
    if a['done'] and any(a['translation_m'] + a['rotation_rpy_rad']):
        raise ValueError('DONE_WITH_ARM_MOTION')
    return a

def camera_config(config, live=False):
    cameras = config['cameras']
    if len(cameras)!=4 or tuple(c['role'] for c in cameras)!=ROLES or len({c['serial'] for c in cameras})!=4:
        raise ValueError('FOUR_DISTINCT_ORDERED_VIEWS_REQUIRED')
    if cameras[3]['serial']!='348522072063':
        raise ValueError('ADDITIONAL_CAMERA_SERIAL_MISMATCH')
    # First three physical roles are operator-confirmed. Fourth is explicitly
    # an additional view, with physical mounting unclaimed; no geometry transform.
    if live and any(c.get('role_confirmed') is not True for c in cameras[:3]):
        raise ValueError('CAMERA_ROLE_CONFIRMATION_REQUIRED')
    if config['arm'] != {'name':'left','host':'192.168.1.19','port':8080}:
        raise ValueError('LEFT_ENDPOINT_REQUIRED')
    return cameras

def select_replay(source, config, task, previous):
    """Filter old archival input; never present replay as a new acquisition."""
    cameras = camera_config(config)
    by_serial = {c['serial']:c for c in source['cameras']}
    chosen = []
    for c in cameras:
        item = copy.deepcopy(by_serial[c['serial']])
        item.update(role=c['role'], role_confirmed=c['role_confirmed'])
        chosen.append(item)
    return {'observation_id':source['observation_id'], 'task':task,
            'canonical_states':{'left':copy.deepcopy(source['canonical_states']['left'])},
            'cameras':chosen, 'capture_failures':[], 'captured_at':source['captured_at'],
            'capture_span_ms':max(c['captured_at'] for c in chosen)*1000-min(c['captured_at'] for c in chosen)*1000,
            'previous':previous, 'source':'ARCHIVAL_REPLAY_NOT_CURRENT'}

def model_input(obs, schema):
    if set(obs['canonical_states']) != {'left'} or len(obs['cameras']) != 4 or obs.get('capture_failures'):
        raise ValueError('LEFT_FOUR_VIEW_OBSERVATION_REQUIRED')
    if tuple(c['role'] for c in obs['cameras']) != ROLES or len({c['serial'] for c in obs['cameras']}) != 4:
        raise ValueError('VIEW_ORDER')
    images=[]
    for i,c in enumerate(obs['cameras'],1):
        p=Path(c['image_path']).resolve()
        if ROOT/'logs' not in p.parents or not p.is_file() or not 0<p.stat().st_size<=8*1024*1024:
            raise ValueError('IMAGE_PATH_OR_SIZE')
        data=p.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(data).hexdigest()!=c['sha256']:
            raise ValueError('IMAGE_INTEGRITY')
        images.append({k:c.get(k) for k in ('serial','role','role_confirmed','image_path','captured_at')})
        images[-1]['input_index']=i
    s=obs['canonical_states']['left']
    # Contact telemetry stays in observation/logs, not in model input.
    state={k:copy.deepcopy(s[k]) for k in ('arm','joint_deg','system_error','timestamp')}
    state['ee_pose']={k:copy.deepcopy(s['ee_pose'][k]) for k in ('xyz_m','rpy_rad','units')}
    g=s.get('gripper_state',{})
    state['gripper']={'opening_feedback':g.get('position')/1000 if number(g.get('position')) else None,
                     'range':[0,1], 'zero':'fully closed','one':'fully open','quantity':'opening, not force'}
    def frame(f):return {k:copy.deepcopy(f[k]) for k in ('id','name','pose')}
    return {'task':obs['task'], 'observation_id':obs['observation_id'],
            'images_in_attachment_order':images, 'robot_states':{'left':state},
            'work_frames':{'left':frame(s['work_frame'])},'tool_frames':{'left':frame(s['tool_frame'])},
            'previous':obs.get('previous'), 'action_schema':schema}

def validate_state(obs, live=False, max_age_s=180):
    errors=[]
    s=obs['canonical_states']['left']; ee=s.get('ee_pose',{}); raw=s.get('raw_sdk_state',{})
    e=s.get('system_error',{}); codes=e.get('codes')
    if not isinstance(codes,list) or not codes or any(type(c)is not int or c!=0 for c in codes) or e.get('has_error') is not False:
        errors.append('ROBOT_ERROR_OR_UNKNOWN')
    if (not vector(s.get('joint_deg'),6) or not vector(ee.get('xyz_m'),3) or not vector(ee.get('rpy_rad'),3)
        or ee.get('units')!={'xyz':'m','rpy':'rad'} or ee.get('unit_scale_applied')!=1
        or raw.get('joint')!=s.get('joint_deg') or raw.get('pose')!=ee.get('xyz_m',[])+ee.get('rpy_rad',[])):
        errors.append('STATE_UNITS_OR_VALUES')
    raw_error=raw.get('err',{})
    if (e.get('raw')!=raw_error or raw_error.get('err_len')!=len(codes or [])
        or raw_error.get('err') not in (codes,[str(c) for c in (codes or [])])):
        errors.append('ERROR_RAW_CANONICAL_MISMATCH')
    if s.get('connection',{}).get('ip')!='192.168.1.19' or s.get('frame_snapshot_stable') is not True:
        errors.append('CONNECTION_OR_UNSTABLE_FRAME')
    for key, expected in FRAME_FINGERPRINTS.items():
        f=s.get(key,{})
        fingerprint=hashlib.sha256(json.dumps(s.get('raw_'+key,{}),sort_keys=True,allow_nan=False).encode()).hexdigest()
        if f.get('definition_fingerprint')!=expected or fingerprint!=expected:
            errors.append(key.upper()+'_CHANGED')
    if s.get('work_frame',{}).get('id')!=WORK or s.get('tool_frame',{}).get('id')!=TOOL:
        errors.append('FRAME_ID')
    g=s.get('gripper_state',{}); gr=g.get('raw',{})
    if (not number(g.get('position')) or not 0<=g['position']<=1000 or gr.get('sys_state')!=0
        or not isinstance(gr.get('dof_err'),list) or not gr['dof_err'] or any(x!=0 for x in gr['dof_err'])):
        errors.append('GRIPPER_FEEDBACK_OR_ERROR')
    if obs.get('capture_failures') or not number(obs.get('capture_span_ms')) or not 0<=obs['capture_span_ms']<=1000:
        errors.append('CAMERA_CAPTURE')
    if live:
        stamps=[s.get('timestamp'),obs.get('captured_at')]+[c.get('captured_at') for c in obs['cameras']]
        if any(not number(t) or not 0<=time.time()-t<=max_age_s for t in stamps):errors.append('STALE_OBSERVATION')
    return errors

def command_plan(a, state):
    # Done is terminal; all actuator channels are ignored and nothing is dispatched.
    if a['done']:return {'arm':None,'gripper':None,'terminal':True}
    pose=[p+d for p,d in zip(state['ee_pose']['xyz_m']+state['ee_pose']['rpy_rad'],a['translation_m']+a['rotation_rpy_rad'])]
    if not vector(pose,6):raise ValueError('TARGET_NONFINITE')
    wire=int(a['gripper_opening']*1000)
    g=state['gripper_state']; satisfied=g['position']==wire and g['raw'].get('speed',[None])[0]==0
    return {'arm':{'function':'rm_movej_p','pose':pose,'speed_percent':1,'r':0,'connect':0,'block':1}
                   if any(a['translation_m']+a['rotation_rpy_rad']) else None,
            'gripper':None if satisfied else {'function':'RmArm.set_gripper_position',
                'opening_target':a['gripper_opening'],'wire_target':wire,'quantity':'opening, not force'},
            'gripper_channel':'ALREADY_SATISFIED' if satisfied else 'REQUESTED','terminal':False}

class DryRunExecutor:
    def execute(self, plan):
        return {'status':'DRY_RUN_NOT_SENT','executed_action':{'arm':None,'gripper':None},
                'sdk_result':{'called':False,'return_code':None},'hardware_commands_sent':0}

def call_astra(context, run, config, model, stop, emit):
    if config.get('backend') == 'CodexAstraBackend':
        from codex_astra_backend import CodexAstraBackend
        backend=CodexAstraBackend(config,run,model,stop,emit,SCHEMA_PATH,parse)
        backend.decide(context,context['images_in_attachment_order'])
        return backend.raw
    (run/'input_only').mkdir();(run/'runtime').mkdir()
    prompt=json.dumps(context,ensure_ascii=False,allow_nan=False)
    (run/'prompt.txt').write_text(prompt)
    command=codex_command(config['executable'],model,context['images_in_attachment_order'],run,config['provider'],schema=SCHEMA_PATH)
    write_json(run/'command.json',command)
    env={k:v for k,v in os.environ.items() if k in ('HOME','USER','LOGNAME','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR')}
    env.update(PATH='/usr/bin:/bin',TMPDIR=str(run/'runtime'))
    start=time.monotonic(); proc=None; result={'model':model,'status':'STARTED'}
    try:
        # File-backed output avoids pipe deadlocks while STOP remains responsive.
        with (run/'events.jsonl').open('x') as out, (run/'stderr.log').open('x') as err, (run/'prompt.txt').open() as inp:
            proc=subprocess.Popen(command,stdin=inp,stdout=out,stderr=err,cwd=run/'input_only',env=env)
            notified=0
            while proc.poll() is None:
                if stop.is_set():raise RuntimeError('HUMAN_STOP')
                elapsed=time.monotonic()-start
                if elapsed>config['timeout_s']:raise TimeoutError('ASTRA_TIMEOUT')
                if elapsed>=notified+5:
                    emit('ASTRA STATUS',{'status':'inference running','elapsed_s':round(elapsed,1)});notified=elapsed
                stop.wait(.1)
        result['return_code']=proc.returncode
        output=run/'last_message.json'
        if output.is_file():
            raw=output.read_text();(run/'astra_raw.txt').write_text(raw)
            emit('ASTRA RAW OUTPUT',raw)
        if proc.returncode!=0:raise RuntimeError('ASTRA_EXIT_NONZERO')
        final=check_events((run/'events.jsonl').read_text())
        if not output.is_file() or output.stat().st_size>65536 or output.read_text().strip()!=final.strip():
            raise RuntimeError('ASTRA_OUTPUT_MISMATCH')
        result['status']='COMPLETE'
        return output.read_text()
    except Exception as exc:
        result.update(status='FAILED',error=str(exc));raise
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        # Only the owned model subprocess is terminated; no hardware process or API.
        result['inference_latency_s']=time.monotonic()-start
        write_json(run/'backend_result.json',result)
