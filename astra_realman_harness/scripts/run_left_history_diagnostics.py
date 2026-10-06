#!/usr/bin/env python3
"""Measured three-view H1/H5 D0/D1 loop. One task, continuous feedback, no step Enter."""
import argparse
import copy
import fcntl
import hashlib
import json
import signal
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, read_json, write_json, new_run
from left_terminal import camera_config, select_replay, validate_state, command_plan, DryRunExecutor, call_astra
from history_diagnostics import PROFILES, TransitionHistory, build_transition, decode, schema_path
from timing import Timings
from left_preview import Preview


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--replay', type=Path, help='Archival observation; fixture-only, no model or hardware.')
    source.add_argument('--live', action='store_true')
    p.add_argument('--fixture', type=Path, help='Offline response, envelope for D1, action for D0.')
    p.add_argument('--execute', action='store_true', help='Real hardware; requires live model, forbids fixture/replay.')
    p.add_argument('--profile', choices=PROFILES, default='H5D0')
    p.add_argument('--model', choices=['gpt-6-astra'], default='gpt-6-astra')
    p.add_argument('--task', help='Otherwise enter once; preserved verbatim.')
    p.add_argument('--config', type=Path, default=ROOT/'config/left_terminal.json')
    p.add_argument('--max-steps', type=int, default=10)
    p.add_argument('--wall-budget-s', type=float, default=480,
                   help='Monotonic episode budget; blocks new commands, cannot interrupt blocking SDK motion.')
    p.add_argument('--preview-port', type=int, default=8765)
    p.add_argument('--no-preview', action='store_true')
    p.add_argument('--lock-path', type=Path, help='Shared existing auto-pick.lock; default is original lab lock for live runs.')
    p.add_argument('--layout-id', default='unassigned')
    p.add_argument('--trial-id', default='unassigned')
    p.add_argument('--phase', choices=['placement', 'full-pick-place', 'diagnostic'], default='placement')
    args = p.parse_args()
    if not 1 <= args.max_steps <= 50 or not 0 < args.wall_budget_s < float('inf'):
        p.error('max steps must be 1..50; wall budget must be positive and finite')
    if args.replay and not args.fixture:
        p.error('Replay is fixture-only; use prepare_history_replay.py for fixed-observation inference.')
    if args.execute and (not args.live or args.fixture):
        p.error('--execute requires --live and real model; fixtures/replay forbidden')
    config = read_json(args.config)
    cameras = camera_config(config, live=args.live)
    backend_config = read_json(ROOT/'config/decision_backend.json')
    if backend_config.get('backend') != 'CodexAstraBackend':
        p.error('New profiles require existing CodexAstraBackend; no fallback')
    task = args.task if args.task is not None else input('Task (verbatim; STOP cancels): ')
    if not task.strip() or task.strip().upper() == 'STOP':
        return 0
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    def commands():
        for line in sys.stdin:
            if line.strip().upper() == 'STOP':
                stop.set()
                return
    threading.Thread(target=commands, daemon=True).start()
    run = new_run(ROOT/'logs'/('left-measured-'+args.profile+'-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]))
    episode_id = run.name
    history = TransitionHistory(args.profile, episode_id)
    schema = read_json(schema_path(args.profile))
    mode = 'REAL_EXECUTION' if args.execute else 'DRY_RUN_ONLY'
    summary = {'episode_id':episode_id, 'profile':args.profile, 'mode':mode, 'model_calls':0,
               'hardware_commands_sent':0, 'steps':0, 'status':'STARTED', 'run':str(run),
               'independent_success':'unknown'}
    def emit(label, value):
        print(label+' → '+(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,allow_nan=False)),flush=True)
    emit('RUN', {'log':str(run),'mode':mode,'profile':args.profile,'stop':'STOP + Enter or Ctrl-C'})
    write_json(run/'config.json', config)
    write_json(run/'action_schema.json', schema)
    write_json(run/'history_profile.json', {
        'profile':args.profile,'history_k':int(args.profile[1]),'diagnostics':args.profile.endswith('D1'),
        'model':args.model,'reasoning_effort':'low','speed_percent':1,'historical_images':False,
        'camera_order':[c['role'] for c in cameras],'task':task,
        'max_steps':args.max_steps,'wall_budget_s':args.wall_budget_s,
        'layout_id':args.layout_id,'trial_id':args.trial_id,'phase':args.phase,
        'source_revision_base':'22bfb2e549e6ca98b741ba84f254d4c1bbe66225'})
    source_files = ['scripts/run_left_history_diagnostics.py','history_diagnostics.py','left_terminal.py',
                    'left_executor.py','exact_target_feasibility.py','codex_astra_backend.py',
                    'scripts/codex_astra_mac_bridge.py','timing.py','schema/left_decision.schema.json',
                    'schema/left_opening.schema.json']
    write_json(run/'source_manifest.json',{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_files})
    # Independent labels stay outside model input and history.
    write_json(run/'independent_observation.template.json', {
        'episode_id':episode_id,'actual_stable_in_basket':'unknown','evidence':None,
        'observer':None,'observed_at':None,'recovery_after_failure':'unknown',
        'visual_contradiction_steps':[],'ineffective_action_steps':[],
        'human_intervention':'unknown','starting_state_deviation':'unknown','notes':''})
    started = time.monotonic()
    deadline = started + args.wall_budget_s
    timer = threading.Timer(args.wall_budget_s, stop.set)
    timer.daemon = True
    timer.start()
    def guard():
        if time.monotonic() >= deadline:
            raise RuntimeError('WALL_BUDGET_EXHAUSTED')
        if stop.is_set():
            raise RuntimeError('HUMAN_STOP')
    timings = None
    previous = None
    try:
        with ExitStack() as stack:
            lock_path = args.lock_path or (Path('/home/tongji/alex/astra_realman_harness/logs/auto-pick.lock') if args.live else ROOT/'logs/auto-pick.lock')
            lock = stack.enter_context(lock_path.open('a+'))
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            session = streams = None
            if args.live:
                from camera_session import CameraSession
                from realman_api2_readonly import SDKReadOnly
                streams = stack.enter_context(CameraSession(cameras))
                session = stack.enter_context(SDKReadOnly(new_run(run/'sdk')))
                if not session.connect('left',config['arm']['host'],config['arm']['port'])['connected']:
                    raise RuntimeError('LEFT_CONNECTION_FAILED')
            preview = None if args.no_preview else stack.enter_context(Preview(cameras,args.preview_port,streams,mode=mode))
            if preview:
                emit('CAMERA VIEW','http://127.0.0.1:'+str(preview.server.server_port))
            def capture(path):
                parent = 'executor' if path.name in ('between-channels','failure-readback') else 'step'
                with timings.measure('capture.'+path.name, parent):
                    new_run(path)
                    if not args.live:
                        obs = select_replay(read_json(args.replay),config,task,previous)
                        write_json(path/'source.json',{'path':str(args.replay),'type':'ARCHIVAL_REPLAY'})
                    else:
                        images,failures,metrics = streams.snapshot(path)
                        sampled = session.snapshot('left')
                        write_json(path/'left-sdk-sample.json',sampled)
                        state = sampled['canonical']
                        if state is None:
                            raise RuntimeError('CANONICAL_STATE_FAILED')
                        raw = session.connected['left'].rm_get_rm_plus_state_info()
                        write_json(path/'gripper-raw.json',{'timestamp':time.time(),'raw_return':raw,'units':'SDK raw; unknown fields not interpreted as force'})
                        if type(raw[0]) is not int or raw[0] != 0:
                            raise RuntimeError('GRIPPER_READ_FAILED:'+str(raw[0]))
                        g = raw[1]
                        state['gripper_state'] = {'position':g['pos'][0],'position_range':[0,1000],'raw':g}
                        obs = {'observation_id':'left-'+uuid.uuid4().hex,'task':task,'canonical_states':{'left':state},
                               'cameras':images,'capture_failures':failures,'capture_span_ms':metrics['capture_span_ms'],
                               'camera_capture':metrics,'captured_at':min([state['timestamp']]+[c['captured_at'] for c in images]),
                               'previous':None,'source':'LIVE_READ_ONLY'}
                    # Raw capture is immutable. Final transition and next observation are separate files.
                    write_json(path/'observation.json',obs)
                    write_json(path/'contact-telemetry.json',{'raw_sdk_state':obs['canonical_states']['left'].get('raw_sdk_state'),
                        'raw_gripper':obs['canonical_states']['left'].get('gripper_state',{}).get('raw'),
                        'units':'raw SDK fields; absence is unknown, no force estimate; no contact controller'})
                    if preview:
                        preview.update(obs)
                    return obs
            current = None
            for index in range(1,args.max_steps+1):
                guard()
                step = new_run(run/('step-%02d'%index))
                summary['steps'] = index
                timings = Timings()
                step_started = time.monotonic()
                try:
                    if current is None:
                        current = capture(step/'input')
                    obs = copy.deepcopy(current)
                    obs['decision_ready_at'] = time.time()
                    obs['episode_id'] = episode_id
                    write_json(step/'input_observation.json',obs)
                    with timings.measure('request_context', 'step'):
                        context = history.context(obs,schema,index)
                    write_json(step/'model_input.json',context)
                    emit('STEP',index)
                    emit('MODEL INPUT',context)
                    errors = validate_state(obs,live=args.live)
                    write_json(step/'input_validation.json',{'errors':errors,'replay_age_exemption':not args.live})
                    if errors:
                        raise RuntimeError('INPUT_REJECT:'+','.join(errors))
                    guard()
                    decision = new_run(step/'decision')
                    if args.fixture:
                        raw = args.fixture.read_text()
                        (decision/'astra_raw.txt').write_text(raw)
                        (decision/'prompt.txt').write_text(json.dumps(context,ensure_ascii=False,allow_nan=False))
                        write_json(decision/'attachments.json',context['images_in_attachment_order'])
                        write_json(decision/'backend_result.json',{'backend':'OFFLINE_FIXTURE_NOT_ASTRA','inference_latency_s':None})
                    else:
                        summary['model_calls'] += 1
                        with timings.measure('backend', 'step'):
                            raw = call_astra(context,decision,backend_config,args.model,stop,emit,
                                             schema_path=schema_path(args.profile),decoder=lambda text:decode(text,args.profile)[1])
                    (step/'raw_proposal.txt').write_text(raw)
                    diagnostics, action = decode(raw,args.profile)
                    if diagnostics is not None:
                        write_json(step/'diagnostics.json',diagnostics)
                        emit('DIAGNOSTICS',diagnostics)
                    write_json(step/'parsed_action.json',action)
                    emit('PARSED ACTION',action)
                    guard()
                    fresh = capture(step/'pre-execution') if args.execute else obs
                    errors = validate_state(obs,live=args.live) + validate_state(fresh,live=args.live,max_age_s=3 if args.execute else 180)
                    write_json(step/'safety.json',{'decision':'REJECT' if errors else 'PASS_INTERFACE_PENDING_FEASIBILITY','errors':errors,'execution_permitted':False})
                    if errors:
                        raise RuntimeError('SAFETY_REJECT')
                    plan = command_plan(action,fresh['canonical_states']['left'])
                    write_json(step/'planned_commands.json',plan)
                    from exact_target_feasibility import check_exact_target, dispatch_checked
                    with timings.measure('ik','step'):
                        check = check_exact_target(session,action,fresh) if args.live else {
                            'status':'NOT_CHECKED_OFFLINE','original_target':plan['arm']['pose'] if plan['arm'] else None,
                            'reason':'Offline replay; no SDK or feasibility assertion.','planner_status':'NOT_CHECKED'}
                    write_json(step/'feasibility.json',check)
                    emit('FEASIBILITY',check)
                    executor = None
                    execution_error = None
                    try:
                        guard()
                        if check['status'] == 'CHECK_ERROR':
                            raise RuntimeError('FEASIBILITY_CHECK_FAULT:'+check['reason'])
                        with timings.measure('executor','step'):
                            if args.execute:
                                from left_executor import RealLeftExecutor
                                def make_executor():
                                    nonlocal executor
                                    executor = RealLeftExecutor(session,capture,stop,step,timings=timings)
                                    return executor
                                executed = dispatch_checked(action,fresh,check,make_executor)
                            else:
                                executed = DryRunExecutor().execute(plan)
                                if check['status'] == 'REJECTED_IK':
                                    executed['status'] = 'REJECTED_IK'
                    except Exception as exc:
                        execution_error = exc
                        executed = copy.deepcopy(executor.result) if executor else {
                            'status':'STOPPED','executed_action':{'arm':None,'gripper':None},
                            'sdk_result':{'called':False,'arm':None,'gripper':None},'hardware_commands_sent':0}
                        executed.update(status='STOPPED',error=str(exc))
                    summary['hardware_commands_sent'] += executed['hardware_commands_sent']
                    if not (step/'execution_result.json').exists():
                        write_json(step/'execution_result.json',executed)
                        write_json(step/'executed_action.json',executed['executed_action'])
                        write_json(step/'sdk_result.json',executed['sdk_result'])
                    emit('EXECUTED ACTION',executed)
                    after = None
                    readback_error = None
                    after_errors = []
                    try:
                        after = capture(step/'after')
                        write_json(step/'after_state.json',after['canonical_states'])
                        after_errors = validate_state(after,live=args.live)
                    except Exception as exc:
                        readback_error = type(exc).__name__+':'+str(exc)
                    write_json(step/'after_validation.json',{'errors':after_errors,'readback_error':readback_error})
                    transition = build_transition(episode_id,index,obs,fresh,after,action,executed,check,
                        completed_at=time.time(),after_errors=after_errors,readback_error=readback_error)
                    write_json(step/'transition.json',transition)
                    write_json(step/'pose-telemetry.json',{k:transition[k] for k in (
                        'dispatch_before_pose','actual_after_pose','actual_xyz_delta_m','translation_residual_m',
                        'rotation_residual_rad','execution_residual_applicable','residual_reference')})
                    if after is not None:
                        current = copy.deepcopy(after)
                        current.update(previous=None,decision_ready_at=time.time(),episode_id=episode_id,
                                       completed_transition_path=str(step/'transition.json'))
                        write_json(step/'next_observation.json',current)
                    if execution_error:
                        raise execution_error
                    if after_errors or readback_error:
                        raise RuntimeError('AFTER_STATE_ERROR:'+str(after_errors or readback_error))
                    history.append(transition)
                    guard()
                    if action['done']:
                        summary['status'] = 'MODEL_DONE'
                        break
                    if args.replay:
                        summary['status'] = 'OFFLINE_REPLAY_COMPLETE'
                        break
                finally:
                    write_json(step/'timing.json',{'step_total_s':time.monotonic()-step_started,
                        'stages':timings.rows,'semantics':'parent-child; do not sum nested stages'})
            else:
                summary['status'] = 'MAX_STEPS'
    except Exception as exc:
        summary.update(status='WALL_BUDGET_EXHAUSTED' if time.monotonic() >= deadline else 'STOPPED',
                       reason=type(exc).__name__+':'+str(exc))
        emit('STOP',summary['reason'])
    finally:
        timer.cancel()
        stop.set()
        summary.update(episode_total_s=time.monotonic()-started,
                       budget_overrun_s=max(0,time.monotonic()-deadline))
        write_json(run/'summary.json',summary)
        emit('SUMMARY',summary)
    return 1 if summary['status']=='STOPPED' else 0

if __name__ == '__main__':
    sys.exit(main())
