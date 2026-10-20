"""Metadata semantics only: deterministic injected clocks/data, never live evidence."""
import asyncio
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aspire_realman_live.state_owner import SingleArmStateOwner, READ_LABELS
from aspire_realman_live.state_runtime import SingleArmReadOnlyAdapter
from aspire_realman_live.runtime import build_live_runtime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'aspire_realman_phase05/tests'))


def make_owner(kind='LIVE_SDK_READ_ONLY'):
    return SingleArmStateOwner('OFFLINE_UNIT_INJECTION_NOT_REAL_OWNER', 'left',
        source_kind=kind, clock_id='unit-injected-clock')


def publish(owner):
    raw = copy.deepcopy(json.loads((ROOT/'aspire_realman_phase0/evidence/replay_snapshot.json').read_text())['canonical_states']['left'])
    raw['timestamp'] = 2000.0  # Synthetic clock fixture, not refreshed real telemetry.
    raw.pop('gripper_state', None)
    sample = {'arm':'left', 'canonical':raw, 'calls':{k:{'return_code':0} for k in READ_LABELS}}
    owner.publish(sample, owner_id=owner.owner_id, sequence=1,
        read_interval_monotonic_s=[500.0,500.01], host_clock_id=owner.clock_id)


class StateMetadataTests(unittest.TestCase):
    def test_query_success_does_not_imply_live_or_controller_freshness(self):
        cases = [('fresh_injected_live', 'LIVE_SDK_READ_ONLY', 500.2,2000.2,'unit-injected-clock',True),
                 ('old_receipt', 'LIVE_SDK_READ_ONLY', 502.0,2000.2,'unit-injected-clock',False),
                 ('old_sdk_return', 'LIVE_SDK_READ_ONLY', 500.2,2002.0,'unit-injected-clock',False),
                 ('foreign_clock', 'LIVE_SDK_READ_ONLY', 500.2,2000.2,'different-boot',False),
                 ('closed_owner', 'LIVE_SDK_READ_ONLY', 500.2,2000.2,'unit-injected-clock',False),
                 ('historical', 'HISTORICAL_REPLAY',500.2,2000.2,'unit-injected-clock',False),
                 ('transport_fixture', 'OFFLINE_SDK_TRANSPORT_FIXTURE',500.2,2000.2,'unit-injected-clock',False)]
        for label,kind,mono,wall,clock,expected in cases:
            with self.subTest(label=label):
                owner=make_owner(kind);publish(owner)
                if label=='closed_owner':owner.close()
                result=owner.read(now_monotonic_s=mono,now_epoch_s=wall,host_clock_id=clock)
                self.assertTrue(result['query_ok'])
                self.assertEqual(result['live_current'],expected)
                self.assertEqual(result['quality']['live_host_time_eligible'],expected)
                self.assertEqual(result['controller_measurement_freshness'],'UNVERIFIED')
                self.assertFalse(result['quality']['device_measurement_freshness_verified'])
                self.assertFalse(result['quality']['controller_timestamp_or_latency_bound_available'])
                self.assertEqual(result['canonical_state']['timestamp'],2000.0)
                if clock!='unit-injected-clock':
                    self.assertIsNone(result['quality']['source_epoch_age_s'])

    def test_native_http_reports_cached_failure_without_claiming_current(self):
        from http_support import loopback_server
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        owner=make_owner()
        clock=SimpleNamespace(monotonic=lambda:500.2,time=lambda:2000.2)
        async def query(base,runtime):
            async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
                async with streamable_http_client(base+'/mcp/',http_client=client) as (read,write,_):
                    async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=10)) as s:
                        await s.initialize()
                        empty=await s.call_tool('cap_program_readonly_state',{})
                        self.assertTrue(empty.isError)  # No payload = query failed, no defaults.
                        publish(owner)
                        async def payload(expected_live):
                            call=await s.call_tool('cap_program_readonly_state',{})
                            self.assertFalse(call.isError)
                            value=call.structuredContent['job']['result']['result']
                            self.assertTrue(value['query_ok']);self.assertIs(value['ok'],True)
                            self.assertEqual(value['live_current'],expected_live)
                            self.assertEqual(value['controller_measurement_freshness'],'UNVERIFIED')
                            self.assertFalse(value['quality']['device_measurement_freshness_verified'])
                            self.assertFalse(value['motion_permitted'])
                            self.assertFalse(value['full_cap_observation_available'])
                            self.assertIsNone(value['actual_grasp_tcp'])
                            self.assertEqual(value['timestamps']['source_epoch_s'],2000.0)
                            return value
                        await payload(True)  # Explicit offline clock/return-code branch injection.
                        clock.monotonic=lambda:503.0
                        await payload(False)
                        stale=await s.call_tool('observe',{'cameras':[]})
                        self.assertTrue(stale.structuredContent['observation']['stale'])
                        clock.monotonic=lambda:500.2
                        owner.fail('OFFLINE_INJECTED_CONNECTION_FAILURE')
                        failed=await payload(False)
                        self.assertFalse(failed['quality']['owner_running'])
                        self.assertEqual(failed['owner_error'],'OFFLINE_INJECTED_CONNECTION_FAILURE')
                        owner.close()
                        await payload(False)
                        typed=await s.call_tool('cap_get_robot_state',{})
                        self.assertTrue(typed.isError)
        # Replace ONLY this module's clock binding, never the process-wide clock.
        with patch('aspire_realman_live.state_owner.time',clock), patch(
                'aspire_realman_live.state_runtime.current_clock_id',return_value='unit-injected-clock'):
            runtime=build_live_runtime(None,state_owner=owner)
            try:
                with loopback_server(runtime.app) as base:asyncio.run(query(base,runtime))
            finally:runtime.close()
