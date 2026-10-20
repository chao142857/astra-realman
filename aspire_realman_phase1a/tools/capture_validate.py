"""Opt-in bounded tabletop capture + native localhost MCP; zero arm connections."""
import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
ROOT = Path(__file__).resolve().parents[2]
bootstrap = argparse.ArgumentParser(add_help=False)
bootstrap.add_argument('--aspire-source',type=Path,default=ROOT/'.cache/ASPIRE')
bootstrap_args,_ = bootstrap.parse_known_args()
ASPIRE = bootstrap_args.aspire_source
sys.path[:0] = [str(ROOT/'aspire_realman_phase1a/src'),str(ROOT/'aspire_realman_phase05/src'),
               str(ASPIRE/'src'),str(ROOT/'aspire_realman_phase05/tests')]
lock=json.loads((ROOT/'aspire_realman_phase05/upstream.lock.json').read_text())
for name,expected in lock['runtime_source_sha256'].items():
    if hashlib.sha256((ASPIRE/name).read_bytes()).hexdigest()!=expected:
        raise SystemExit('PINNED_ASPIRE_HASH_MISMATCH:'+name)
from aspire_realman_live import LiveSource,build_live_runtime
from aspire_realman_live.owner import LabRGBDOwner,device_users
from http_support import loopback_server
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import numpy as np
from PIL import Image


def guard(event,args):
    if event == 'socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ['127.0.0.1','::1']:
        raise PermissionError('PHASE_1A_PERMITS_ONLY_LOOPBACK_NO_ARM_ENDPOINTS')
sys.addaudithook(guard)


def summarize(result):
    return {'isError':bool(result.isError),'image_count':sum(c.type=='image' for c in result.content),
            'structuredContent':result.structuredContent}


async def check_mcp(base, source):
    evidence = []
    async with httpx.AsyncClient(trust_env=False,timeout=10) as client:
        async with streamable_http_client(base+'/mcp/',http_client=client) as (read,write,_):
            async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=10)) as session:
                init = await session.initialize()
                evidence.append({'event':'initialize','protocol':init.protocolVersion})
                names = sorted(t.name for t in (await session.list_tools()).tools)
                evidence.append({'event':'tools/list','names':names})
                caps = await session.call_tool('get_capability_graph',{})
                evidence.append({'event':'capabilities',**summarize(caps)})
                graph = caps.structuredContent['configured_providers']
                assert not any(graph.values()),graph
                assert 'cap_move_to_pose' not in names and 'cap_localize_object' not in names
                seen = []
                for _ in range(3):
                    obs = await session.call_tool('observe',{'cameras':['tabletop']})
                    evidence.append({'event':'live_observe',**summarize(obs)})
                    assert not obs.isError and sum(c.type=='image' for c in obs.content)==1
                    value = obs.structuredContent['observation']
                    assert value['state']=={},value['state']
                    meta = value['camera_metadata']['tabletop']
                    assert not meta['full_cap_observation_available'] and not meta['geometry_eligible']
                    assert not meta['stale'] and meta['exposure_freshness_verified']
                    assert meta['depth_usable_for_optical_inspection']
                    seen.append(value['observation_seq'])
                    await asyncio.sleep(.25)
                assert seen[-1]>seen[0],seen
                for name,args in [('cap_get_robot_state',{}),('cap_set_gripper',{'arm':'left','position':.5}),
                                  ('cap_move_to_joints',{'arm':'left','target':[0]*6}),
                                  ('cap_move_synchronized',{'targets':{'left':[0]*6,'right':[0]*6}}),
                                  ('cap_program_go_home',{})]:
                    r = await session.call_tool(name,args)
                    evidence.append({'event':name,**summarize(r)})
                    assert r.isError,(name,r)
                return evidence


