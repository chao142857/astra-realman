"""Persistent acquisition using the installed lab driver. Never sends actuation."""
import concurrent.futures, hashlib, importlib.util, sys, threading, time, uuid
from pathlib import Path
import numpy as np
from PIL import Image
from io_utils import new_run, write_json
from scripts.capture_onsite_rgbd import CAMERAS, DRIVER, CAMERA_PACKAGE, intrinsics, sha

def frame_metadata(frame, rs):
    result = {}
    for name in ('frame_timestamp', 'sensor_timestamp', 'backend_timestamp', 'time_of_arrival', 'actual_exposure'):
        field = getattr(rs.frame_metadata_value, name, None)
        if field is not None and frame.supports_frame_metadata(field):
            result[name] = frame.get_frame_metadata(field)
    return {'raw_values': result, 'units': 'SDK field-specific raw units; not cross-device synchronization evidence'}

class RGBDSession:
    def __init__(self, camera_configs=None):
        self.configs = camera_configs or CAMERAS
        self.cameras = []; self.pool = None; self.profiles = {}
        self.stop = threading.Event(); self.condition = threading.Condition()
        self.latest = {}; self.error = None; self.last_numbers = {}; self.readers = []
    def __enter__(self):
        import pyrealsense2 as rs
        self.rs = rs
        sys.path.insert(0, str(CAMERA_PACKAGE))
        spec = importlib.util.spec_from_file_location('onsite_lab_camera', DRIVER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        present = [d.get_info(rs.camera_info.serial_number) for d in rs.context().devices]
        if any(serial not in present for _, _, serial in self.configs): raise RuntimeError('REQUIRED_CAMERA_MISSING')
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(self.configs))
        try:
            for selector, role, serial in self.configs:
                c = module.RealSenseCamera(serial_num=serial, is_depth_frame=True)
                self.cameras.append(c); c.start_camera()
                dp = c.profile.get_stream(rs.stream.depth).as_video_stream_profile()
                cp = c.profile.get_stream(rs.stream.color).as_video_stream_profile()
                transform = dp.get_extrinsics_to(cp)
                self.profiles[selector] = {'serial': serial, 'role': role,
                    'raw_depth_intrinsics': intrinsics(dp.get_intrinsics()),
                    'raw_color_intrinsics': intrinsics(cp.get_intrinsics()),
                    'depth_to_color': {'rotation_column_major': list(transform.rotation),
                        'translation_m': list(transform.translation),
                        'semantics': 'p_color = R_color_depth @ p_depth + t_color_depth',
                        'source': 'installed device profile get_extrinsics_to(color)',
                        'world_or_hand_eye_calibration': False},
                    'depth_scale_m_per_z16': c.profile.get_device().first_depth_sensor().get_depth_scale(),
                    'color_fps': cp.fps(), 'depth_fps': dp.fps(),
                    'device_name': c.profile.get_device().get_info(rs.camera_info.name),
                    'firmware': c.profile.get_device().get_info(rs.camera_info.firmware_version)}
            # Warm-up once per session; subsequent observations never restart.
            futures = [self.pool.submit(self._warm, c) for c in self.cameras]
            for f in futures: f.result()
            for index, c in enumerate(self.cameras):
                thread = threading.Thread(target=self._pump, args=(index, c), daemon=True)
                thread.start(); self.readers.append(thread)
            return self
        except BaseException:
            self.__exit__(None, None, None); raise
    @staticmethod
    def _warm(camera):
        for _ in range(8): camera._pipeline.wait_for_frames(5000)
    def _read(self, camera):
        start = time.monotonic(); wall_start = time.time()
        frames = camera._pipeline.wait_for_frames(5000)
        raw_color, raw_depth = frames.get_color_frame(), frames.get_depth_frame()
        raw_metadata = {'color': frame_metadata(raw_color, self.rs), 'depth': frame_metadata(raw_depth, self.rs)}
        aligned = camera._align.process(frames)
        color, depth = aligned.get_color_frame(), aligned.get_depth_frame()
        if not color or not depth: raise RuntimeError('RGBD_FRAME_MISSING')
        end = time.monotonic(); wall_end = time.time()
        return {'rgb': np.asanyarray(color.get_data()).copy(),
            'depth_raw': np.asanyarray(depth.get_data()).copy(),
            'color_intrinsics': intrinsics(color.profile.as_video_stream_profile().get_intrinsics()),
            'aligned_depth_intrinsics': intrinsics(depth.profile.as_video_stream_profile().get_intrinsics()),
            'captured_monotonic': end, 'captured_at': wall_end,
            'capture_interval_monotonic': [start, end], 'host_wall_read_interval': [wall_start, wall_end],
            'color_timestamp_ms': color.get_timestamp(), 'depth_timestamp_ms': depth.get_timestamp(),
            'color_timestamp_domain': str(color.get_frame_timestamp_domain()),
            'depth_timestamp_domain': str(depth.get_frame_timestamp_domain()),
            'color_frame_number': color.get_frame_number(), 'depth_frame_number': depth.get_frame_number(),
            'raw_frame_metadata': raw_metadata,
            'depth_scale_m_per_z16': camera.profile.get_device().first_depth_sensor().get_depth_scale()}
    def read(self):
        deadline = time.monotonic()+6
        with self.condition:
            while True:
                if self.error: raise RuntimeError('CAMERA_READER_FAILED:'+self.error)
                if len(self.latest) == len(self.configs):
                    result = [self.latest[i] for i in range(len(self.configs))]
                    fresh = all(time.monotonic()-s['captured_monotonic'] <= .5 for s in result)
                    new = all(s['depth_frame_number'] != self.last_numbers.get(i) for i, s in enumerate(result))
                    if fresh and new:
                        self.last_numbers = {i: s['depth_frame_number'] for i, s in enumerate(result)}
                        return result
                left = deadline-time.monotonic()
                if left <= 0: raise RuntimeError('FRESH_RGBD_UNAVAILABLE')
                self.condition.wait(min(left, .1))
    def _pump(self, index, camera):
        try:
            while not self.stop.is_set():
                sample = self._read(camera)
                with self.condition:
                    self.latest[index] = sample; self.condition.notify_all()
        except Exception as exc:
            if not self.stop.is_set():
                with self.condition:
                    self.error = type(exc).__name__+':'+str(exc); self.condition.notify_all()
    def __exit__(self, *_):
        self.stop.set()
        for thread in self.readers: thread.join(timeout=6)
        if self.pool: self.pool.shutdown(wait=True)
        for c in self.cameras:
            if c.camera_on: c.stop_camera()

