"""Read-only projection of group journals for GUI; no control or model imports."""
import json
import time
import uuid
from io_utils import ROOT, new_run, write_json


def group_evidence(step):
    from astra_gui import load, action_summary
    obs=load(step/'input/observation.json')
    group=load(step/'parsed_group.json');result=load(step/'group_result.json')
    checks=load(step/'group_preflight.json');backend=load(step/'decision/backend_result.json')
    before=load(step/'pre-execution/observation.json').get('canonical_states',obs.get('canonical_states',{}))
    after=load(step/'after_state.json');arms={};dispatch=False;sent=0
    for arm in ('left','right'):
        folder=step/arm
        action=next((a for a in group.get('actions',[]) if a['arm']==arm),None)
        value=load(folder/'worker_result.json') or result.get('arms',{}).get(arm,{}) or load(folder/'execution_result.json')
        claims={channel:load(folder/(channel+'-dispatch.claim.json')) for channel in ('arm','gripper') if (folder/(channel+'-dispatch.claim.json')).exists()}
        dispatch=dispatch or bool(claims) or bool(value.get('hardware_commands_sent'))
        sent+=value.get('hardware_commands_sent',0) or 0
        preflights=sorted(folder.glob('preflight-*/check.json'),key=lambda p:int(p.parent.name.split('-')[-1]))
        check=load(preflights[-1]) if preflights else checks.get(arm,{})
        status=value.get('status') or ('DISPATCH_STARTED_OUTCOME_PENDING' if claims else
            'HELD' if group and action is None else result.get('status') or check.get('status') or 'WAITING')
        arms[arm]={'status':status,'action':action,'action_summary':action_summary(action) if action else {'text':'保持当前状态' if group else '等待动作组'},
            'preflight':check,'dispatch_claims':claims,'executed_command':value.get('executed_action',load(folder/'executed_action.json')),
            'sdk_result':value.get('sdk_result',load(folder/'sdk_result.json')),'before':before.get(arm),
            'after':value.get('after_state') or after.get(arm) or load(folder/'after/observation.json').get('canonical_states',{}).get(arm),
            'error':value.get('error'),'started_at':value.get('started_at'),'finished_at':value.get('finished_at')}
    status=result.get('status') or ('EXECUTING' if dispatch else 'PREFLIGHT' if group else backend.get('status') or 'WAITING')
    try:raw=(step/'raw_proposal.txt').read_text()
    except OSError:raw=None
    return {'step':step.name,'action':group,'action_summary':action_summary(group),'arms':arms,'execution_mode':group.get('execution'),
        'status':status,'result_text':status+' · '+str(group.get('execution','等待 Astra')),'stage':status,
        'failure_reason':result.get('error') or backend.get('error'),'failure':load(step/'failure.json'),
        'dispatch_started':dispatch,'executed_command':{a:v['executed_command'] for a,v in arms.items()},
        'sdk_result':{a:v['sdk_result'] for a,v in arms.items()},'hardware_commands_sent':sent if result else None,
        'feasibility':checks,'backend':backend,'diagnostics':{},'raw_proposal':raw,'model_output_valid':bool(group),
        'decision_cameras':obs.get('cameras',[]),'camera_streams':obs.get('camera_capture',{}),
        'observation_id':obs.get('observation_id'),'timing':{'execution_s':result.get('elapsed_s')}}


def demo_run(console):
    """Synthetic group records only; never starts arm workers, SDK, cameras or model."""
    from fixtures.synthetic_history import action
    run=new_run(ROOT/'logs'/('gui-parallel-demo-'+uuid.uuid4().hex[:8]));console.current_run=run
    write_json(run/'SYNTHETIC.json',{'synthetic':True});console._line('RUN → '+json.dumps({'log':str(run)}))
    start=time.monotonic();status='MAX_STEPS';count=0
    try:
        for count in range(1,min(console.settings['max_steps'],3)+1):
            if console.demo_stop.is_set():status='STOPPED';break
            step=new_run(run/('step-%03d'%count));actions=[]
            for arm in ('left','right'):
                a=action();a.update(arm=arm,frame='realman:'+arm+':work:World',tool_frame='realman:'+arm+':tool:Arm_Tip');actions.append(a)
            group={'done':False,'execution':'parallel','actions':actions}
            write_json(step/'action_schema.json',{'properties':{'actions':{}}})
            if console.demo_stop.wait(.3):status='STOPPED';break
            write_json(step/'parsed_group.json',group);(step/'raw_proposal.txt').write_text(json.dumps(group))
            write_json(step/'group_preflight.json',{a:{'status':'REJECTED_IK' if count==2 else 'PASS_IK','synthetic':True} for a in ('left','right')})
            results={}
            if count!=2:
                for arm in ('left','right'):
                    d=new_run(step/arm);write_json(d/'arm-dispatch.claim.json',{'synthetic':True})
                    if console.demo_stop.wait(.3):status='STOPPED';break
                    results[arm]={'status':'EXECUTED','synthetic':True,'hardware_commands_sent':0,'sdk_result':{'synthetic':True,'arm':0}}
                    write_json(d/'worker_result.json',results[arm])
            write_json(step/'group_result.json',{'status':'STOPPED' if status=='STOPPED' else 'REJECTED_IK' if count==2 else 'COMPLETED','execution':'parallel','arms':results})
            if status=='STOPPED':break
    finally:
        write_json(run/'summary.json',{'status':status,'steps':count,'model_calls':0,'hardware_commands_sent':0,'elapsed_s':time.monotonic()-start,'synthetic':True})
        from episode_archive import finalize_archive
        finalize_archive(run,console.settings['task'],lambda label,value:console._line(label+' → '+json.dumps(value,ensure_ascii=False)))
        console.active=False
