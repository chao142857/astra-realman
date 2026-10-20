"""One owner publishes real pixels. Consumers never open or refresh a device."""
from __future__ import annotations
import copy
import threading
import time
from pathlib import Path
import numpy as np

TABLETOP = {'tabletop': '346222072496'}
MISSING = {'left_wrist': '254522073676', 'overhead': '344422071480', 'right_wrist': '348522072063'}


def host_clock_id():
    return 'linux-monotonic:' + Path('/proc/sys/kernel/random/boot_id').read_text().strip()


class LiveSource:
    """Thread-safe, same-host owner subscription; no disk replay or synthetic state.

    Owner passes RGB uint8, aligned optical-Z float32 metres and provenance.
    Capture timestamps are retained, never replaced by read/refresh time.
    Robot telemetry is deliberately unavailable in Phase 1A (arms powered off).
    """
    def __init__(self, owner_id: str, *, roles=None, clock_id=None):
        if not owner_id:
            raise ValueError('OWNER_ID_REQUIRED')
        self.owner_id = owner_id
        self.roles = dict(TABLETOP if roles is None else roles)
        if self.roles != TABLETOP:
            raise ValueError('ONLY_CONFIRMED_TABLETOP_SERIAL_ENABLED')
        self.clock_id = clock_id or host_clock_id()
        self._lock = threading.Lock()
        self._snapshot = None
        self._last_numbers = None
        self.closed = False
        self.failure = None
        self.published_count = 0

    def publish(self, camera: dict, *, owner_id: str):
        if owner_id != self.owner_id:
            raise ValueError('OWNER_MISMATCH')
        c = copy.deepcopy(camera)
        if self.roles.get(c.get('role')) != c.get('serial'):
            raise ValueError('CAMERA_ROLE_SERIAL_MISMATCH')
        if c.get('host_clock_id') != self.clock_id:
            raise ValueError('HOST_CLOCK_DOMAIN_MISMATCH')
        rgb, depth = c.get('rgb'), c.get('depth_m')
        if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError('RGB_UINT8_REQUIRED')
        if not isinstance(depth, np.ndarray) or depth.dtype != np.float32 or depth.shape != rgb.shape[:2]:
            raise ValueError('ALIGNED_DEPTH_FLOAT32_REQUIRED')
        if c.get('alignment') != 'depth_to_color' or c.get('depth_unit') != 'm':
            raise ValueError('ALIGNED_METRIC_DEPTH_REQUIRED')
        k = np.asarray(c['intrinsics'], dtype=float)
        if k.shape != (3, 3) or not np.isfinite(k).all() or k[0,0] <= 0 or k[1,1] <= 0:
            raise ValueError('FACTORY_INTRINSICS_REQUIRED')
        for name in ['captured_at', 'received_monotonic_s', 'color_timestamp_ms', 'depth_timestamp_ms']:
            if not np.isfinite(c[name]) or c[name] <= 0:
                raise ValueError('INVALID_TIMESTAMP:' + name)
        if any(not c.get(name) for name in ['color_timestamp_domain', 'depth_timestamp_domain', 'intrinsics_source']):
            raise ValueError('TIMESTAMP_AND_INTRINSICS_PROVENANCE_REQUIRED')
        numbers = (int(c['color_frame_number']), int(c['depth_frame_number']))
        with self._lock:
            if self.closed or self.failure:
                raise RuntimeError('LIVE_SOURCE_NOT_RUNNING')
            if self._last_numbers is not None and any(a <= b for a,b in zip(numbers,self._last_numbers)):
                raise ValueError('REPEATED_OR_REGRESSED_DEVICE_FRAME')
            self._last_numbers = numbers
            self.published_count += 1
            self._snapshot = {'mode':'LIVE', 'owner_id':self.owner_id, 'sequence':self.published_count,
                'captured_at':c['captured_at'], 'cameras':[c], 'canonical_states':{},
                'robot_state_source':'UNAVAILABLE_ARMS_POWERED_OFF', 'motion_permitted':False}

    def read(self):
        with self._lock:
            if self._snapshot is None:
                raise RuntimeError('LIVE_FRAME_NOT_YET_AVAILABLE')
            result = copy.deepcopy(self._snapshot)
            result['owner_running'] = not self.closed and self.failure is None
            result['owner_error'] = self.failure
            return result

    def fail(self, error):
        with self._lock:
            self.failure = str(error)

    def close(self):
        with self._lock:
            self.closed = True
