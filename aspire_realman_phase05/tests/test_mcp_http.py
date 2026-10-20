"""Real native Streamable HTTP MCP protocol, no SDK/robot/camera/model services."""
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import unittest
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from aspire_realman import RealManAdapter, ReplaySource, build_realman_runtime
from aspire_realman.fixtures import synthetic_station, MockSegmentation
from http_support import loopback_server
from test_native_adapter import historical_scope
ROOT=Path(__file__).resolve().parents[2]
WIRE_EVIDENCE=[]


async def session_flow(base, callback):
    async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
        health=await client.get(base+'/health');health.raise_for_status()
        async with streamable_http_client(base+'/mcp/',http_client=client) as (read,write,_):
            async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=10)) as session:
                init=await session.initialize()
                WIRE_EVIDENCE.append({'event':'initialize','protocol_version':init.protocolVersion,'server':init.serverInfo.model_dump()})
                await callback(session,client)


def wire_summary(value):
    if value is None:
        return None
    # Keep contract evidence, avoid repeating complete observation/job state on every call.
    result = {k:value[k] for k in ['ok','error','result','image_cameras','messages'] if k in value}
    if 'job' in value and value['job']:
        job=value['job']
        result['job']={k:job[k] for k in ['kind','label','active','error','result'] if k in job}
    if 'observation' in value:
        obs=value['observation']
        result['observation']={k:obs[k] for k in ['stale','monitor_error','camera_metadata'] if k in obs}
    if 'tools' in value:
        result['tool_names']=[t['name'] for t in value['tools']]
    return result


async def call(session,name,args=None):
    result=await session.call_tool(name,args or {})
    WIRE_EVIDENCE.append({'event':'tools/call','name':name,'isError':bool(result.isError),
        'image_count':sum(c.type=='image' for c in result.content),'structuredContent':wire_summary(result.structuredContent)})
    return result


class NativeMcpHttpTests(unittest.TestCase):
    def setUp(self):
        source,config=synthetic_station()
        self.runtime=build_realman_runtime(source,config,segmentation_provider=MockSegmentation())

    def tearDown(self):
        self.assertEqual(self.runtime.adapter.hardware_commands_sent,0)
        self.runtime.close()

    def test_discovery_observe_state_and_mock_localization(self):
        async def check(session,client):
            listing=await session.list_tools();names={t.name for t in listing.tools}
            WIRE_EVIDENCE.append({'event':'tools/list','names':sorted(names)})
            expected={'observe','get_capability_graph','cap_get_robot_state','cap_localize_object','cap_move_to_pose','cap_move_synchronized','cap_move_to_joints','cap_set_gripper'}
            self.assertTrue(expected<=names)
            caps=await call(session,'get_capability_graph');self.assertFalse(caps.isError)
            obs=await call(session,'observe',{'cameras':['synthetic_overhead']})
            self.assertFalse(obs.isError);self.assertEqual(sum(c.type=='image' for c in obs.content),1)
            self.assertEqual(obs.structuredContent['observation']['camera_metadata']['synthetic_overhead']['source_kind'],'SYNTHETIC')
            state=await call(session,'cap_get_robot_state')
            self.assertFalse(state.isError)
            self.assertEqual(state.structuredContent['result']['embodiment'],'realman')
            self.assertFalse(state.structuredContent['result']['metadata']['motion_permitted'])
            loc=await call(session,'cap_localize_object',{'query':'generic synthetic object'})
            self.assertFalse(loc.isError,str(loc.structuredContent))
            self.assertTrue(loc.structuredContent['result']['ok'])
        with loopback_server(self.runtime.app) as base:asyncio.run(session_flow(base,check))

    def test_all_native_motion_tools_refuse_over_http(self):
        pose={'position':[.1,.2,.3],'rpy_deg':[0,0,90],'frame':'synthetic:work'}
        requests=[('cap_set_gripper',{'position':.2,'arm':'left'}),
                  ('cap_move_to_joints',{'target':[0]*6,'arm':'right'}),
                  ('cap_move_to_pose',{'target_pose':pose,'arm':'left'}),
                  ('cap_move_synchronized',{'targets':{'left':pose,'right':pose}}),
                  ('cap_program_go_home',{})]
        async def check(session,client):
            for name,args in requests:
                result=await call(session,name,args)
                self.assertTrue(result.isError, (name,result.structuredContent))
                self.assertFalse(result.structuredContent['ok'])
            # Home program's first gripper request is refused; it never reaches Home.
            self.assertNotIn('go_home',[r['operation'] for r in self.runtime.adapter.refusals])
            self.assertEqual(self.runtime.adapter.hardware_commands_sent,0)
        with loopback_server(self.runtime.app) as base:asyncio.run(session_flow(base,check))

    def test_invalid_pose_and_missing_camera_are_errors_not_dispatch(self):
        async def check(session,client):
            bad={'position':[0,0,0],'quaternion_wxyz':[0,0,0,0],'frame':'synthetic:work'}
            self.assertTrue((await call(session,'cap_move_to_pose',{'target_pose':bad,'arm':'left'})).isError)
            self.assertTrue((await call(session,'observe',{'cameras':['does_not_exist']})).isError)
            self.assertEqual(self.runtime.adapter.refusals,())
        with loopback_server(self.runtime.app) as base:asyncio.run(session_flow(base,check))

    def test_steering_and_job_terminal_are_native(self):
        async def check(session,client):
            steer=await client.post(base+'/steer',json={'message':'Remain observation only.'})
            self.assertEqual(steer.status_code,200)
            messages=await call(session,'read_operator_messages');self.assertFalse(messages.isError)
            result=await call(session,'cap_set_gripper',{'position':.2,'arm':'right'})
            job=result.structuredContent['job'];self.assertFalse(job['active'])
            status=await call(session,'get_job',{'job_id':job['id']})
            self.assertFalse(status.isError)
            self.assertFalse(status.structuredContent['job']['result']['ok'])
        with loopback_server(self.runtime.app) as base:asyncio.run(session_flow(base,check))


class HistoricalMcpHttpTests(unittest.TestCase):
    def test_historical_native_state_and_missing_pixels(self):
        source=ReplaySource(ROOT/'aspire_realman_phase0/evidence/replay_snapshot.json')
        runtime=build_realman_runtime(source,historical_scope(source))
        async def check(session,client):
            state=await call(session,'cap_get_robot_state')
            self.assertFalse(state.isError)
            value=state.structuredContent['result'];self.assertEqual(value['base_frame'],'realman:left:work:World')
            self.assertEqual(set(value['joint_positions']),{'left'})
            self.assertEqual(value['metadata']['joint_velocity_quality']['left'],'UNMEASURED_NUMERIC_PLACEHOLDER')
            self.assertTrue((await call(session,'observe',{'cameras':['left_wrist']})).isError)
            self.assertTrue((await call(session,'cap_set_gripper',{'position':.5,'arm':'left'})).isError)
        try:
            with loopback_server(runtime.app) as base:asyncio.run(session_flow(base,check))
            self.assertEqual(runtime.adapter.hardware_commands_sent,0)
        finally:runtime.close()
