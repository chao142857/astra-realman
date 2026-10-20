"""Bounded, single-arm entry to the audited SDKReadOnly; no motion API.

Importing this module never imports the vendor SDK. Production connection needs
explicit onsite assertions. An injected SDK is exclusively OFFLINE fixture data.
The deployed three-file reader is copied byte-for-byte into a NEW run so its
io_utils write confinement cannot write into the original deployment.
"""
import copy
import fcntl
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import shutil
import sys
import time

from .source import host_clock_id

DEPLOYMENT = Path('/home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness')
SDK_PACKAGE = Path('/home/tongji/aloha/RealMan_Control/Robotic_Arm')
READER_HASHES = {
    'realman_api2_readonly.py': 'b690a92982b0a111f60b193ad34b67ccc60ea26ebe31eb88f59d663fc9e0aef7',
    'realman_state.py': '5f5ce26c2fbd5dfb6dafdfad2b93e9308d471032649882ec86f55ee809c58f22',
    'io_utils.py': '99cc9d9a2ded45979be089a5528adde62f540e41bd4bf8b62a4477dd41fccf6b',
}
SDK_HASHES = {
    '__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'rm_robot_interface.py': 'dac840a77e62280056674fbfb763cf6c4d93084406435fff3445872cf6b1f580',
    'rm_ctypes_wrap.py': 'd2f136c6fca3944b066d7e548d70e9cadd926de5f15bdc0b64cba076515020de',
    'libs/linux_x86/libapi_c.so': '53106459d55cc6ac5d6a6ddf9b623a8cb88fd3cd09549bfff2626d6c67ea502c',
}
READS = {'rm_get_current_arm_state', 'rm_get_current_work_frame', 'rm_get_current_tool_frame'}
LIFECYCLE = {'rm_init', 'rm_create_robot_arm', 'rm_delete_robot_arm', 'rm_destroy'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_files(directory, expected):
    result = {name: sha(directory/name) for name in expected}
    if result != expected:
        raise RuntimeError('AUDITED_SOURCE_CHANGED_NO_VERSION_FALLBACK')
    return result


def prepare_reader(run, deployment=DEPLOYMENT):
    """Read/copy Python only. No ctypes load, rm_init, socket or arm access."""
    run = Path(run).resolve()
    hashes = verify_files(Path(deployment), READER_HASHES)
    folder = run/'verified_reader'
    folder.mkdir(parents=True, exist_ok=False)
    for name in hashes:
        shutil.copyfile(Path(deployment)/name, folder/name)
    verify_files(folder, READER_HASHES)
    return folder


def load_reader(folder):
    verify_files(folder, READER_HASHES)
    for name in ('io_utils', 'realman_state', 'realman_api2_readonly'):
        if name in sys.modules:
            raise RuntimeError('READER_MODULE_ALREADY_LOADED_REFUSE_AMBIGUITY:'+name)
    sys.path.insert(0, str(folder))
    try:
        spec = importlib.util.spec_from_file_location('realman_api2_readonly', folder/'realman_api2_readonly.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(folder))
    if module.READS != READS or module.LIFECYCLE != LIFECYCLE:
        raise RuntimeError('SDK_ALLOWLIST_CHANGED')
    return module


def validate_onsite(arm, host, port, *, powered=False, authorized=False, sole_owner=False):
    if arm not in ('left', 'right') or not host or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('EXPLICIT_ONE_ARM_AND_ENDPOINT_REQUIRED')
    ipaddress.IPv4Address(host)  # no DNS lookup, no guessed controller endpoint
    if not all(x is True for x in (powered, authorized, sole_owner)):
        raise PermissionError('ONSITE_POWER_READ_AUTHORIZATION_AND_SOLE_OWNER_CONFIRMATION_REQUIRED')


def existing_connections(host, port):
    """Fail closed on an existing connection; no probe packets are sent."""
    rows = []
    for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
        fields = line.split()
        iphex, porthex = fields[2].split(':')
        peer = str(ipaddress.IPv4Address(bytes.fromhex(iphex)[::-1]))
        if peer == host and int(porthex, 16) == port and fields[3] != '0A':
            rows.append({'peer': peer, 'port': port, 'kernel_state': fields[3]})
    if rows:
        raise RuntimeError('EXISTING_CONTROLLER_CONNECTION_REFUSE_COMPETING_OWNER:'+json.dumps(rows))
    return rows


class SDKStateReader:
    """Synchronous poller; only the caller's single-arm handle is ever deleted."""
    def __init__(self, owner, run, reader_folder, host, port, *, onsite=None, injected_sdk=None):
        self.owner, self.run, self.folder = owner, Path(run), Path(reader_folder)
        self.host, self.port, self.onsite = host, port, onsite or {}
        self.injected_sdk = injected_sdk
        self.session = None
        self.lock = None
        self.sequence = 0
        self.module = None
        self.log = []

    def __enter__(self):
        if self.injected_sdk is None:
            validate_onsite(self.owner.arm, self.host, self.port, **self.onsite)
            if self.owner.source_kind != 'LIVE_SDK_READ_ONLY':
                raise ValueError('REAL_READER_REQUIRES_LIVE_SOURCE_KIND')
            if self.owner.clock_id != host_clock_id():
                raise ValueError('CURRENT_HOST_BOOT_CLOCK_REQUIRED')
            verify_files(SDK_PACKAGE, SDK_HASHES)
            existing_connections(self.host, self.port)
        elif self.owner.source_kind != 'OFFLINE_SDK_TRANSPORT_FIXTURE':
            raise ValueError('INJECTED_SDK_CAN_NEVER_PUBLISH_LIVE')
        try:
            key = hashlib.sha256(f'{self.owner.arm}:{self.host}:{self.port}'.encode()).hexdigest()[:20]
            self.lock = open('/tmp/aspire-realman-readonly-'+key+'.lock', 'a')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.injected_sdk is None:
                existing_connections(self.host, self.port)
            self.module = load_reader(self.folder)
            events = self.folder/'events'
            events.mkdir(exist_ok=False)
            self.session = self.module.SDKReadOnly(events, sdk=self.injected_sdk)
            self.session.__enter__()
            result = self.session.connect(self.owner.arm, self.host, self.port, dof=6)
            if not result['connected']:
                raise RuntimeError('SDK_SINGLE_ARM_CONNECT_FAILED')
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def poll_once(self):
        if self.session is None:
            raise RuntimeError('READONLY_SESSION_NOT_ENTERED')
        begin, wall_begin = time.monotonic(), time.time()
        sample = self.session.snapshot(self.owner.arm)
        end, wall_end = time.monotonic(), time.time()
        self.sequence += 1
        packet = {'source_kind': self.owner.source_kind, 'sequence': self.sequence,
            'arm_scope': [self.owner.arm], 'host_clock_id': self.owner.clock_id,
            'read_interval_monotonic_s': [begin, end], 'read_interval_epoch_s': [wall_begin, wall_end],
            'sdk_sample': sample, 'controller_measurement_timestamp': None,
            'motion_permitted': False}
        path = self.run/f'sdk-sample-{self.sequence:06d}.json'
        with path.open('x') as stream:
            json.dump(packet, stream, indent=2, allow_nan=False)
        try:
            if sample.get('canonical') is None:
                raise RuntimeError('SDK_CANONICAL_UNAVAILABLE:'+str(sample.get('canonical_error')))
            self.owner.publish(sample, owner_id=self.owner.owner_id, sequence=self.sequence,
                read_interval_monotonic_s=[begin, end], host_clock_id=self.owner.clock_id)
        except BaseException as exc:
            self.owner.fail(type(exc).__name__+':'+str(exc))
            self.publish_latest()
            raise
        self.log.append({'sequence': self.sequence, 'packet': str(path), 'sha256': sha(path)})
        self.publish_latest()
        return copy.deepcopy(packet)

    def publish_latest(self):
        try:
            value = self.owner.read(host_clock_id=self.owner.clock_id)
        except RuntimeError as exc:
            value = {'owner_error': str(exc), 'current_state_available': False, 'native_robot_state_available': False}
        tmp = self.run/'latest.tmp'
        tmp.write_text(json.dumps(value, indent=2, allow_nan=False))
        tmp.replace(self.run/'latest.json')

    def __exit__(self, *args):
        self.owner.close()
        try:
            if self.session is not None:
                self.session.__exit__(*args)
        finally:
            if self.lock is not None:
                self.lock.close()
                self.lock = None
            self.session = None
            if self.run.exists():
                self.publish_latest()
