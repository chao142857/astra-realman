"""Bounded single-arm SDKReadOnly + native CAP/MCP; plan-only by default.

Run without --connect-readonly for a nonconnecting preflight. Onsite flags are
operator assertions, never inferred from SSH reachability or historical data.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import signal
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def setup(aspire):
    lock = json.loads((ROOT/'aspire_realman_phase05/upstream.lock.json').read_text())
    for name, expected in lock['runtime_source_sha256'].items():
        if hashlib.sha256((aspire/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('PINNED_ASPIRE_HASH_MISMATCH:'+name)
    sys.path[:0] = [str(ROOT/'aspire_realman_phase1a/src'), str(ROOT/'aspire_realman_phase05/src'),
                   str(aspire/'src'), str(ROOT/'aspire_realman_phase05/tests')]
    return len(lock['runtime_source_sha256'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--aspire-source', type=Path, default=ROOT/'.cache/ASPIRE')
    p.add_argument('--arm', choices=['left','right'], default='left')
    p.add_argument('--robot-host', help='Explicit IPv4 endpoint, never guessed')
    p.add_argument('--robot-port', type=int, default=8080)
    p.add_argument('--connect-readonly', action='store_true')
    p.add_argument('--onsite-power-confirmed', action='store_true')
    p.add_argument('--onsite-read-authorized', action='store_true')
    p.add_argument('--sole-sdk-owner-confirmed', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--seconds', type=float, default=10)
    p.add_argument('--period', type=float, default=.5)
    a = p.parse_args()
    verified = setup(a.aspire_source)
    from aspire_realman_live.sdk_state import (DEPLOYMENT, SDK_PACKAGE, READER_HASHES, SDK_HASHES,
        READS, LIFECYCLE, verify_files, prepare_reader, SDKStateReader, validate_onsite)
    plan = {'mode':'PLAN_ONLY_NO_SDK_IMPORT_OR_CONNECTION', 'arm_scope':[a.arm],
        'endpoint':{'host':a.robot_host,'port':a.robot_port}, 'upstream_hashes_verified':verified,
        'reads':sorted(READS),'lifecycle':sorted(LIFECYCLE),'motion_permitted':False,
        'native_robot_state_available':False,'onsite_flags_are_operator_assertions':True}
    try:
        plan['deployed_reader_hashes'] = verify_files(DEPLOYMENT, READER_HASHES)
        plan['sdk_files_verified_without_import'] = verify_files(SDK_PACKAGE, SDK_HASHES)
    except (OSError, RuntimeError) as exc:
        plan['local_dependency_blocker'] = str(exc)
    if not a.connect_readonly:
        print(json.dumps(plan, indent=2)); return 0
    # Validate before mkdir, copying/importing reader, rm_init or SDK load.
    validate_onsite(a.arm, a.robot_host, a.robot_port, powered=a.onsite_power_confirmed,
        authorized=a.onsite_read_authorized, sole_owner=a.sole_sdk_owner_confirmed)
    if 'local_dependency_blocker' in plan:
        raise RuntimeError(plan['local_dependency_blocker'])
    if not a.output or not 1 <= a.seconds <= 60 or not .2 <= a.period <= 5:
        p.error('live needs NEW --output, 1..60 seconds and 0.2..5 second poll period')
    output = a.output.resolve(); output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    folder = prepare_reader(output)
    from aspire_realman_live.state_owner import SingleArmStateOwner
    from aspire_realman_live.source import host_clock_id
    from aspire_realman_live.runtime import build_live_runtime
    from http_support import loopback_server
    owner = SingleArmStateOwner('sdk-readonly:'+uuid.uuid4().hex, a.arm,
        source_kind='LIVE_SDK_READ_ONLY', clock_id=host_clock_id())
    reader = SDKStateReader(owner, output, folder, a.robot_host, a.robot_port,
        onsite={'powered':True,'authorized':True,'sole_owner':True})
    # SIGTERM, like Ctrl+C, unwinds only our own session and localhost server.
    previous = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    report = {**plan, 'mode':'BOUNDED_LIVE_READONLY', 'status':'STARTED', 'output':str(output)}
    try:
        with ExitStack() as stack:
            stack.enter_context(reader)
            reader.poll_once()
            runtime = build_live_runtime(None, state_owner=owner)
            stack.callback(runtime.close)
            base = stack.enter_context(loopback_server(runtime.app))
            (output/'mcp-endpoint.json').write_text(json.dumps({'url':base+'/mcp/', 'pid':__import__('os').getpid()}))
            print(json.dumps({'status':'READONLY_MCP_READY','url':base+'/mcp/','seconds':a.seconds}),flush=True)
            deadline = time.monotonic()+a.seconds
            while time.monotonic() < deadline:
                time.sleep(min(a.period, max(0,deadline-time.monotonic())))
                if time.monotonic() < deadline:
                    reader.poll_once()
            report['status'] = 'BOUNDED_READONLY_COMPLETED'
    except KeyboardInterrupt:
        report['status'] = 'STOPPED_BY_OPERATOR'
    except Exception as exc:
        report.update(status='FAILED', error=type(exc).__name__+':'+str(exc))
    finally:
        signal.signal(signal.SIGTERM, previous)
        report.update(published_samples=reader.log, owner_closed=owner.closed,
            sdk_events=[] if reader.module is None else [str(f) for f in (folder/'events').glob('*.json')],
            current_state_after_shutdown=False, motion_dispatches=0)
        (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps({'status':report['status'],'report':str(output/'report.json')}))
    return report['status']=='FAILED'


if __name__=='__main__':
    raise SystemExit(main())
