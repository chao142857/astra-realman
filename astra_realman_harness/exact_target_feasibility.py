"""Pure preflight IK of the exact proposal target. No motion, projection or search."""
import copy, ctypes, hashlib, json, time, math, threading
from io_utils import vector
from left_terminal import command_plan,parse

class FeasibilityFault(RuntimeError):pass

_SOLVER_LOCK = threading.RLock()  # SDK traversal mode is process-global.

def solve_exact_inputs(session, arm, q_in, target, flag=1, *, all_stages=False):
    """Solve a frozen target; never dispatch, change targets or search nearby poses.

    all_stages is diagnostic-only: evaluate all three methods even if fast succeeds.
    This checker owns traversal mode (normally False), and restores it in finally.
    """
    started = time.monotonic()
    q_in, target = copy.deepcopy(q_in), copy.deepcopy(target)
    out = dict(status='CHECK_ERROR', q_in=q_in, exact_target_pose=target, checker_flag=flag,
               fast_return=None, traversal_return=None, all_solution_count=None,
               all_solutions=None, selected_solution=None, solution_joint_deg=None,
               solver_path=[], return_code=None, raw_ik_return=None, target_modified=False,
               motion_commands_sent=0, reason=None)
    try:
        if not vector(q_in, 6) or not vector(target, 6) or type(flag) is not int or flag != 1:
            raise FeasibilityFault('INVALID_EXACT_INPUT')
        if any(not math.isfinite(ctypes.c_float(v).value) for v in target+q_in):
            raise FeasibilityFault('SDK_FLOAT32_INPUT_OVERFLOW')
        robot = session.connected[arm]
        def params():
            # Fresh buffers prevent a solver mutating the next solver's input.
            return session.sdk.rm_inverse_kinematics_params_t(q_in=list(q_in), q_pose=list(target), flag=flag)
        def single(stage):
            out['solver_path'].append(stage)
            raw = robot.rm_algo_inverse_kinematics(params())
            out[stage+'_return'] = copy.deepcopy(raw)
            if stage == 'fast': out['raw_ik_return'] = copy.deepcopy(raw)
            if not isinstance(raw, (tuple,list)) or len(raw)!=2 or type(raw[0]) is not int:
                raise FeasibilityFault('INVALID_IK_RETURN:'+stage)
            code, solution = raw
            out['return_code'] = code
            if code not in (0,1) or (code==0 and not vector(solution,6)):
                raise FeasibilityFault('IK_API_ERROR_OR_INVALID_SOLUTION:'+stage+':'+str(code))
            return list(solution) if code==0 else None
        chosen = None
        with _SOLVER_LOCK:
            chosen = single('fast')
            if chosen is not None: out['selected_solver'] = 'fast'
            if chosen is None or all_stages:
                # No hardware setting is changed; this is the SDK algorithm mode.
                try:
                    robot.rm_algo_set_redundant_parameter_traversal_mode(True)
                    out['traversal_mode_enabled'] = True
                    traversed = single('traversal')
                finally:
                    robot.rm_algo_set_redundant_parameter_traversal_mode(False)
                    out['traversal_mode_restored_false'] = True
                if chosen is None and traversed is not None:
                    chosen = traversed; out['selected_solver'] = 'traversal'
            if chosen is None or all_stages:
                info = robot.rm_get_robot_info()
                out['robot_info_return'] = copy.deepcopy(info)
                if (not isinstance(info,(list,tuple)) or len(info)!=2 or type(info[0]) is not int
                    or info[0]!=0 or not isinstance(info[1],dict)):
                    raise FeasibilityFault('ROBOT_INFO_FAILED')
                if info[1].get('arm_dof')!=6 or info[1].get('arm_model')!='RM_65':
                    raise FeasibilityFault('ALL_SOLUTIONS_REQUIRES_VERIFIED_6DOF_RM65')
                out['solver_path'].append('all_solutions')
                raw = robot.rm_algo_inverse_kinematics_all(params())
                out['all_result'] = raw.result
                out['all_solution_count'] = raw.num
                out['all_q_ref'] = list(raw.q_ref)
                if type(raw.result) is not int or raw.result not in (0,1):
                    raise FeasibilityFault('ALL_SOLUTIONS_API_ERROR:'+str(raw.result))
                if type(raw.num) is not int or not 0 <= raw.num <= 8:
                    raise FeasibilityFault('INVALID_ALL_SOLUTION_COUNT')
                rows = [list(raw.q_solve[i]) for i in range(raw.num)]
                out['all_solutions'] = rows
                out['candidate_checks'] = []
                valid = []
                if raw.result==1 and raw.num:
                    raise FeasibilityFault('INCONSISTENT_ALL_SOLUTIONS_RESULT')
                for index, row in enumerate(rows):
                    candidate = row[:6]
                    if not vector(candidate,6): raise FeasibilityFault('INVALID_ALL_SOLUTION')
                    # Local SDK wrapper requires a float pointer despite its list annotation.
                    limit = robot.rm_algo_ikine_check_joint_position_limit((ctypes.c_float*6)(*candidate))
                    check = dict(index=index, joint_deg=candidate, joint_limit_return=limit)
                    out['candidate_checks'].append(check)
                    if type(limit) is not int or not 0<=limit<=6:
                        raise FeasibilityFault('JOINT_LIMIT_CHECK_ERROR:'+str(limit))
                    if limit==0:
                        distance = sum((a-b)**2 for a,b in zip(candidate,q_in))
                        check['distance_squared_deg'] = distance
                        valid.append((distance,index,candidate))
                if chosen is None and valid:
                    _, index, chosen = min(valid)
                    out.update(selected_solver='all_solutions', selected_candidate_index=index)
            if chosen is None:
                out.update(status='REJECTED_IK', return_code=1,
                           reason='Fast and traversal failed; no valid all-solutions candidate for the exact target.')
            else:
                out.update(status='PASS_IK', return_code=0, selected_solution=chosen,
                           solution_joint_deg=chosen,
                           reason='Endpoint IK solution found; path/collision feasibility not certified.')
    except Exception as exc:
        out.update(status='CHECK_ERROR', reason=type(exc).__name__+':'+str(exc))
    out['latency_s'] = time.monotonic()-started
    return out

