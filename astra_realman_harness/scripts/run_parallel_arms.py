#!/usr/bin/env python3
"""Single Astra decision loop; two independent arm workers; shadow is the default."""
import argparse,json,multiprocessing,signal,sys,threading,time,uuid
from contextlib import ExitStack
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,new_run,read_json,write_json
from arm_stack import model_input
from arm_worker import ProcessArmWorker
from parallel_arms import GroupCoordinator,group_schema,parse_group
from left_terminal import call_astra,validate_state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true',required=True,help='Connect SDK read sessions and persistent cameras.')
    p.add_argument('--execute',action='store_true',help='Send the checked action group; without this, shadow only.')
    p.add_argument('--task',help='Otherwise prompt for the task verbatim.')
    p.add_argument('--max-steps',type=int,default=100);p.add_argument('--time-budget-s',type=int,default=7200)
    p.add_argument('--config',type=Path,default=ROOT/'config/arm_mirror.json')
    p.add_argument('--backend-config',type=Path,default=ROOT/'config/decision_backend.json')
    args=p.parse_args()
    if not 1<=args.max_steps<=100 or not 1<=args.time_budget_s<=86400:p.error('invalid episode budget')
    task=args.task if args.task is not None else input('Task (STOP cancels): ')
    if not task.strip() or task.strip().upper()=='STOP':return
    config=read_json(args.config);backend=read_json(args.backend_config)
    if backend.get('backend')!='CodexAstraBackend':p.error('official existing CodexAstraBackend required')
    cams=config['cameras']
    if {c['role'] for c in cams}!={'left_wrist','right_wrist','tabletop','overhead'} or len(cams)!=4 or not all(c.get('role_confirmed') for c in cams):p.error('four confirmed camera roles required')
    context=multiprocessing.get_context('spawn');stop=context.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set());signal.signal(signal.SIGTERM,lambda *_:stop.set())
    def stdin_stop():
        for line in sys.stdin:
            if line.strip().upper()=='STOP':stop.set();return
    threading.Thread(target=stdin_stop,daemon=True).start()
    run=new_run(ROOT/'logs'/('parallel-arms-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]))
    def emit(name,value):print(name+' → '+(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)),flush=True)
    summary={'mode':'EXECUTE' if args.execute else 'SHADOW','model_calls':0,'steps':0,'status':'STARTED','log':str(run)}
    write_json(run/'config.json',config);emit('RUN',summary);started=time.monotonic();previous=None
    try:
        with ExitStack() as stack:
            # Existing exclusive episode mechanism; fixed path also shared by right-mirror CLI below.
            import fcntl
            lock=stack.enter_context(open('/tmp/astra-realman-actuation.lock','a+'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            workers={}
            for arm in ('left','right'):
                worker=ProcessArmWorker(arm,stop,run/('worker-'+arm));stack.callback(worker.close);workers[arm]=worker
            from camera_session import CameraSession
            streams=stack.enter_context(CameraSession(cams));coordinator=GroupCoordinator(workers,stop)
            def capture(path):
                path.mkdir(parents=True)
                states={arm:worker.read() for arm,worker in workers.items()}
                images,failures,metrics=streams.snapshot(path)
                obs={'observation_id':uuid.uuid4().hex,'canonical_states':states,'cameras':images,'capture_failures':failures,
                     'capture_span_ms':metrics['capture_span_ms'],'captured_at':min([s['timestamp'] for s in states.values()]+[c['captured_at'] for c in images]),
                     'task':task,'previous':previous,'source':'LIVE_READ_ONLY'}
                write_json(path/'observation.json',obs)
                for arm,s in states.items():
                    errors=validate_state(obs,live=True,max_age_s=3,arm_id=arm,work=s['work_frame']['id'],tool=s['tool_frame']['id'],frame_fingerprints={k:s[k]['definition_fingerprint'] for k in ('work_frame','tool_frame')})
                    if errors:raise RuntimeError(arm+':'+','.join(errors))
                return obs
            for index in range(1,args.max_steps+1):
                if stop.is_set():summary['status']='STOPPED';break
                if time.monotonic()-started>=args.time_budget_s:summary['status']='TIME_BUDGET';break
                step=new_run(run/('step-%03d'%index));summary['steps']=index
                obs=capture(step/'input');context_json=model_input(obs);schema=group_schema(obs['canonical_states']);context_json['action_schema']=schema
                schema_path=step/'action_schema.json';write_json(schema_path,schema);write_json(step/'model_input.json',context_json);emit('MODEL INPUT',context_json)
                decision=new_run(step/'decision');summary['model_calls']+=1
                raw=call_astra(context_json,decision,backend,'gpt-6-astra',stop,emit,schema_path=schema_path,decoder=lambda raw:parse_group(raw,obs['canonical_states']))
                (step/'raw_proposal.txt').write_text(raw)
                command=read_json(decision/'command.json')
                if not any(isinstance(x,str) and x.startswith('model_reasoning_effort=') and x.split('=',1)[1].strip('\"')=='medium' for x in command):
                    raise RuntimeError('BRIDGE_MEDIUM_REQUIRED_NO_ACTION_SENT')
                group=parse_group(raw,obs['canonical_states']);emit('ACTION GROUP',group)
                if time.monotonic()-started>=args.time_budget_s:summary['status']='TIME_BUDGET';break
                # Latest cameras/state before dispatch, after the possibly long model call.
                fresh=capture(step/'pre-execution');parse_group(group,fresh['canonical_states'])
                result=coordinator.run(group,step,execute=args.execute);emit('GROUP RESULT',result)
                previous={'last_action':group,'last_result':result}
                after=capture(step/'after');write_json(step/'after_state.json',after['canonical_states'])
                if result['status']=='MODEL_DONE':summary['status']='MODEL_DONE';break
            else:summary['status']='MAX_STEPS'
    except Exception as exc:
        stop.set();summary.update(status='STOPPED',error=type(exc).__name__+':'+str(exc));emit('STOP',summary['error'])
    finally:
        summary['elapsed_s']=time.monotonic()-started;write_json(run/'summary.json',summary);emit('SUMMARY',summary)
    return 1 if summary['status']=='STOPPED' else 0
if __name__=='__main__':raise SystemExit(main())
