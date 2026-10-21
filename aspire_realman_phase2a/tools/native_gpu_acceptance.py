"""One synthetic integration run: native MCP -> CAP -> real cuRobo -> timed Stub.

No task agent/model, SDK, physical sockets or camera owners are started.
Full wire/trajectory evidence stays at --output on the execution host.
"""
import argparse,asyncio,json,os,sys,time,traceback
from datetime import timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'aspire_realman_phase2a/src'),str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src'),str(ROOT/'.cache/curobo'),str(ROOT/'aspire_realman_phase05/tests')]

def replay_gpu_trajectory_faults(trajectory,manifest,output):
    """Inject faults into the actual successful cuRobo trajectory, not hand q."""
    import numpy as np
    from aspire_realman_phase2a.execution import ExecutionEngine,StubTransport
    from cap_harness.errors import ErrorCode
    output.mkdir(exist_ok=False);tests={}
    for name in ('timeout','controller_error','unexpected_exception','feedback_mismatch','controller_error_feedback','duplicate','state_changed','no_dual_fallback'):
        positions=trajectory.expected_start.joint_positions
        t=StubTransport(positions,timed_dual=name!='no_dual_fallback',fail_at=3 if name=='controller_error' else 0 if name=='duplicate' else None)
        engine=ExecutionEngine(t,manifest,output/name)
        if name=='state_changed':t.positions['right'][0]+=.001
        original=t._tick
        if name in ('unexpected_exception','feedback_mismatch','controller_error_feedback'):
            def tick(*args,**kwargs):
                if kwargs['sequence']==3 and name=='unexpected_exception':raise RuntimeError('INJECTED_UNEXPECTED_STUB_EXCEPTION')
                value=original(*args,**kwargs)
                if kwargs['sequence']==3 and name=='feedback_mismatch':t.positions['left'][0]+=.001
                if kwargs['sequence']==3 and name=='controller_error_feedback':value['controller_error']=-2
                return value
            t._tick=tick
        result=engine.execute(trajectory,request_id='actual-gpu-replay:'+name,timeout_s=.075 if name=='timeout' else 60.)
        if name=='duplicate':
            t.fail_at=None;result=engine.execute(trajectory,request_id='actual-gpu-replay:'+name)
        expected=ErrorCode.TIMEOUT if name=='timeout' else ErrorCode.STALE_PLAN if name=='state_changed' else ErrorCode.UNSUPPORTED if name=='no_dual_fallback' else ErrorCode.SAFETY_INTERLOCK if name=='duplicate' else ErrorCode.CONTROLLER_FAILED
        stopped=len(t.events);claim_count=len(list(engine.ledger.glob('*.claim.json')))
        tests[name]={'ok':not result.ok and result.error.code==expected and stopped<trajectory.waypoint_count,
            'status':result.status.value,'error':result.error.code.value,'steps_executed':result.steps_executed,'stub_ticks':stopped,
            'claim_count':claim_count,'trajectory_origin':'ACTUAL_CUROBO_GPU_NATIVE_CAP_RESAMPLED','hardware_commands_sent':0}
    (output/'summary.json').write_text(json.dumps(tests,indent=2))
    return {'ok':all(v['ok'] for v in tests.values()),'category':'ACTUAL_GPU_TRAJECTORY_FAULT_REPLAY_STUB_ONLY','cases':tests}