def binding(action,state):
    data={'action':action,'joint_deg':state['joint_deg'],'ee_pose':state['ee_pose'],
          'work_frame':state['work_frame'],'tool_frame':state['tool_frame'],'timestamp':state['timestamp']}
    return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()

def check_exact_target(session,action,observation, *, allow_shared_session=False):
    start=time.monotonic()
    arm=action['arm'];state=observation['canonical_states'][arm]
    a=parse(json.dumps(action,allow_nan=False),arm,state['work_frame']['id'],state['tool_frame']['id']);plan=command_plan(a,state)
    result={'status':'CHECK_ERROR','check_kind':'ENDPOINT_IK_ONLY','planner_status':'NOT_CHECKED_NO_INDEPENDENT_PLANNER',
            'motion_commands_sent':0,'original_target':copy.deepcopy(plan['arm']['pose']) if plan['arm'] else None,
            'frame':a['frame'],'tool_frame':a['tool_frame'],'seed_joint_deg':copy.deepcopy(state['joint_deg']),
            'binding':binding(a,state),'target_modified':False,'return_code':None,'raw_ik_return':None,
            'solution_joint_deg':None,'reason':None,'checker_function':'rm_algo_inverse_kinematics',
            'checker_flag':1,'units':{'joint':'deg','position':'m','rpy':'rad'}}
    try:
        if not plan['arm']:
            result.update(status='NOT_REQUIRED',reason='No arm motion requested');return result
        if arm not in session.connected or (not allow_shared_session and set(session.connected)!={arm}):raise FeasibilityFault('ARM_SESSION_MISMATCH')
        result.update(delta_xyz_m=copy.deepcopy(a['translation_m']),
                      delta_rpy_rad=copy.deepcopy(a['rotation_rpy_rad']))
        result.update(solve_exact_inputs(session,arm,state['joint_deg'],result['original_target']))
        return result
    except Exception as exc:
        result.update(status='CHECK_ERROR',reason=type(exc).__name__+':'+str(exc))
        return result
    finally:result['latency_s']=time.monotonic()-start

def require_exact_check(result,action,observation):
    state=observation['canonical_states'][action['arm']];plan=command_plan(action,state)
    expected='PASS_IK' if plan['arm'] else 'NOT_REQUIRED'
    if (not isinstance(result,dict) or result.get('status')!=expected or result.get('binding')!=binding(action,state)
        or result.get('original_target')!=(plan['arm']['pose'] if plan['arm'] else None) or result.get('target_modified') is not False):
        raise FeasibilityFault('MISSING_FAILED_OR_MISMATCHED_FEASIBILITY_CHECK')

def dispatch_checked(action,observation,check,executor_factory):
    """A rejected mathematical proposal never constructs a hardware executor."""
    if check['status']=='REJECTED_IK':
        if check.get('binding')!=binding(action,observation['canonical_states'][action['arm']]):
            raise FeasibilityFault('REJECTION_BINDING_MISMATCH')
        return {'status':'REJECTED_IK','executed_action':{'arm':None,'gripper':None},
                'sdk_result':{'called':False,'arm':None,'gripper':None},'hardware_commands_sent':0,'execution_latency_s':0}
    # No REJECTED_PLANNING fabricated: no independent trajectory checker exists here.
    require_exact_check(check,action,observation)
    return executor_factory().execute(action,observation,feasibility=check)
