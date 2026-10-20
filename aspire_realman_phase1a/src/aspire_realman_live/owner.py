"""One bounded lab-driver owner; no auto reset, sensor options or arm SDK.

Reuse the installed RealSenseCamera pipeline and rs.align(color), just as
capture_onsite_rgbd.read_one. Do not call read_* methods: their timeout handler
restarts a pipeline. A running camera owner is a hard precondition failure.
"""
from __future__ import annotations
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import numpy as np
from .source import host_clock_id

DRIVER = Path('/home/tongji/aloha/RealMan_Control/realsense.py')
PACKAGE = Path('/home/tongji/aloha/shadow_camera/src')


def intrinsics(profile):
    k = profile.as_video_stream_profile().get_intrinsics()
    return {'matrix':[[k.fx,0,k.ppx],[0,k.fy,k.ppy],[0,0,1]],'resolution':[k.width,k.height],
            'distortion_model':str(k.model),'distortion_coefficients':list(k.coeffs)}


def metadata(frame, rs):
    result = {}
    for name in ['frame_timestamp','sensor_timestamp','backend_timestamp','time_of_arrival','actual_exposure']:
        field = getattr(rs.frame_metadata_value,name,None)
        if field is not None and frame.supports_frame_metadata(field):
            result[name] = frame.get_frame_metadata(field)
    return result


def device_users():
    devices = sorted(str(p) for p in Path('/dev').glob('video*'))
    if not devices:
        raise RuntimeError('NO_VIDEO_NODES')
    result = subprocess.run(['fuser',*devices],capture_output=True,text=True)
    if result.returncode not in (0,1):
        raise RuntimeError('DEVICE_OWNER_CHECK_FAILED:' + result.stderr)
    if result.stdout.strip():
        raise RuntimeError('EXISTING_CAMERA_OWNER:' + result.stdout.strip())
    return {'devices':devices,'fuser_returncode':result.returncode,'pids':result.stdout.strip()}