def main():
    def hardware_guard(event,args):
        if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):
            raise RuntimeError('OFFLINE_RUN_FORBIDS_NON_LOOPBACK_CONNECTION')
        if event=='import' and args[0].startswith(('Robotic_Arm','realman_api2')):
            raise RuntimeError('OFFLINE_RUN_FORBIDS_HARDWARE_SDK_IMPORT')
        if event=='ctypes.dlopen' and args[0] and 'libapi_c' in str(args[0]):
            raise RuntimeError('OFFLINE_RUN_FORBIDS_REALMAN_LIBRARY_LOAD')
    sys.addaudithook(hardware_guard)
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--warp-cubin',action='store_true');p.add_argument('--phase2b-controls',action='store_true');a=p.parse_args()
    a.output.resolve().relative_to(ROOT);a.output.mkdir(parents=True,exist_ok=False)
    summary={'scope':'SYNTHETIC_OFFLINE_ONLY','hardware_commands_sent':0,'tests':{},'ok':False}
    wire=[];runtime=None
    def save():
        (a.output/'wire.json').write_text(json.dumps(wire,indent=2))
        (a.output/'summary.json').write_text(json.dumps(summary,indent=2))

    try:
        import numpy as np,torch,warp as wp,httpx,requests
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from http_support import loopback_server
        from aspire_realman_phase2a.model import load_manifest,ARMS,NAMES,FRAME
        from aspire_realman_phase2a.runtime import build_runtime
        from cap_harness.providers.curobo.client import CuRoboProvider
        from cap_harness.providers.curobo import service
        import curobo._src.runtime as cr
        cr.cache_dir=str(ROOT/'.cache/curobo-runtime');wp.config.kernel_cache_dir=str(ROOT/'.cache/warp')
        if a.warp_cubin:wp.config.cuda_output='cubin'
        torch.cuda.reset_peak_memory_stats();os.environ['ASPIRE_REALMAN_MODEL_MANIFEST']=str(a.manifest)
        summary['environment']={'torch':torch.__version__,'cuda_runtime':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),
            'warp':wp.__version__,'cuda_home':os.environ.get('CUDA_HOME'),'curobo_commit':'a35a708ecfbb26eb9ab2d7ef22c65919c4fae4a9'}
        m=load_manifest(a.manifest)
        summary['model_scope']=m.get('diagnostic_scope','FULL_ASSEMBLY_UNVERIFIED')
        summary['model_manifest']=str(a.manifest)
        http=requests.Session();http.trust_env=False
        def capture(response,*args,**kwargs):
            row={'url':response.url,'status':response.status_code,'elapsed_s':response.elapsed.total_seconds(),
                'request':json.loads(response.request.body or '{}')}
            try:row['response']=response.json()
            except ValueError:row['response_text']=response.text
            wire.append(row);save()
        http.hooks['response'].append(capture)
        with loopback_server(service.app) as provider_url:
            provider=CuRoboProvider(provider_url,timeout_s=(10,600),max_retries=0,session=http)
            runtime=build_runtime(m,a.output/'stub-ledger',provider)
            def pose_mapping(q,arm):
                pose=runtime.adapter.fk.poses(q)[arm]
                return {'position':pose.position.tolist(),'quaternion_wxyz':pose.quaternion_wxyz.tolist(),'frame':FRAME}
            async def flow(base):
                async with httpx.AsyncClient(trust_env=False,timeout=650) as client:
                    async with streamable_http_client(base+'/mcp/',http_client=client) as (read,write,_):
                        async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=650)) as session:
                            initialized=await session.initialize();listing=await session.list_tools()
                            names=sorted(t.name for t in listing.tools)
                            summary['mcp']={'protocol_version':initialized.protocolVersion,'tools':names}
                            required={'cap_move_to_joints','cap_move_to_pose','cap_move_synchronized','cap_set_gripper','cap_get_robot_state'}
                            summary['tests']['discovery']={'ok':required<=set(names),'category':'NATIVE_MCP_PROTOCOL'}
                            async def call(name,args=None,category='ACTUAL_CUROBO_GPU_THEN_STUB'):
                                t=time.perf_counter()
                                try:
                                    r=await session.call_tool(name,args or {})
                                    wire.append({'tool':name,'arguments':args or {},'isError':bool(r.isError),'structuredContent':r.structuredContent})
                                    data=r.structuredContent or {};value=data.get('job',{}).get('result',data.get('result',{}))
                                    okay=not r.isError and (not isinstance(value,dict) or value.get('ok',True))
                                    row={'ok':bool(okay),'category':category,'elapsed_s':time.perf_counter()-t,'result':value}
                                    summary['tests'][name]=row;save();return row
                                except Exception as exc:
                                    summary['tests'][name]={'ok':False,'category':category,'error':repr(exc),'traceback':traceback.format_exc()};save()
                                    return summary['tests'][name]
                            await call('cap_get_robot_state',category='STUB_FEEDBACK_NATIVE_MCP')
                            await call('observe',{'cameras':['synthetic_overhead']},'SYNTHETIC_IMAGE_NATIVE_MCP')
                            q={arm:v.copy() for arm,v in runtime.adapter.get_robot_state().joint_positions.items()};q['left'][0]+=.04
                            from cap_harness.geometry import pose_from_mapping
                            t=time.perf_counter();ik=runtime.api.solve_ik(pose_from_mapping(pose_mapping(q,'left')),arm='left',backend='curobo')
                            summary['tests']['native_cap_ik']={'ok':ik.ok,'category':'ACTUAL_CUROBO_GPU_IK_NATIVE_CAP',
                                'elapsed_s':time.perf_counter()-t,'joint_positions':None if ik.joint_positions is None else ik.joint_positions.tolist(),
                                'error':None if ik.error is None else {'code':ik.error.code.value,'message':ik.error.message,'details':dict(ik.error.details)}}
                            await call('cap_move_to_joints',{'target':q['left'].tolist(),'arm':'left','max_steps':120})
                            q={arm:v.copy() for arm,v in runtime.adapter.get_robot_state().joint_positions.items()};q['left'][2]+=.035
                            strategy={'ik_solver':'curobo','trajectory_planner':'curobo','pose_planner':'curobo-integrated'}
                            await call('cap_move_to_pose',{'target_pose':pose_mapping(q,'left'),'arm':'left','max_steps':300,'strategy':strategy})
                            q={arm:v.copy() for arm,v in runtime.adapter.get_robot_state().joint_positions.items()}
                            q['left'][0]+=.025;q['right'][0]-=.03
                            await call('cap_move_synchronized',{'targets':{arm:pose_mapping(q,arm) for arm in ARMS},'max_steps':300,'strategy':strategy})
                            await call('cap_set_gripper',{'position':.4329,'arm':'left'},'STUB_V17_GRIPPER_CONTRACT_ONLY')
                            await call('cap_get_robot_state',category='STUB_FEEDBACK_NATIVE_MCP')
                            if a.phase2b_controls:
                                from cap_harness.contracts import Pose
                                t=time.perf_counter()
                                bad_ik=runtime.api.solve_ik(Pose(np.array([100.,0.,0.]),np.array([1.,0.,0.,0.]),FRAME),arm='left',backend='curobo')
                                summary['tests']['unreachable_ik_negative']={'ok':not bad_ik.ok and bad_ik.error is not None and bad_ik.error.details.get('status_code')==422 and 'unreachable' in bad_ik.error.message,'category':'ACTUAL_CUROBO_GPU_UNREACHABLE_IK',
                                    'elapsed_s':time.perf_counter()-t,'error':None if bad_ik.error is None else {'code':bad_ik.error.code.value,'message':bad_ik.error.message,'details':dict(bad_ik.error.details)}}
                                if not runtime.adapter.trajectories:raise RuntimeError('NO_SUCCESSFUL_GPU_TRAJECTORY_FOR_CONTROL_ACCEPTANCE')
                                actual=runtime.adapter.trajectories[-1]
                                np.savez(a.output/'actual-gpu-synchronized-resampled.npz',**dict(actual.joint_positions),dt_s=actual.dt_s)
                                summary['tests']['gpu_trajectory_fault_replay']=replay_gpu_trajectory_faults(actual,m,a.output/'gpu-trajectory-faults')
                                # Cancel the real native MCP job while its actual GPU
                                # trajectory is held before a middle Stub packet.
                                transport=runtime.adapter.transport;transport.pause_at=8
                                transport.tick_waiting.clear();transport.tick_release.clear()
                                q={arm:v.copy() for arm,v in runtime.adapter.get_robot_state().joint_positions.items()}
                                q['left'][0]+=.025;q['right'][0]-=.025
                                args={'targets':{arm:pose_mapping(q,arm) for arm in ARMS},'max_steps':300,'strategy':strategy}
                                before=len(transport.events)
                                pending=asyncio.create_task(session.call_tool('cap_move_synchronized',args))
                                try:
                                    waiting=await asyncio.to_thread(transport.tick_waiting.wait,15.)
                                    if not waiting:
                                        if pending.done():
                                            early=pending.result();wire.append({'early_cancel_action_response':early.structuredContent});save()
                                        raise RuntimeError('NATIVE_GPU_TRAJECTORY_DID_NOT_REACH_MIDDLE_GATE')
                                    status=await session.call_tool('get_job',{})
                                    job_id=status.structuredContent['job']['id']
                                    wrong=await client.post(base+'/jobs/not-the-active-job/cancel')
                                    cancel=await session.call_tool('cancel_job',{'job_id':job_id})
                                    acknowledged=len(transport.events)
                                    action=await asyncio.wait_for(pending,timeout=15.)
                                    result=action.structuredContent['job']['result']
                                    terminal=action.structuredContent['job']
                                    after=len(transport.events)
                                    provider_calls_before=len([r for r in wire if 'url' in r])
                                    rejected=await session.call_tool('cap_move_synchronized',args)
                                    stale_cancel=await client.post(base+'/jobs/'+job_id+'/cancel')
                                    provider_calls_after=len([r for r in wire if 'url' in r])
                                    row={'ok':bool(waiting and not cancel.isError and result['status']=='cancelled'
                                        and terminal['cancellation_requested'] and acknowledged==after==len(transport.events)
                                        and 0<after-before<runtime.adapter.trajectories[-1].waypoint_count
                                        and rejected.isError and provider_calls_before==provider_calls_after and wrong.status_code==409 and stale_cancel.status_code==409),
                                        'category':'NATIVE_MCP_SESSION_CANCEL_ACTUAL_GPU_TRAJECTORY_STUB_ABORT',
                                        'job_id':job_id,'ticks_before_job':before,'ticks_at_cancel_ack':acknowledged,'ticks_after_terminal':after,
                                        'planned_waypoints':runtime.adapter.trajectories[-1].waypoint_count,
                                        'executed_job_ticks':after-before,'terminal_result':result,
                                        'cancel_receipt':cancel.structuredContent,'wrong_job_http_status':wrong.status_code,'finished_job_http_status':stale_cancel.status_code,
                                        'post_cancel_action_rejected':rejected.isError,'post_cancel_provider_calls':provider_calls_after-provider_calls_before,
                                        'physical_stop_verified':False,'hardware_commands_sent':0}
                                    summary['tests']['native_session_cancel']=row
                                    wire.append({'native_cancel_arguments':args,'cancel_response':cancel.structuredContent,'cancelled_action_response':action.structuredContent,'post_cancel_action_response':rejected.structuredContent})
                                finally:
                                    transport.abort()
                                    if not pending.done():await asyncio.wait_for(pending,timeout=15.)
            with loopback_server(runtime.app) as mcp_url:asyncio.run(flow(mcp_url))
            summary['post_resample_gpu_checks']=runtime.adapter.validator.records
            summary['stub_feedback_events']=len(runtime.adapter.transport.events)
            (a.output/'stub-feedback.json').write_text(json.dumps(runtime.adapter.transport.events,indent=2))
            summary['operation_controller_events']=runtime.runtime.session._operation_controller.events
            # Reject malformed physical/fake calibration and joint limit inputs at native HTTP boundary.
            payload=provider._base_payload(runtime.adapter.get_robot_state(),runtime.adapter.get_planning_context())
            for label,mutate in [('limit',lambda x:x['joint_positions']['left'].__setitem__(0,10.)),
                                 ('joint_order',lambda x:x['joint_names']['left'].reverse()),
                                 ('unverified_world',lambda x:x.__setitem__('base_frame','World'))]:
                import copy
                bad=copy.deepcopy(payload);mutate(bad);bad.update(arm='left',target={'type':'joints','joint_positions':m['default_positions']['left']})
                r=http.post(provider_url+'/plan',json=bad,timeout=15)
                summary['tests']['reject_'+label]={'ok':r.status_code==400,'category':'NATIVE_PROVIDER_VALIDATION','status':r.status_code,'body':r.text}
            # Same actual GPU model, explicit enclosing mesh: scene collision must reject it.
            try:
                import trimesh
                from curobo.scene import Scene,Mesh
                planner=service._planner(service.BaseRequest(**payload));service._purge_scene_mesh_cache(planner)
                box=trimesh.creation.box(extents=[4.,4.,4.])
                planner.update_world(Scene(mesh=[Mesh(name='negative_enclosing_box',pose=[0,0,0,1,0,0,0],vertices=box.vertices.tolist(),faces=box.faces.tolist())]))
                q=torch.tensor([sum([payload['joint_positions'][arm] for arm in ARMS],[])],device='cuda',dtype=torch.float32)
                mask=planner.graph_planner.check_samples_feasibility(q).detach().cpu().numpy().reshape(-1)
                details=service._configuration_constraint_detail(planner,service._state(service.BaseRequest(**payload),planner))
                scene_term=details.get('constraint:scene_collision',{}).get('maximum',0)
                summary['tests']['scene_collision_negative']={'ok':not bool(mask.any()) and scene_term>0,'category':'ACTUAL_CUROBO_GPU_SCENE_TERM',
                    'feasible':mask.tolist(),'constraint_detail':details,'note':'Scene term must be positive; false feasibility alone is confounded by any model self-collision.'}
            except Exception as exc:summary['tests']['scene_collision_negative']={'ok':False,'error':str(exc),'traceback':traceback.format_exc()}
        summary['ok']=all(row['ok'] for row in summary['tests'].values())
    except BaseException as exc:
        summary['error']={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()};traceback.print_exc()
    finally:
        if runtime:runtime.close()
        summary['loaded_hardware_modules']=[n for n in sys.modules if n.startswith(('Robotic_Arm','realman_api2'))]
        try:summary['peak_allocated_bytes']=torch.cuda.max_memory_allocated();summary['peak_reserved_bytes']=torch.cuda.max_memory_reserved()
        except Exception:pass
        save();print(json.dumps({k:v for k,v in summary.items() if k!='tests'},indent=2))
    raise SystemExit(0 if summary['ok'] else 1)


if __name__=="__main__":main()
