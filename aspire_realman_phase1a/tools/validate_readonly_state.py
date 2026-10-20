"""Exercise the actual audited SDK reader using explicitly injected transport.

No vendor SDK import, ctypes library load or non-loopback connection. This is
entry/serialization/MCP validation, never real controller or pose validation.
"""
import argparse
import asyncio
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from serve_readonly_state import setup


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--aspire-source',type=Path,default=ROOT/'.cache/ASPIRE')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();verified=setup(a.aspire_source)
    from aspire_realman_live.sdk_state import SDKStateReader,prepare_reader,validate_onsite
    from aspire_realman_live.state_owner import SingleArmStateOwner
    from aspire_realman_live.source import host_clock_id
    from aspire_realman_live.runtime import build_live_runtime
    from aspire_realman_live.owner import save_raw_bundle
    from http_support import loopback_server
    import numpy as np
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    def guard(event,args):
        if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1'):
            raise PermissionError('OFFLINE_VALIDATION_ONLY_LOOPBACK')
        if event=='ctypes.dlopen' and args and 'libapi_c' in str(args[0]):
            raise PermissionError('NO_VENDOR_LIBRARY_LOAD_DURING_OFFLINE_VALIDATION')
    sys.addaudithook(guard)
    output=a.output.resolve();output.relative_to(ROOT);output.mkdir(parents=True,exist_ok=False)
    blocked=[]
    for flags in ({},{'powered':True},{'powered':True,'authorized':True}):
        try:validate_onsite('left','127.0.0.1',8080,**flags)
        except PermissionError as exc:blocked.append(str(exc))
        else:raise AssertionError('Onsite gate bypassed')
    historical_path=ROOT/'aspire_realman_phase0/evidence/replay_snapshot.json'
    original=historical_path.read_bytes();canonical=json.loads(original)['canonical_states']['left']
    codes=canonical['system_error']['codes']
    raw_work={'name':canonical['work_frame']['name'],'pose':canonical['work_frame']['pose']['xyz_m']+canonical['work_frame']['pose']['rpy_rad']}
    raw_tool={'name':canonical['tool_frame']['name'],'pose':canonical['tool_frame']['pose']['xyz_m']+canonical['tool_frame']['pose']['rpy_rad']}
    raw_state={'joint':canonical['joint_deg'],'pose':canonical['ee_pose']['xyz_m']+canonical['ee_pose']['rpy_rad'],
               'err':{'err_len':len(codes),'err':codes}}
    calls=[]
    class FakeRobot:
        changed=False
        work_reads=0
        def rm_get_current_work_frame(self):
            calls.append('rm_get_current_work_frame')
            FakeRobot.work_reads+=1
            frame=copy.deepcopy(raw_work)
            if FakeRobot.changed and FakeRobot.work_reads%2==0:frame['name']='changed_during_read'
            return 0,frame
        def rm_get_current_tool_frame(self):
            calls.append('rm_get_current_tool_frame');return 0,copy.deepcopy(raw_tool)
        def rm_get_current_arm_state(self):
            calls.append('rm_get_current_arm_state');return 0,copy.deepcopy(raw_state)
    class FakeSDK:
        class rm_thread_mode_e:RM_DUAL_MODE_E=2
        RoboticArm=FakeRobot
        @staticmethod
        def rm_init(mode):calls.append('rm_init');return 0
        @staticmethod
        def rm_create_robot_arm(host,port):
            calls.append('rm_create_robot_arm')
            return type('Handle',(),{'contents':type('Contents',(),{'id':123})()})()
        @staticmethod
        def rm_delete_robot_arm(handle):calls.append('rm_delete_robot_arm');return 0
        @staticmethod
        def rm_destroy():calls.append('rm_destroy');return 0
    folder=prepare_reader(output)
    owner=SingleArmStateOwner('offline-sdk-entry','left',source_kind='OFFLINE_SDK_TRANSPORT_FIXTURE',clock_id=host_clock_id())
    reader=SDKStateReader(owner,output,folder,'127.0.0.1',8080,injected_sdk=FakeSDK)
    evidence=[]
    async def wire(base,runtime):
        async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
            async with streamable_http_client(base+'/mcp/',http_client=client) as (read,write,_):
                async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=10)) as s:
                    await s.initialize()
                    names=sorted(t.name for t in (await s.list_tools()).tools)
                    assert 'cap_program_readonly_state' in names
                    evidence.append({'event':'tools/list','names':names})
                    value=await s.call_tool('cap_program_readonly_state',{})
                    assert not value.isError,value
                    payload=value.structuredContent['job']['result']['result']
                    assert payload['source']['kind']=='OFFLINE_SDK_TRANSPORT_FIXTURE'
                    assert payload['telemetry']['joint_positions_deg']==canonical['joint_deg']
                    assert payload['telemetry']['joint_velocity_deg_s'] is None and payload['telemetry']['gripper'] is None
                    assert payload['endpoint']['semantics_status']=='UNKNOWN'
                    assert payload['endpoint']['target_frame'] is None and not payload['endpoint']['is_actual_grasp_center']
                    assert payload['frames']['active_tool']['name']==canonical['tool_frame']['name']
                    assert payload['actual_grasp_tcp'] is None and payload['world_transform'] is None
                    assert not payload['quality']['live_host_time_eligible']
                    assert payload['query_ok'] and payload['ok'] and not payload['live_current']
                    assert payload['controller_measurement_freshness']=='UNVERIFIED'
                    assert not payload['native_robot_state_available']
                    evidence.append({'event':'readonly_state','result':value.structuredContent})
                    for name,args in [('observe',{'cameras':[]}),('cap_get_robot_state',{}),
                            ('cap_set_gripper',{'arm':'left','position':.5}),
                            ('cap_move_to_joints',{'arm':'left','target':[0]*6}),
                            ('cap_move_synchronized',{'targets':{'left':[0]*6}}),('cap_program_go_home',{})]:
                        r=await s.call_tool(name,args)
                        if name=='observe':
                            assert not r.isError and r.structuredContent['observation']['stale']
                            assert r.structuredContent['observation']['state']=={}
                        else:assert r.isError,(name,r)
                        evidence.append({'event':name,'isError':r.isError,'result':r.structuredContent})
                    cap=await s.call_tool('get_capability_graph',{})
                    assert not any(cap.structuredContent['configured_providers'].values())
                    evidence.append({'event':'capabilities','result':cap.structuredContent})
    with reader:
        packet=reader.poll_once()
        assert packet['sdk_sample']['canonical']['joint_deg']==canonical['joint_deg']
        assert packet['sdk_sample']['canonical']['ee_pose']['xyz_m']==canonical['ee_pose']['xyz_m']
        runtime=build_live_runtime(None,state_owner=owner)
        try:
            with loopback_server(runtime.app) as base:asyncio.run(wire(base,runtime))
            for name,fn in [('reset',lambda:runtime.adapter.reset()),('trajectory',lambda:runtime.adapter.execute_trajectory(None)),
                ('home',lambda:runtime.adapter.go_home()),('gripper',lambda:runtime.adapter.set_gripper(.5))]:
                try:r=fn()
                except Exception as exc:assert 'interlock' in str(type(exc)).lower() or 'physical' in str(exc).lower()
                else:assert not r.ok
            assert runtime.adapter.hardware_commands_sent==0
            # Actual five-call reader rejects a changed Work definition, records
            # failed sample and prevents previous state from remaining healthy.
            FakeRobot.changed=True
            try:reader.poll_once()
            except ValueError as exc:assert 'WORK_TOOL_CHANGED' in str(exc)
            else:raise AssertionError('Changed frame accepted')
            assert not owner.read(host_clock_id=host_clock_id())['quality']['owner_running']
            from cap_harness.agent.mcp import CapMcpBridge
            failed=CapMcpBridge(runtime.runtime.session).call('cap_program_readonly_state',{})
            assert not failed.isError  # Query retrieves the last diagnostic sample.
            diagnostic=failed.structuredContent['job']['result']['result']
            assert diagnostic['query_ok'] and not diagnostic['live_current']
            assert diagnostic['owner_error'] and not diagnostic['quality']['owner_running']
            assert diagnostic['controller_measurement_freshness']=='UNVERIFIED'
            assert runtime.runtime.session.visual_snapshot()['stale']
            evidence.append({'event':'changed_work_frame_cached_diagnostic_not_live','isError':False,'result':failed.structuredContent})
        finally:runtime.close()
    assert calls[-2:]==['rm_delete_robot_arm','rm_destroy']
    assert all(name in reader.module.ALLOWED for name in calls)
    latest=json.loads((output/'latest.json').read_text());assert not latest['quality']['owner_running']
    # Different shapes prove raw depth was stored independently, never renamed
    # aligned depth. Generated arrays verify serialization only, not real capture.
    raw_z=np.arange(12,dtype=np.uint16).reshape(3,4)
    aligned_z=np.arange(20,dtype=np.uint16).reshape(4,5)
    bundle=save_raw_bundle(output/'serialization-only',np.zeros((4,5,3),np.uint8),raw_z,
        np.zeros((4,5,3),np.uint8),aligned_z,aligned_z.astype(np.float32)*.001,
        {'source_kind':'SYNTHETIC_SERIALIZATION_CHECK_NOT_REAL_CAPTURE'}, {'depth_scale_m_per_z16':.001})
    assert np.array_equal(np.load(output/'serialization-only/raw-depth-z16.npy'),raw_z)
    assert np.load(output/'serialization-only/aligned-depth-z16.npy').shape!=(raw_z.shape)
    assert hashlib.sha256(historical_path.read_bytes()).digest()==hashlib.sha256(original).digest()
    report={'status':'AUDITED_READER_AND_NATIVE_MCP_OFFLINE_PASS_NOT_HARDWARE_ACCEPTANCE',
        'upstream_hashes_verified':verified,'source_kind':owner.source_kind,'arm_scope':['left'],
        'source_historical_sha256':hashlib.sha256(original).hexdigest(), 'onsite_gates_rejected':blocked,
        'injected_sdk_calls':calls,'mcp':evidence,'shutdown_owner_closed':owner.closed,
        'raw_bundle_serialization_only':bundle,'real_sdk_imports':[n for n in sys.modules if n.startswith('Robotic_Arm')],
        'physical_connections':0,'motion_dispatches':0,'real_camera_captures':0,'native_robot_state_available':False}
    (output/'validation.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({'status':report['status'],'report':str(output/'validation.json')}))


if __name__=='__main__':main()
