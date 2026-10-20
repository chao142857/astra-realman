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
import json
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


def save_raw_bundle(folder, raw_rgb, raw_z16, aligned_rgb, aligned_z16, depth_m, camera, profile):
    """One owner's SAME frameset, pre-align pixels copied before rs.align.

    No reconstruction of historical raw depth, sensor writes or new pipeline.
    Called only by the explicitly authorized live capture path below.
    """
    from PIL import Image
    if (raw_rgb.dtype != np.uint8 or raw_rgb.ndim != 3 or raw_rgb.shape[2] != 3
            or raw_z16.dtype != np.uint16 or raw_z16.ndim != 2
            or aligned_rgb.dtype != np.uint8 or aligned_rgb.ndim != 3 or aligned_rgb.shape[2] != 3
            or aligned_z16.dtype != np.uint16 or depth_m.dtype != np.float32
            or aligned_z16.shape != depth_m.shape or depth_m.shape != aligned_rgb.shape[:2]):
        raise ValueError('RAW_AND_ALIGNED_STREAM_SHAPE_DTYPE_REQUIRED')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    Image.fromarray(raw_rgb).save(folder/'raw-rgb.png')
    Image.fromarray(aligned_rgb).save(folder/'aligned-rgb.png')
    np.save(folder/'raw-depth-z16.npy', raw_z16, allow_pickle=False)
    np.save(folder/'aligned-depth-z16.npy', aligned_z16, allow_pickle=False)
    np.save(folder/'aligned-depth-m.npy', depth_m, allow_pickle=False)
    record = {k:v for k,v in camera.items() if k not in ('rgb','depth_m')}
    record.update(profile=profile, raw_depth_pixels_saved=True, raw_rgb_saved=True,
        same_owner_same_frameset=True, measurement_accuracy_qualified=False,
        host_saved_epoch_s=time.time(), assets={p.name:{'bytes':p.stat().st_size,
            'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.iterdir())})
    with (folder/'snapshot.json').open('x') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
    return {'folder':str(folder),'snapshot_sha256':hashlib.sha256((folder/'snapshot.json').read_bytes()).hexdigest()}


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
    def __init__(self, source, *, raw_archive=None, reference_description=None, archive_limit=60):
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
        self.raw_archive = None if raw_archive is None else Path(raw_archive)
        self.reference_description = reference_description
        self.archive_limit = archive_limit
        self.raw_bundles = []
        if raw_archive is not None and (not reference_description or not 1 <= archive_limit <= 300):
            raise ValueError('RAW_CAPTURE_REQUIRES_REFERENCE_DESCRIPTION_AND_BOUNDED_FRAME_COUNT')

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
                'stream_profiles':{'color':{'format':str(cp.format()),'stream_index':cp.stream_index(),'unique_id':cp.unique_id()},
                                   'raw_depth':{'format':str(dp.format()),'stream_index':dp.stream_index(),'unique_id':dp.unique_id()}},
                'known_scale_reference_description':self.reference_description,
                'known_scale_reference_measured_by_software':False,
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
                save_raw = self.raw_archive is not None and len(self.raw_bundles) < self.archive_limit
                if save_raw:
                    # Must precede align; an aligned Z16 cannot be substituted.
                    raw_rgb = np.asanyarray(raw_color.get_data()).copy()
                    raw_z16 = np.asanyarray(raw_depth.get_data()).copy()
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
                    'raw_stream_intrinsics':{'color':intrinsics(raw_color.profile),'depth':intrinsics(raw_depth.profile)},
                    'aligned_frame_numbers':{'color':color.get_frame_number(),'depth':depth.get_frame_number()},
                    'aligned_timestamp_ms':{'color':color.get_timestamp(),'depth':depth.get_timestamp()},
                    'aligned_timestamp_domains':{'color':str(color.get_frame_timestamp_domain()),'depth':str(depth.get_frame_timestamp_domain())},
                    'calibration_status':'HISTORICAL_EXTRINSIC_NOT_REVALIDATED','world_transform':None}
                self.source.publish(c,owner_id=self.source.owner_id)
                if save_raw:
                    self.raw_bundles.append(save_raw_bundle(self.raw_archive/f'{len(self.raw_bundles)+1:06d}',
                        raw_rgb,raw_z16,c['rgb'],z16,z,c,self.profile))
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
