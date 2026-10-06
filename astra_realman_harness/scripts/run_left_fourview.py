#!/usr/bin/env python3
"""Four-camera left-only terminal; dry-run by default, explicit --execute for hardware."""
import argparse, copy, fcntl, json, signal, sys, threading, time, uuid
from contextlib import ExitStack
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT, read_json, write_json, new_run
from left_terminal_fourview import camera_config, select_replay, model_input, validate_state, parse, command_plan, DryRunExecutor, call_astra, SCHEMA_PATH
from left_preview_fourview import Preview

def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--replay',type=Path,help='Existing observation JSON. Never treated as current.')
    source.add_argument('--live',action='store_true',help='Read-only left SDK and three persistent cameras.')
    p.add_argument('--fixture',type=Path,help='Offline proposal text; clearly labeled, no model call.')
    p.add_argument('--execute',action='store_true',help='Enable REAL left actuator commands; requires --live, forbids fixtures/replay.')
    p.add_argument('--model',default='gpt-6-astra')
    p.add_argument('--task',help='Otherwise read one verbatim task line from terminal.')
    p.add_argument('--config',type=Path,default=ROOT/'config/left_terminal_fourview.json')
    p.add_argument('--max-steps',type=int,default=50)
    p.add_argument('--preview-port',type=int,default=8765)
    p.add_argument('--no-preview',action='store_true')
    args=p.parse_args()
    if not 1<=args.max_steps<=50:p.error('max steps must be 1..50')
    if args.replay and not args.fixture:p.error('Archive replay is offline fixture-only; use --live for actual Astra input.')
    if args.execute and (not args.live or args.fixture):p.error('--execute requires live observations and real model; fixtures/replay forbidden')
    mode='REAL_EXECUTION' if args.execute else 'DRY_RUN_ONLY'
    config=read_json(args.config); cameras=camera_config(config,live=args.live)
    task=args.task if args.task is not None else input('Task (verbatim; STOP cancels): ')
    if not task.strip() or task.strip().upper()=='STOP':return
    stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set());signal.signal(signal.SIGTERM,lambda *_:stop.set())
    def commands():
        for line in sys.stdin:
            if line.strip().upper()=='STOP':stop.set();return
    threading.Thread(target=commands,daemon=True).start()
    run=new_run(ROOT/'logs'/('left-fourview-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]))
    summary={'mode':mode,'hardware_commands_sent':0,'model_calls':0,'steps':0,'status':'STARTED','run':str(run)}
    def emit(label,value):
        print(label+' → '+(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,allow_nan=False)),flush=True)
    emit('RUN',{'log':str(run),'mode':mode,'stop':'type STOP + Enter, or Ctrl-C'})
    schema=read_json(SCHEMA_PATH);write_json(run/'config.json',config);write_json(run/'action_schema.json',schema)
    previous=None
    executor=None
    try:
        with ExitStack() as stack:
            lock=stack.enter_context((ROOT/'logs/auto-pick.lock').open('a+'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            session=None; streams=None
            if args.live:
                from camera_session import CameraSession
                from realman_api2_readonly import SDKReadOnly
                streams=stack.enter_context(CameraSession(cameras))
                session=stack.enter_context(SDKReadOnly(new_run(run/'sdk')))
                if not session.connect('left',config['arm']['host'],config['arm']['port'])['connected']:raise RuntimeError('LEFT_CONNECTION_FAILED')
            preview=None if args.no_preview else stack.enter_context(Preview(cameras,args.preview_port,streams,mode=mode))
            if preview:emit('CAMERA VIEW','http://127.0.0.1:'+str(preview.server.server_port))
            def capture(path):
                new_run(path)
                if not args.live:
                    obs=select_replay(read_json(args.replay),config,task,previous)
                    write_json(path/'source.json',{'path':str(args.replay),'type':'ARCHIVAL_REPLAY'})
                else:
                    images,failures,metrics=streams.snapshot(path)
                    sampled=session.snapshot('left');write_json(path/'left-sdk-sample.json',sampled)
                    state=sampled['canonical']
                    if state is None:raise RuntimeError('CANONICAL_STATE_FAILED')
                    raw=session.connected['left'].rm_get_rm_plus_state_info()
                    # Preserve every returned field, including available current/force/effort.
                    write_json(path/'gripper-raw.json',{'timestamp':time.time(),'raw_return':raw,'units':'SDK raw; unknown fields not interpreted as force'})
                    if type(raw[0]) is not int or raw[0]!=0:raise RuntimeError('GRIPPER_READ_FAILED:'+str(raw[0]))
                    g=raw[1]
                    state['gripper_state']={'position':g['pos'][0],'position_range':[0,1000],'raw':g}
                    obs={'observation_id':'left-'+uuid.uuid4().hex,'task':task,'canonical_states':{'left':state},
                         'cameras':images,'capture_failures':failures,'capture_span_ms':metrics['capture_span_ms'],
                         'camera_capture':metrics,'captured_at':min([state['timestamp']]+[c['captured_at'] for c in images]),
                         'previous':previous,'source':'LIVE_READ_ONLY'}
                write_json(path/'observation.json',obs)
                write_json(path/'contact-telemetry.json',{'raw_sdk_state':obs['canonical_states']['left'].get('raw_sdk_state'),
                    'raw_gripper':obs['canonical_states']['left'].get('gripper_state',{}).get('raw'),
                    'units':'raw SDK fields; absence is unknown, no force estimate; no contact controller'})
                if preview:preview.update(obs)
                return obs
            current=None
            for index in range(1,args.max_steps+1):
                if stop.is_set():raise RuntimeError('HUMAN_STOP')
                executor=None
                step=new_run(run/('step-%02d'%index));summary['steps']=index
                if current is None:current=capture(step/'input')
                else:write_json(step/'input_observation.json',current)
                obs=current;context=model_input(obs,schema)
                write_json(step/'model_input.json',context);emit('STEP',index);emit('MODEL INPUT',context)
                initial_errors=validate_state(obs,live=args.live)
                write_json(step/'input_validation.json',{'errors':initial_errors,'replay_age_exemption':not args.live,'execution_permitted':False})
                if initial_errors:raise RuntimeError('INPUT_REJECT:'+','.join(initial_errors))
                if stop.is_set():raise RuntimeError('HUMAN_STOP')
                decision=new_run(step/'decision')
                if args.fixture:
                    raw=args.fixture.read_text();(decision/'astra_raw.txt').write_text(raw)
                    write_json(decision/'backend_result.json',{'backend':'OFFLINE_FIXTURE_NOT_ASTRA','inference_latency_s':None})
                    emit('ASTRA RAW OUTPUT [OFFLINE FIXTURE]',raw)
                else:
                    summary['model_calls']+=1
                    raw=call_astra(context,decision,read_json(ROOT/'config/decision_backend.json'),args.model,stop,emit)
                # Store raw separately even when parsing fails.
                (step/'raw_proposal.txt').write_text(raw)
                action=parse(raw);write_json(step/'parsed_action.json',action);emit('PARSED ACTION',action)
                if stop.is_set():raise RuntimeError('HUMAN_STOP')
                errors=validate_state(obs,live=args.live)
                fresh=capture(step/'pre-execution') if args.execute else obs
                errors+=validate_state(fresh,live=args.live,max_age_s=3 if args.execute else 180)
                safety={'decision':'REJECT' if errors else ('PASS_INTERFACE_PENDING_FEASIBILITY' if args.execute else 'PASS_DRY_RUN_ONLY'),
                        'errors':errors,'execution_permitted':False,
                        'hardware_workspace_enforcement':'EXISTING_CONTROLLER_LIMITS' if args.execute else 'NOT_EXERCISED_IN_DRY_RUN'}
                write_json(step/'safety.json',safety);emit('SAFETY',safety)
                if errors:raise RuntimeError('SAFETY_REJECT')
                plan=command_plan(action,fresh['canonical_states']['left']);write_json(step/'planned_commands.json',plan)
                emit('PLANNED COMMANDS [NOT SENT]',plan)
                from exact_target_feasibility import check_exact_target, dispatch_checked
                if args.live:
                    check=check_exact_target(session,action,fresh)
                else:
                    check={'status':'NOT_CHECKED_OFFLINE','original_target':plan['arm']['pose'] if plan['arm'] else None,
                           'reason':'Offline replay does not load SDK or assert feasibility.','planner_status':'NOT_CHECKED'}
                write_json(step/'feasibility.json',check);emit('FEASIBILITY',check)
                if check['status']=='CHECK_ERROR':raise RuntimeError('FEASIBILITY_CHECK_FAULT:'+check['reason'])
                if stop.is_set():raise RuntimeError('HUMAN_STOP')
                if args.execute:
                    from left_executor import RealLeftExecutor
                    def make_executor():
                        nonlocal executor
                        executor=RealLeftExecutor(session,capture,stop,step)
                        return executor
                    try:executed=dispatch_checked(action,fresh,check,make_executor)
                    finally:
                        if executor is not None:
                            summary['hardware_commands_sent']+=executor.result['hardware_commands_sent']
                            emit('EXECUTED ACTION',executor.result['executed_action'])
                            emit('SDK RESULT',executor.result['sdk_result'])
                    if executor is None:
                        write_json(step/'executed_action.json',executed['executed_action'])
                        write_json(step/'sdk_result.json',executed['sdk_result'])
                        write_json(step/'execution_result.json',executed)
                        emit('EXECUTED ACTION',executed['executed_action']);emit('SDK RESULT',executed['sdk_result'])
                else:
                    executed=DryRunExecutor().execute(plan)
                    if check['status']=='REJECTED_IK':executed['status']='REJECTED_IK'
                    write_json(step/'executed_action.json',executed['executed_action']);emit('EXECUTED ACTION',executed['executed_action'])
                    write_json(step/'sdk_result.json',executed['sdk_result']);emit('SDK RESULT',executed['sdk_result'])
                previous={'last_action':action,'last_result':{'status':executed['status'],
                    'hardware_commands_sent':executed['hardware_commands_sent'],'command':executed['executed_action'],
                    'original_target':check['original_target'],
                    'feasibility':{k:check.get(k) for k in ('status','return_code','reason','planner_status')}}} 
                after=capture(step/'after')
                write_json(step/'after_state.json',after['canonical_states'])
                s=after['canonical_states']['left']
                emit('AFTER STATE',{'arm':'left','joint_deg':s['joint_deg'],'ee_pose':{k:s['ee_pose'][k] for k in ('xyz_m','rpy_rad')},'gripper_opening_feedback':s['gripper_state']['position']/1000,'system_error':s['system_error']})
                after_errors=validate_state(after,live=args.live)
                write_json(step/'after_validation.json',{'errors':after_errors})
                if after_errors:raise RuntimeError('AFTER_STATE_ERROR:'+','.join(after_errors))
                if args.execute:
                    from execution_telemetry import pose_telemetry
                    before=fresh['canonical_states']['left']['ee_pose']
                    target=plan['arm']['pose'] if plan['arm'] else before['xyz_m']+before['rpy_rad']
                    write_json(step/'pose-telemetry.json',pose_telemetry(before,{'xyz_m':target[:3],'rpy_rad':target[3:]},s['ee_pose']))
                    previous['last_result'].update(gripper_position=s['gripper_state']['position'],robot_errors={'left':s['system_error']['codes']})
                    after['previous']=previous
                current=after
                write_json(step/'next_observation.json',after);emit('NEXT OBSERVATION',{'path':str(step/'next_observation.json'),'source':after['source'],'images':[c['image_path'] for c in after['cameras']]})
                if action['done']:summary['status']='MODEL_DONE';break
                if args.replay:summary['status']='OFFLINE_REPLAY_COMPLETE';break
            else:summary['status']='MAX_STEPS'
    except Exception as exc:
        summary.update(status='STOPPED',reason=type(exc).__name__+':'+str(exc));emit('STOP',summary['reason'])
    finally:
        stop.set();write_json(run/'summary.json',summary);emit('SUMMARY',summary)
        from episode_archive import finalize_archive
        finalize_archive(run,task,emit)
    return 1 if summary['status']=='STOPPED' else 0

if __name__=='__main__':sys.exit(main())