class LabRGBDOwner:
    def __init__(self, source):
        self.source = source
        self.camera = None
        self.lock = None
        self.thread = None
        self.stop = threading.Event()
        self.rows = []
        self.error = None
        self.skipped_duplicate_pairs = 0
        self.profile = {}
        self.first = None
        self.last = None

    def __enter__(self):
        self.lock = open('/tmp/aspire-realsense-346222072496.lock','a')
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.preflight = device_users()
            import pyrealsense2 as rs
            self.rs = rs
            devices = list(rs.context().query_devices())
            self.enumeration = [{str(k):d.get_info(k) for k in [rs.camera_info.name,rs.camera_info.serial_number,
                rs.camera_info.firmware_version,rs.camera_info.physical_port,rs.camera_info.usb_type_descriptor] if d.supports(k)} for d in devices]
            if '346222072496' not in [d.get_info(rs.camera_info.serial_number) for d in devices]:
                raise RuntimeError('CONFIRMED_TABLETOP_NOT_ENUMERATED')
            # Import reviewed local factory, not its CLI, GUI or experiment runner.
            sys.path.insert(0,str(PACKAGE))
            spec = importlib.util.spec_from_file_location('phase1a_lab_realsense',DRIVER)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.camera = module.RealSenseCamera(serial_num='346222072496',is_depth_frame=True)
            device_users()  # recheck immediately before acquiring the sole pipeline
            self.camera.start_camera()
            profile = self.camera.profile
            cp, dp = profile.get_stream(rs.stream.color), profile.get_stream(rs.stream.depth)
            transform = dp.as_video_stream_profile().get_extrinsics_to(cp)
            self.profile = {'driver':str(DRIVER),'driver_sha256':hashlib.sha256(DRIVER.read_bytes()).hexdigest(),
                'owner_id':self.source.owner_id,'pid':os.getpid(),'clock_id':host_clock_id(),
                'color':intrinsics(cp),'raw_depth':intrinsics(dp),
                'color_fps':cp.fps(),'depth_fps':dp.fps(),
                'depth_scale_m_per_z16':profile.get_device().first_depth_sensor().get_depth_scale(),
                'factory_depth_to_color':{'rotation_column_major':list(transform.rotation),'translation_m':list(transform.translation)},
                'world_transform':None,'sensor_options_written':False,'reset_attempted':False}
            for _ in range(8):
                self.camera._pipeline.wait_for_frames(5000)
            self.thread = threading.Thread(target=self._pump,name='sole-tabletop-rgbd-owner',daemon=True)
            self.thread.start()
            deadline = time.monotonic()+8
            while self.source.published_count == 0:
                if self.error:
                    raise RuntimeError(self.error)
                if time.monotonic() > deadline:
                    raise RuntimeError('FIRST_RGBD_TIMEOUT')
                self.stop.wait(.01)
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def _pump(self):
        try:
            last_numbers = None
            while not self.stop.is_set():
                started = time.monotonic()
                raw = self.camera._pipeline.wait_for_frames(3000)
                received, wall = time.monotonic(),time.time()
                raw_color,raw_depth = raw.get_color_frame(),raw.get_depth_frame()
                if not raw_color or not raw_depth:
                    raise RuntimeError('RAW_RGBD_MISSING')
                numbers = (raw_color.get_frame_number(),raw_depth.get_frame_number())
                if last_numbers is not None and any(a <= b for a,b in zip(numbers,last_numbers)):
                    self.skipped_duplicate_pairs += 1
                    continue
                aligned = self.camera._align.process(raw)
                color,depth = aligned.get_color_frame(),aligned.get_depth_frame()
                if not color or not depth:
                    raise RuntimeError('ALIGNED_RGBD_MISSING')
                z16 = np.asanyarray(depth.get_data()).copy()
                z = (z16.astype(np.float32)*self.profile['depth_scale_m_per_z16']).astype(np.float32)
                ci, di = intrinsics(color.profile),intrinsics(depth.profile)
                if ci != di:
                    raise RuntimeError('ALIGNED_INTRINSICS_DO_NOT_MATCH_COLOR')
                c = {'role':'tabletop','serial':'346222072496',
                    'rgb':np.asanyarray(color.get_data()).copy(),'depth_m':z,
                    'intrinsics':ci['matrix'],'intrinsics_detail':ci,'aligned_depth_intrinsics':di,
                    'intrinsics_source':'current device aligned frame profile',
                    'alignment':'depth_to_color','depth_unit':'m','depth_convention':'optical_z',
                    'optical_frame':'realsense:346222072496:color_optical',
                    'captured_at':wall,'received_monotonic_s':received,'host_clock_id':host_clock_id(),
                    'capture_wait_interval_monotonic_s':[started,received],
                    'color_timestamp_ms':raw_color.get_timestamp(),'depth_timestamp_ms':raw_depth.get_timestamp(),
                    'color_timestamp_domain':str(raw_color.get_frame_timestamp_domain()),
                    'depth_timestamp_domain':str(raw_depth.get_frame_timestamp_domain()),
                    'color_frame_number':numbers[0],'depth_frame_number':numbers[1],
                    'raw_color_frame_metadata':metadata(raw_color,self.rs),'raw_depth_frame_metadata':metadata(raw_depth,self.rs),
                    'calibration_status':'HISTORICAL_EXTRINSIC_NOT_REVALIDATED','world_transform':None}
                self.source.publish(c,owner_id=self.source.owner_id)
                from .quality import camera_quality
                snapshot = self.source.read()
                row = camera_quality(c,snapshot)
                row.update({k:c[k] for k in ['received_monotonic_s','color_timestamp_ms','depth_timestamp_ms',
                    'capture_wait_interval_monotonic_s','raw_color_frame_metadata','raw_depth_frame_metadata']})
                self.rows.append(row)
                if self.first is None:
                    self.first = (c,z16.copy())
                self.last = (c,z16.copy())
                last_numbers = numbers
        except Exception as exc:
            self.error = type(exc).__name__ + ':' + str(exc)
            self.source.fail(self.error)

    def __exit__(self,*args):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=4)
        try:
            if self.camera and hasattr(self.camera,'_pipeline'):
                if self.camera.camera_on or getattr(self.camera,'profile',None) is not None:
                    self.camera._pipeline.stop()
                    self.camera.camera_on = False
        finally:
            self.source.close()
            if self.lock:
                self.lock.close()
                self.lock = None
