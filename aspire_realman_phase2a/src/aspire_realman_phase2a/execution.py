"""Timed Stub execution + explicit V17 endpoint contracts; ZERO hardware I/O.

Retains V17's single-use claim/no retry, preflight/feedback, error/stop semantics.
Does not import the lab executor (which would expose real dispatch) or task code.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
import numpy as np
from cap_harness.contracts import Trajectory,SynchronizedTrajectory,ExecutionResult
from cap_harness.errors import ApiError,ErrorCode
from .model import ARMS,NAMES


class PhysicalDispatch:
    """No SDK/socket implementation exists in Phase2A."""
    def __init__(self,*args,**kwargs):
        raise ApiError(ErrorCode.SAFETY_INTERLOCK,'PHYSICAL_REALMAN_DISPATCH_HARD_DISABLED_PHASE2A')


def v17_pose_contract(xyz_m,rpy_rad):
    xyz=np.asarray(xyz_m,float);rpy=np.asarray(rpy_rad,float)
    if xyz.shape!=(3,) or rpy.shape!=(3,) or not np.isfinite(np.r_[xyz,rpy]).all():raise ValueError('FINITE_M_RAD_POSE_REQUIRED')
    return {'protocol':'V17_VERIFIED_BLOCKING_ENDPOINT_ONLY','sdk_method':'rm_movej_p',
        'args':[np.r_[xyz,rpy].tolist(),1,0,0,1],'xyz_unit':'m','orientation_unit':'rad',
        'timed_trajectory':False,'dual_synchronization':False,'physical_dispatch_available':False}


def sdk_joint_endpoint_contract(joints_rad,*,speed_percent):
    """Audited SDK serialization only; NOT V17-verified joint-stream execution.

    rm_movej allocates arm_dof elements and accepts degrees. rm_movej_canfd
    instead allocates seven floats in this SDK even for RM65. We deliberately
    do not invent a six-axis padding convention or claim a timed stream here.
    """
    q=np.asarray(joints_rad,float)
    if q.shape!=(6,) or not np.isfinite(q).all() or type(speed_percent) is not int or not 1<=speed_percent<=100:
        raise ValueError('SIX_FINITE_RADIANS_AND_EXPLICIT_SPEED_PERCENT_REQUIRED')
    return {'sdk_method':'rm_movej','args':[np.rad2deg(q).tolist(),speed_percent,0,0,1],
        'input_unit':'rad','sdk_joint_unit':'deg','blocking_endpoint':True,'timed_trajectory':False,
        'dual_synchronization':False,'physical_dispatch_available':False,'physical_acceptance':'NOT_PERFORMED'}


def sdk_stream_sample_contract(joints_rad,*,relative_time_s,period_s,follow):
    """Serialize the audited Python SDK signature without calling it.

    Six native radians become six degree arguments. The existing Python SDK
    owns its seven-float C storage; its RM65 behavior is NOT physically tested.
    Shared scheduled times here do not create a controller-side sync trigger.
    """
    q=np.asarray(joints_rad,float)
    if q.shape!=(6,) or not np.isfinite(q).all() or type(follow) is not bool:
        raise ValueError('SIX_FINITE_RADIANS_AND_EXPLICIT_FOLLOW_MODE_REQUIRED')
    if not math.isfinite(period_s) or period_s<=0 or not math.isfinite(relative_time_s) or relative_time_s<0:
        raise ValueError('FINITE_NONNEGATIVE_TIME_AND_POSITIVE_PERIOD_REQUIRED')
    if follow and period_s>.01:raise ValueError('AUDITED_HIGH_FOLLOW_REQUIRES_PERIOD_AT_MOST_10MS')
    return {'sdk_method':'rm_movej_canfd','kwargs':{'joint':np.rad2deg(q).tolist(),'follow':follow,'expand':0.,'trajectory_mode':0,'radio':0},
        'relative_time_s':relative_time_s,'period_s':period_s,'sdk_joint_unit':'deg','source_joint_unit':'rad',
        'sdk_c_storage_floats':7,'native_joint_count':6,'rm65_c_storage_acceptance':'UNVERIFIED',
        'hardware_sync_trigger':None,'physical_dispatch_available':False,'validated_source':'SDK_SOURCE_ONLY_NOT_V17_TIMED_STREAM'}


def gripper_contract(arm,opening):
    if arm not in ARMS or isinstance(opening,bool) or not math.isfinite(opening) or not 0<=opening<=1:raise ValueError('NORMALIZED_SINGLE_ARM_OPENING_REQUIRED')
    return {'arm':arm,'opening_requested':float(opening),'wire_target':int(opening*1000),
        'v17_wire':{'command':'hand_follow_pos','hand_pos':[int(opening*1000)]},
        'required_ack':{'command':'hand_follow_pos','set_state':True},'retries':0,'grasp_confirmed':'UNKNOWN'}


def same_gripper_wire_hold(arm,requested,measured):
    """A hold is identical at V17 wire resolution, not at unquantized float q.

    Measured Stub feedback is an exact raw integer / 1000. Reject changes in
    effective wire target; never dispatch gripper changes in an arm trajectory.
    """
    raw=round(float(measured)*1000)
    if abs(float(measured)*1000-raw)>1e-7:return False
    return all(gripper_contract(arm,float(v))['wire_target']==raw for v in np.asarray(requested).reshape(-1))


class StubTransport:
    """Deterministic virtual-clock feedback, explicitly not a real controller."""
    def __init__(self,positions,*,timed_dual=True,fail_at=None,delay_at=None,cancel_at=None,pause_at=None):
        self.positions={a:np.array(positions[a],float).copy() for a in ARMS}
        self.openings={a:1. for a in ARMS};self.now_s=0.;self.timed_dual=timed_dual
        self.fail_at,self.delay_at,self.cancel_at=fail_at,delay_at or {},cancel_at
        self.events=[];self.cancel_event=threading.Event()
        self.pause_at=pause_at;self.tick_waiting=threading.Event();self.tick_release=threading.Event()
        self._dispatch_lock=threading.Lock()
    def abort(self):
        # Serialize the cancellation acknowledgement with packets. Once abort
        # returns, no future Stub packet can be appended, including a waiting tick.
        with self._dispatch_lock:self.cancel_event.set()
        self.tick_release.set()
    def tick(self,values,*,when,relative_time_s,period_s,sequence,request_id):
        if self.pause_at==sequence:
            self.tick_waiting.set()
            if not self.tick_release.wait(15.):raise ApiError(ErrorCode.TIMEOUT,'STUB_TEST_GATE_TIMEOUT')
        with self._dispatch_lock:
            if self.cancel_event.is_set():raise ApiError(ErrorCode.CANCELLED,'STUB_ABORT_LATCHED_BEFORE_PACKET')
            return self._tick(values,when=when,relative_time_s=relative_time_s,period_s=period_s,sequence=sequence,request_id=request_id)
    def _tick(self,values,*,when,relative_time_s,period_s,sequence,request_id):
        if len(values)>1 and not self.timed_dual:raise ApiError(ErrorCode.UNSUPPORTED,'TIMED_DUAL_STREAM_UNAVAILABLE_NO_ENDPOINT_RPC_FALLBACK')
        self.now_s=max(self.now_s,when)+self.delay_at.get(sequence,0.)
        if self.fail_at==sequence:raise ApiError(ErrorCode.CONTROLLER_FAILED,'INJECTED_STUB_CONTROLLER_ERROR',details={'stub_code':-1})
        contracts={a:sdk_stream_sample_contract(q,relative_time_s=relative_time_s,period_s=period_s,follow=False) for a,q in values.items()}
        # Stub exercises the exact unit-lowering/feedback path, never calls SDK.
        self.positions.update({a:np.deg2rad(c['kwargs']['joint']) for a,c in contracts.items()})
        event={'source':'STUB_FEEDBACK_NOT_REAL_SENSOR','request_id':request_id,'sequence':sequence,
            'scheduled_s':when,'feedback_s':self.now_s,'joint_names':{a:list(NAMES[a]) for a in values},
            'joint_positions_rad':{a:q.tolist() for a,q in self.positions.items()},'controller_error':0,
            'same_tick_arm_packet':list(values),'physical_commands_sent':0}
        event['sdk_contracts_not_dispatched']=contracts
        self.events.append(event)
        if self.cancel_at==sequence:self.cancel_event.set()
        return event
    def gripper(self,contract,request_id):
        with self._dispatch_lock:
            if self.cancel_event.is_set():raise ApiError(ErrorCode.CANCELLED,'STUB_ABORT_LATCHED_BEFORE_PACKET')
            return self._gripper(contract,request_id)
    def _gripper(self,contract,request_id):
        self.openings[contract['arm']]=contract['wire_target']/1000.
        event={'source':'STUB_GRIPPER_FEEDBACK_NOT_HARDWARE','request_id':request_id,'contract':contract,
            'ack':contract['required_ack'],'position_raw':contract['wire_target'],'physical_commands_sent':0}
        self.events.append(event);return event


class ExecutionEngine:
    def __init__(self,transport,manifest,ledger):
        if type(transport) is not StubTransport:raise ApiError(ErrorCode.SAFETY_INTERLOCK,'EXACT_STUB_TRANSPORT_REQUIRED')
        self.transport,self.manifest,self.ledger=transport,manifest,Path(ledger)
        self.ledger.mkdir(parents=True,exist_ok=False);self.lock=threading.Lock();self.last=None
    def claim(self,request_id,payload):
        key=hashlib.sha256(request_id.encode()).hexdigest()
        try:
            with (self.ledger/(key+'.claim.json')).open('x') as stream:
                json.dump({'request_id':request_id,'payload':payload,'retry_allowed':False,'physical_dispatch':False},stream,allow_nan=False)
                stream.flush();os.fsync(stream.fileno())
        except FileExistsError as exc:raise ApiError(ErrorCode.SAFETY_INTERLOCK,'DUPLICATE_DISPATCH_ID_CONSUMED_NO_RETRY') from exc
        return key
    def error(self,code,message,steps=0,**details):
        return ExecutionResult(ok=False,steps_executed=steps,error=ApiError(code,message,details=details),
            diagnostics={'execution_source':'STUB_ONLY','hardware_commands_sent':0,'physical_stop_verified':False,**details})
    def abort(self):
        self.transport.abort()
        return {'future_stub_ticks_cancelled':True,'physical_stop_verified':False,'hardware_commands_sent':0}
    def execute(self,trajectory,*,request_id=None,timeout_s=60.):
        if not isinstance(trajectory,(Trajectory,SynchronizedTrajectory)):return self.error(ErrorCode.INVALID_REQUEST,'NATIVE_TRAJECTORY_REQUIRED')
        if trajectory.expected_start.metadata.get('source_kind')!='SYNTHETIC_OFFLINE':return self.error(ErrorCode.SAFETY_INTERLOCK,'SYNTHETIC_EXPECTED_START_REQUIRED')
        sync=isinstance(trajectory,SynchronizedTrajectory)
        values=dict(trajectory.joint_positions) if sync else {trajectory.arm:trajectory.joint_positions}
        names=trajectory.joint_names if sync else {trajectory.arm:trajectory.joint_names}
        count=trajectory.waypoint_count if sync else len(trajectory.joint_positions)
        payload={'kind':'TIMED_DUAL_JOINT_CONTRACT' if sync else 'TIMED_SINGLE_JOINT_CONTRACT','dt_s':trajectory.dt_s,
            'relative_time_s':(np.arange(count)*trajectory.dt_s).tolist(),'joint_unit':'rad','time_unit':'s',
            'joint_positions_rad':{a:q.tolist() for a,q in values.items()},'joint_names':{a:list(n) for a,n in names.items()},
            'source_kind':'SYNTHETIC_OFFLINE','planner':trajectory.planner,'hardware_sdk_lowering':None}
        request_id=request_id or hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        if not math.isfinite(timeout_s) or timeout_s<=0:return self.error(ErrorCode.INVALID_REQUEST,'POSITIVE_TIMEOUT_REQUIRED')
        if not self.lock.acquire(blocking=False):return self.error(ErrorCode.SAFETY_INTERLOCK,'EXECUTOR_BUSY')
        steps=0;key=None
        try:
            try:
                if sync and (set(values)!=set(ARMS) or not self.transport.timed_dual):raise ApiError(ErrorCode.UNSUPPORTED,'TIMED_DUAL_REQUIRED_NO_SEQUENTIAL_ENDPOINT_RPC')
                if set(trajectory.expected_start.joint_positions)!=set(ARMS):raise ApiError(ErrorCode.INVALID_REQUEST,'BOTH_START_ARMS_REQUIRED')
                grippers=trajectory.gripper_positions
                grippers={} if grippers is None else dict(grippers) if sync else {trajectory.arm:grippers}
                if any(not same_gripper_wire_hold(a,g,self.transport.openings[a]) for a,g in grippers.items()):
                    raise ApiError(ErrorCode.UNSUPPORTED,'TRAJECTORY_GRIPPER_CHANGES_REQUIRE_SEPARATE_TOOL')
                for arm in ARMS:
                    if tuple(trajectory.expected_start.joint_names[arm])!=NAMES[arm]:raise ApiError(ErrorCode.INVALID_REQUEST,'JOINT_ORDER_MISMATCH')
                    if np.max(np.abs(trajectory.expected_start.joint_positions[arm]-self.transport.positions[arm]))>1e-5:raise ApiError(ErrorCode.STALE_PLAN,'START_STATE_CHANGED')
                for arm,q in values.items():
                    if arm not in ARMS or tuple(names[arm])!=NAMES[arm]:raise ApiError(ErrorCode.INVALID_REQUEST,'JOINT_ORDER_MISMATCH')
                    lim=self.manifest['joint_limits'][arm];lo=np.array([x['lower'] for x in lim]);hi=np.array([x['upper'] for x in lim]);vel=np.array([x['velocity'] for x in lim])
                    if not np.isfinite(q).all() or np.any(q<lo) or np.any(q>hi):raise ApiError(ErrorCode.INVALID_REQUEST,'JOINT_LIMIT_NO_CLIPPING')
                    if np.max(np.abs(q[0]-self.transport.positions[arm]))>1e-5:raise ApiError(ErrorCode.STALE_PLAN,'FIRST_SAMPLE_JUMP')
                    if count>1 and np.any(np.abs(np.diff(q,axis=0))/trajectory.dt_s>vel+1e-5):raise ApiError(ErrorCode.INVALID_REQUEST,'VELOCITY_LIMIT')
                key=self.claim(request_id,payload);start=self.transport.now_s;deadline=start+timeout_s
                wall_deadline=time.monotonic()+timeout_s
                for i in range(count):
                    if self.transport.cancel_event.is_set():raise ApiError(ErrorCode.CANCELLED,'ABORT_STOPS_FUTURE_STUB_TICKS_NOT_VERIFIED_HARDWARE_STOP')
                    when=start+i*trajectory.dt_s
                    if when>deadline or time.monotonic()>wall_deadline:raise ApiError(ErrorCode.TIMEOUT,'TRAJECTORY_TIMEOUT_BEFORE_TICK')
                    feedback=self.transport.tick({a:q[i] for a,q in values.items()},when=when,relative_time_s=i*trajectory.dt_s,period_s=trajectory.dt_s,sequence=i,request_id=request_id);steps+=1
                    if feedback['feedback_s']>deadline or time.monotonic()>wall_deadline:raise ApiError(ErrorCode.TIMEOUT,'FEEDBACK_TIMEOUT_NO_RETRY')
                    if feedback.get('controller_error')!=0:raise ApiError(ErrorCode.CONTROLLER_FAILED,'CONTROLLER_ERROR_FEEDBACK')
                    for arm,q in values.items():
                        if np.max(np.abs(self.transport.positions[arm]-q[i]))>1e-5:raise ApiError(ErrorCode.CONTROLLER_FAILED,'FEEDBACK_MISMATCH')
                result=ExecutionResult(ok=True,steps_executed=steps,diagnostics={'execution_source':'STUB_ONLY','hardware_commands_sent':0,
                    'request_id':request_id,'timed_dual_stub':sync,'hardware_synchronization_verified':False,'duration_s':(count-1)*trajectory.dt_s})
            except ApiError as exc:result=self.error(exc.code,exc.message,steps,**dict(exc.details))
            except (ValueError,KeyError,TypeError) as exc:result=self.error(ErrorCode.INVALID_REQUEST,str(exc),steps)
            except Exception as exc:result=self.error(ErrorCode.CONTROLLER_FAILED,'UNEXPECTED_STUB_TRANSPORT_EXCEPTION',steps,exception_type=type(exc).__name__,exception_message=str(exc))
            self.last=result
            if key:
                path=self.ledger/(key+'.result.json')
                with path.open('x') as stream:json.dump({'ok':result.ok,'error':None if result.error is None else {'code':result.error.code.value,'message':result.error.message},
                    'steps_executed':steps,'feedback':[e for e in self.transport.events if e['request_id']==request_id],'diagnostics':dict(result.diagnostics)},stream,indent=2,allow_nan=False)
            return result
        finally:self.lock.release()
    def set_gripper(self,opening,arm,*,request_id):
        if not self.lock.acquire(blocking=False):return self.error(ErrorCode.SAFETY_INTERLOCK,'EXECUTOR_BUSY')
        key=None
        try:
            try:
                contract=gripper_contract(arm,opening);key=self.claim(request_id,contract)
                if self.transport.cancel_event.is_set():raise ApiError(ErrorCode.CANCELLED,'STUB_ABORT_LATCHED')
                reply=self.transport.gripper(contract,request_id)
                if reply['ack']!=contract['required_ack'] or reply['position_raw']!=contract['wire_target']:raise ApiError(ErrorCode.CONTROLLER_FAILED,'GRIPPER_ACK_OR_FEEDBACK_MISMATCH')
                result=ExecutionResult(ok=True,steps_executed=1,diagnostics={'execution_source':'STUB_ONLY','contract':contract,'hardware_commands_sent':0,'grasp_confirmed':'UNKNOWN'})
            except (ApiError,ValueError,TypeError) as exc:
                result=self.error(exc.code if isinstance(exc,ApiError) else ErrorCode.INVALID_REQUEST,str(exc))
            except Exception as exc:result=self.error(ErrorCode.CONTROLLER_FAILED,'UNEXPECTED_STUB_GRIPPER_EXCEPTION',exception_type=type(exc).__name__,exception_message=str(exc))
            self.last=result
            if key:
                with (self.ledger/(key+'.result.json')).open('x') as stream:
                    json.dump({'ok':result.ok,'error':None if result.error is None else {'code':result.error.code.value,'message':result.error.message},
                        'feedback':[e for e in self.transport.events if e['request_id']==request_id],
                        'diagnostics':dict(result.diagnostics)},stream,indent=2,allow_nan=False)
            return result
        finally:self.lock.release()
