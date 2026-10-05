"""Pure preflight IK of the exact proposal target. No motion, projection or search."""
import copy, ctypes, hashlib, json, time
from io_utils import vector
from left_terminal import command_plan,parse

class FeasibilityFault(RuntimeError):pass

def binding(action,state):
    data={'action':action,'joint_deg':state['joint_deg'],'ee_pose':state['ee_pose'],
          'work_frame':state['work_frame'],'tool_frame':state['tool_frame'],'timestamp':state['timestamp']}
    return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()

def check_exact_target(session,action,observation):
    start=time.monotonic()
    a=parse(json.dumps(action,allow_nan=False))
    state=observation['canonical_states']['left'];plan=command_plan(a,state)
    result={'status':'CHECK_ERROR','check_kind':'ENDPOINT_IK_ONLY','planner_status':'NOT_CHECKED_NO_INDEPENDENT_PLANNER',
            'motion_commands_sent':0,'original_target':copy.deepcopy(plan['arm']['pose']) if plan['arm'] else None,
            'frame':a['frame'],'tool_frame':a['tool_frame'],'seed_joint_deg':copy.deepcopy(state['joint_deg']),
            'binding':binding(a,state),'target_modified':False,'return_code':None,'raw_ik_return':None,
            'solution_joint_deg':None,'reason':None,'checker_function':'rm_algo_inverse_kinematics',
            'checker_flag':1,'units':{'joint':'deg','position':'m','rpy':'rad'}}
    try:
        if not plan['arm']:
            result.update(status='NOT_REQUIRED',reason='No arm motion requested');return result
        if set(session.connected)!={'left'}:raise FeasibilityFault('LEFT_SESSION_ONLY')
        # ctypes uses float32 in the same SDK motion call; reject overflow, never clamp.
        if any(not __import__('math').isfinite(ctypes.c_float(v).value) for v in result['original_target']+state['joint_deg']):
            raise FeasibilityFault('SDK_FLOAT32_INPUT_OVERFLOW')
        params=session.sdk.rm_inverse_kinematics_params_t(q_in=state['joint_deg'],q_pose=result['original_target'],flag=1)
        raw=session.connected['left'].rm_algo_inverse_kinematics(params)
        result['raw_ik_return']=copy.deepcopy(raw)
        if not isinstance(raw,(tuple,list)) or len(raw)!=2 or type(raw[0]) is not int:
            raise FeasibilityFault('INVALID_IK_RETURN')
        ret,solution=raw;result['return_code']=ret
        if ret==1:
            result.update(status='REJECTED_IK',reason='SDK endpoint IK failed for the unchanged original target; no actuator command sent.')
        elif ret==0 and vector(solution,6):
            result.update(status='PASS_IK',solution_joint_deg=list(solution),reason='Endpoint IK solution found; path/collision feasibility not certified.')
        else:raise FeasibilityFault('IK_API_ERROR_OR_INVALID_SOLUTION:'+str(ret))
        return result
    except Exception as exc:
        result.update(status='CHECK_ERROR',reason=type(exc).__name__+':'+str(exc))
        return result
    finally:result['latency_s']=time.monotonic()-start

def require_exact_check(result,action,observation):
    state=observation['canonical_states']['left'];plan=command_plan(action,state)
    expected='PASS_IK' if plan['arm'] else 'NOT_REQUIRED'
    if (not isinstance(result,dict) or result.get('status')!=expected or result.get('binding')!=binding(action,state)
        or result.get('original_target')!=(plan['arm']['pose'] if plan['arm'] else None) or result.get('target_modified') is not False):
        raise FeasibilityFault('MISSING_FAILED_OR_MISMATCHED_FEASIBILITY_CHECK')

def dispatch_checked(action,observation,check,executor_factory):
    """A rejected mathematical proposal never constructs a hardware executor."""
    if check['status']=='REJECTED_IK':
        if check.get('binding')!=binding(action,observation['canonical_states']['left']):
            raise FeasibilityFault('REJECTION_BINDING_MISMATCH')
        return {'status':'REJECTED_IK','executed_action':{'arm':None,'gripper':None},
                'sdk_result':{'called':False,'arm':None,'gripper':None},'hardware_commands_sent':0,'execution_latency_s':0}
    # No REJECTED_PLANNING fabricated: no independent trajectory checker exists here.
    require_exact_check(check,action,observation)
    return executor_factory().execute(action,observation,feasibility=check)