def save_observation(run, index, samples, robot_sample, gripper_sample, task, phase, camera_configs=None, arm="left"):
    configs = camera_configs or CAMERAS
    if robot_sample.get("arm") != arm: raise ValueError("ROBOT_ARM_MISMATCH")
    directory = new_run(run/'observations'/('%06d' % index))
    write_json(directory/'robot_raw.json', robot_sample)
    write_json(directory/'gripper_raw.json', gripper_sample)
    canonical = robot_sample['canonical']
    if canonical is None: raise RuntimeError('CANONICAL_STATE_UNAVAILABLE')
    raw_gripper = gripper_sample['raw_return']
    if raw_gripper[0] != 0: raise RuntimeError('GRIPPER_READ_FAILED:%s' % raw_gripper[0])
    opening = None
    positions = raw_gripper[1].get('pos') if isinstance(raw_gripper[1], dict) else None
    if positions and type(positions[0]) in (int, float) and 0 <= positions[0] <= 1000:
        opening = positions[0]/1000
    canonical['gripper_state'] = {'opening': opening, 'raw': raw_gripper[1],
        'quantity': 'opening, not force', 'zero': 'fully closed', 'one': 'fully open',
        'effort_current_force_units_validity': 'UNKNOWN; raw retained, zero does not prove no contact'}
    rgb, depths, calibration = [], [], {}
    for (selector, role, serial), original in zip(configs, samples):
        sample = dict(original); color = sample.pop('rgb'); raw = sample.pop('depth_raw')
        z = (raw.astype(np.float32)*sample['depth_scale_m_per_z16']).astype(np.float32)
        valid = np.isfinite(z) & (z > 0) & (raw < np.iinfo(np.uint16).max); z[~valid] = 0
        Image.fromarray(color).save(directory/(selector+'.png'))
        np.save(directory/(selector+'-z16.npy'), raw, allow_pickle=False)
        np.save(directory/(selector+'-depth-m.npy'), z, allow_pickle=False)
        Image.fromarray(valid.astype(np.uint8)*255).save(directory/(selector+'-valid.png'))
        rgb.append({'camera': selector, 'role': role, 'serial': serial,
            'file': str((directory/(selector+'.png')).relative_to(run)),
            'sha256': sha(directory/(selector+'.png')), 'captured_monotonic': sample['captured_monotonic']})
        depths.append({'camera': selector, 'serial': serial, **sample,
            'depth_path': selector+'-depth-m.npy', 'depth_sha256': sha(directory/(selector+'-depth-m.npy')),
            'raw_z16_path': selector+'-z16.npy', 'raw_z16_sha256': sha(directory/(selector+'-z16.npy')),
            'validity_path': selector+'-valid.png', 'validity_sha256': sha(directory/(selector+'-valid.png')),
            'unit': 'm', 'dtype': 'float32', 'depth_convention': 'opencv_optical_z',
            'validity_policy': 'positive raw Z16 excluding untrusted storage ceiling 65535; no accuracy/confidence claim',
            'raw_storage_ceiling_pixels': int((raw == np.iinfo(np.uint16).max).sum()),
            'alignment': 'lab driver rs.align(color); no World transform', 'valid_fraction': float(valid.mean())})
        k = sample['color_intrinsics']
        calibration[selector] = {'intrinsic': k['matrix'], 'resolution': k['resolution'],
            'axes': 'opencv_optical (+x right,+y down,+z forward)',
            'distortion_model': k['distortion_model'], 'distortion_coefficients': k['distortion_coefficients'],
            'pose_world_status': 'UNKNOWN_NOT_CALIBRATED'}
    times = [s['captured_monotonic'] for s in samples]
    obs = {'schema': 'astra.onsite.observation.rgbd.v1', 'version': 'astra.onsite.observation.rgbd.v1',
        'episode_id': run.name, 'observation_id': 'obs-'+uuid.uuid4().hex,
        'execution_epoch': 0, 'task': task, 'capture_phase_marker': phase,
        'epoch_semantics': 'Observer-only Store epoch; external teleoperation is not an Owner execution count',
        'captured_monotonic': min(times), 'host_readback_span_ms': 1000*(max(times)-min(times)),
        'timestamp_domain': 'yanglab host monotonic; independent device domains retained',
        'exposure_synchronization': 'UNKNOWN; host read completion span is not exposure skew',
        'rgb': rgb, 'depth': depths, 'calibration': calibration,
        'state': {'canonical_states': {arm: canonical}, 'actual_grasp_center_world': None, 'flange_pose_world': None},
        'source': 'REAL_RGBD_AND_REALMAN_READ_ONLY', 'execution_permitted': False,
        'unknowns': ['camera_to_world', 'wrist_hand_eye', 'actual_pad_center_TCP',
            'SDK_reported_pose_frame', 'exposure_synchronization', 'independent_physical_outcome']}
    write_json(directory/'observation.json', obs)
    return obs, directory

def video_panel(samples, index, phase, camera_configs=None):
    configs = camera_configs or CAMERAS
    import cv2
    panels = []
    for (selector, role, _), sample in zip(configs, samples):
        rgb = sample['rgb']; raw = sample['depth_raw']; valid = raw > 0
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        bgr[~valid] = (bgr[~valid]*.35).astype(np.uint8)
        cv2.putText(bgr, '%s | %s | depth valid %.1f%%' % (selector, role, valid.mean()*100),
            (8, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 1)
        panels.append(bgr)
    panel = np.concatenate(panels, axis=1)
    cv2.putText(panel, 'sample %d | %s | CAMERA OPTICAL ONLY; World/TCP UNKNOWN' % (index, phase),
        (8, panel.shape[0]-12), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 255), 1)
    return panel