def save_sample(output,label,sample):
    c,z16 = sample
    folder = output/label
    folder.mkdir()
    Image.fromarray(c['rgb']).save(folder/'rgb.png')
    np.save(folder/'aligned-z16.npy',z16,allow_pickle=False)
    np.save(folder/'aligned-depth-m.npy',c['depth_m'],allow_pickle=False)
    record = {k:v for k,v in c.items() if k not in ['rgb','depth_m']}
    record['assets'] = {p.name:{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p in folder.iterdir()}
    (folder/'snapshot.json').write_text(json.dumps(record,indent=2))
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--aspire-source',type=Path,default=ASPIRE)
    p.add_argument('--capture-tabletop',action='store_true',help='Explicit opt-in; requires prior operator authorization and no other owner')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=4)
    p.add_argument('--save-raw-streams',action='store_true',help='Future onsite: retain actual pre-align RGB/Z16 plus aligned data in same owner')
    p.add_argument('--reference-description',help='Physical known-scale reference and placement; operator description, not software certification')
    a = p.parse_args()
    if not a.capture_tabletop or not 1<=a.seconds<=15:
        p.error('capture requires explicit --capture-tabletop and 1..15 seconds')
    if a.save_raw_streams and not a.reference_description:
        p.error('--save-raw-streams requires actual onsite --reference-description')
    output = a.output.resolve()
    output.relative_to(ROOT.resolve())  # output restricted to this new isolated workspace
    output.mkdir(parents=True,exist_ok=False)
    source = LiveSource('phase1a:'+uuid.uuid4().hex)
    result = {'status':'STARTED','output':str(output),'arm_sdk_connections':0,'physical_commands_sent':0,
              'robot_state_source':'UNAVAILABLE_ARMS_POWERED_OFF','raw_assets_transferred':False}
    result['software_sha256'] = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'aspire_realman_phase1a').rglob('*.py')) if not p.name.startswith('._')}
    owner = LabRGBDOwner(source,raw_archive=output/'raw-frames' if a.save_raw_streams else None,
                         reference_description=a.reference_description)
    try:
        with owner:
            runtime = build_live_runtime(source)
            try:
                try:
                    runtime.adapter.get_observation()
                    raise AssertionError('FULL_OBSERVATION_MUST_BE_UNAVAILABLE')
                except RuntimeError as exc:
                    result['full_cap_observation_error'] = str(exc)
                with loopback_server(runtime.app) as base:
                    result['mcp'] = asyncio.run(check_mcp(base,source))
                    time.sleep(a.seconds)
                result['refusals'] = list(runtime.adapter.refusals)
                result['hardware_commands_sent'] = runtime.adapter.hardware_commands_sent
            finally:
                runtime.close()
        result.update(status='CAPTURED',profile=owner.profile,enumeration=owner.enumeration,preflight=owner.preflight,
            samples=owner.rows,skipped_duplicate_pairs=owner.skipped_duplicate_pairs,
            first=save_sample(output,'first',owner.first),last=save_sample(output,'last',owner.last),owner_error=owner.error)
        result['same_owner_raw_bundles'] = owner.raw_bundles
        frozen = source.read()
        from aspire_realman_live.quality import camera_quality
        result['after_owner_closed'] = camera_quality(frozen['cameras'][0],frozen)
        assert result['after_owner_closed']['stale']
    except Exception as exc:
        result.update(status='FAILED',error=type(exc).__name__+':'+str(exc),owner_error=owner.error)
    finally:
        try:
            result['postflight'] = device_users()
        except RuntimeError as exc:
            result['postflight'] = {'check_failed':str(exc)}
        result['hardware_modules'] = [x for x in sys.modules if x.startswith(('Robotic_Arm','realman_api2'))]
        (output/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        print(json.dumps({'status':result['status'],'error':result.get('error'),'report':str(output/'report.json'),
                          'published_count':source.published_count,'device_owner_postflight':result['postflight']}))
    return result['status']!='CAPTURED'

if __name__=='__main__':
    raise SystemExit(main())
