#!/usr/bin/env python3
"""One real RGB-D/state observation. No executor, motion or configuration calls.
Reuses the lab RealSenseCamera factory and its pipeline/align objects. Reads
frames directly so the driver's timeout handler cannot restart a camera.
"""
import argparse, concurrent.futures, hashlib, importlib.util, json, sys, time, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from io_utils import new_run, write_json
from realman_api2_readonly import SDKReadOnly

DRIVER = Path('/home/tongji/aloha/RealMan_Control/realsense.py')
CAMERA_PACKAGE = Path('/home/tongji/aloha/shadow_camera/src')
CAMERAS = [('wrist', 'left_wrist', '254522073676'),
           ('fixed', 'tabletop', '346222072496'),
           ('assembly', 'overhead', '344422071480')]

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def intrinsics(k):
    return {'matrix': [[k.fx, 0, k.ppx], [0, k.fy, k.ppy], [0, 0, 1]],
            'resolution': [k.width, k.height], 'distortion_model': str(k.model),
            'distortion_coefficients': list(k.coeffs)}

def read_one(camera):
    import numpy as np
    # Discard warm-up frames on this persistent pipeline; never reset/retry.
    for _ in range(8): camera._pipeline.wait_for_frames(5000)
    start = time.monotonic()
    frames = camera._pipeline.wait_for_frames(5000)
    aligned = camera._align.process(frames)
    color, depth = aligned.get_color_frame(), aligned.get_depth_frame()
    if not color or not depth: raise RuntimeError('RGBD_FRAME_MISSING')
    end, wall = time.monotonic(), time.time()
    ci = color.profile.as_video_stream_profile().get_intrinsics()
    di = depth.profile.as_video_stream_profile().get_intrinsics()
    return {'rgb': np.asanyarray(color.get_data()).copy(),
            'depth_raw': np.asanyarray(depth.get_data()).copy(),
            'color_intrinsics': intrinsics(ci), 'aligned_depth_intrinsics': intrinsics(di),
            'captured_monotonic': end, 'captured_at': wall,
            'capture_interval_monotonic': [start, end],
            'color_timestamp_ms': color.get_timestamp(), 'depth_timestamp_ms': depth.get_timestamp(),
            'color_timestamp_domain': str(color.get_frame_timestamp_domain()),
            'depth_timestamp_domain': str(depth.get_frame_timestamp_domain()),
            'color_frame_number': color.get_frame_number(), 'depth_frame_number': depth.get_frame_number(),
            'depth_scale_m_per_z16': camera.profile.get_device().first_depth_sensor().get_depth_scale()}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task', required=True)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    run = new_run(a.output or ROOT/'logs'/('onsite-rgbd-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]))
    cameras = []
    record = {'run': str(run), 'task': a.task, 'execution_permitted': False,
              'motion_commands_sent': 0, 'gripper_commands_sent': 0}
    write_json(run/'source.json', {'camera_driver': str(DRIVER), 'sha256': sha(DRIVER),
        'camera_package': str(CAMERA_PACKAGE), 'arm_identity': 'user confirmed left=192.168.1.19; unchanged 2026-10-11',
        'camera_mapping': CAMERAS, 'mapping_semantics': 'selector aliases only; not simulated camera poses',
        'calibration': 'UNKNOWN; user reports never calibrated', 'task_verbatim': a.task})
    try:
        import numpy as np
        from PIL import Image
        import pyrealsense2 as rs
        sys.path.insert(0, str(CAMERA_PACKAGE))
        spec = importlib.util.spec_from_file_location('lab_realsense_readonly', DRIVER)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        present = [d.get_info(rs.camera_info.serial_number) for d in rs.context().devices]
        write_json(run/'devices.json', {'serials': present})
        if not all(serial in present for _, _, serial in CAMERAS): raise RuntimeError('REQUIRED_CAMERA_MISSING')
        for _, _, serial in CAMERAS:
            camera = mod.RealSenseCamera(serial_num=serial, is_depth_frame=True)
            cameras.append(camera); camera.start_camera()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(read_one, c) for c in cameras]
            samples = [f.result() for f in futures]
        rgb, depth_rows, calibration = [], [], {}
        for (selector, role, serial), sample in zip(CAMERAS, samples):
            color = sample.pop('rgb'); raw = sample.pop('depth_raw')
            z = (raw.astype(np.float32)*sample['depth_scale_m_per_z16']).astype(np.float32)
            valid = np.isfinite(z) & (z > 0); z[~valid] = 0
            Image.fromarray(color).save(run/(selector+'.png'))
            np.save(run/(selector+'-z16.npy'), raw, allow_pickle=False)
            np.save(run/(selector+'-depth-m.npy'), z, allow_pickle=False)
            Image.fromarray(valid.astype(np.uint8)*255).save(run/(selector+'-valid.png'))
            rgb.append({'camera': selector, 'role': role, 'serial': serial, 'file': selector+'.png',
                        'sha256': sha(run/(selector+'.png')), 'captured_monotonic': sample['captured_monotonic']})
            depth_rows.append({'camera': selector, 'serial': serial, **sample,
                'depth_path': selector+'-depth-m.npy', 'depth_sha256': sha(run/(selector+'-depth-m.npy')),
                'validity_path': selector+'-valid.png', 'validity_sha256': sha(run/(selector+'-valid.png')),
                'unit': 'm', 'dtype': 'float32', 'depth_convention': 'opencv_optical_z',
                'alignment': 'existing lab driver rs.align(color); optical frame; no World extrinsics',
                'valid_fraction': float(valid.mean()),
                'positive_depth_min_max_m': [float(z[valid].min()), float(z[valid].max())] if valid.any() else None})
            k = sample['color_intrinsics']
            calibration[selector] = {'intrinsic': k['matrix'], 'resolution': k['resolution'],
                'axes': 'opencv_optical (+x right,+y down,+z forward)',
                'distortion_model': k['distortion_model'], 'distortion_coefficients': k['distortion_coefficients'],
                'pose_world_status': 'UNKNOWN_NOT_CALIBRATED'}
        new_run(run/'sdk')
        with SDKReadOnly(run/'sdk') as session:
            connection = session.connect('left', '192.168.1.19', 8080)
            write_json(run/'left_connection.json', connection)
            if not connection['connected']: raise RuntimeError('LEFT_CONNECTION_FAILED')
            state = session.snapshot('left')
            write_json(run/'left_sdk_sample.json', state)
            # Exact previously used read-only API; never hand_follow_pos.
            started = time.time()
            gripper = session.connected['left'].rm_get_rm_plus_state_info()
            write_json(run/'gripper_raw.json', {'function': 'rm_get_rm_plus_state_info',
                'started_at': started, 'finished_at': time.time(), 'raw_return': gripper,
                'units': 'raw SDK telemetry; not a force estimate'})
        canonical = state['canonical']
        if canonical is None: raise RuntimeError('CANONICAL_STATE_UNAVAILABLE')
        gripper_state = {'return_code': gripper[0], 'raw': gripper[1], 'opening': None,
                         'opening_semantics': '0 fully closed, 1 fully open; not force control'}
        if gripper[0] == 0 and isinstance(gripper[1], dict) and isinstance(gripper[1].get('pos'), list) and gripper[1]['pos']:
            value = gripper[1]['pos'][0]
            if type(value) in (int, float) and 0 <= value <= 1000: gripper_state['opening'] = value/1000
        canonical['gripper_state'] = gripper_state
        captured = [s['captured_monotonic'] for s in samples]
        span = max(captured)-min(captured)
        obs = {'schema': 'astra.onsite.observation.rgbd.v1', 'version': 'astra.onsite.observation.rgbd.v1',
            'episode_id': run.name, 'observation_id': 'obs-'+uuid.uuid4().hex, 'execution_epoch': 0,
            'task': a.task, 'captured_monotonic': min(captured), 'capture_span_s': span,
            'timestamp_domain': 'yanglab host monotonic; device timestamps retained per camera, not cross-device synchronized',
            'frame': 'REALMAN_WORLD_REGISTRATION_UNKNOWN', 'pose_convention': 'SDK m/rad RPY; pad center World pose UNKNOWN',
            'rgb': rgb, 'depth': depth_rows, 'calibration': calibration,
            'state': {'canonical_states': {'left': canonical}, 'actual_grasp_center_world': None, 'flange_pose_world': None},
            'source': 'REAL_RGBD_AND_REALMAN_READ_ONLY', 'execution_permitted': False,
            'unknowns': ['camera_to_realman_world', 'wrist_hand_eye', 'flange_to_actual_pad_center',
                         'public_support_plane_in_world', 'FK_registered_to_world', 'in_flight_STOP_acceptance']}
        write_json(run/'observation.json', obs)
        record.update(status='CAPTURED', capture_span_ms=span*1000,
            joint_deg=canonical['joint_deg'], ee_pose=canonical['ee_pose'],
            work_frame=canonical['work_frame'], tool_frame=canonical['tool_frame'],
            system_error=canonical['system_error'], gripper=gripper_state,
            valid_depth_fractions={r['camera']: r['valid_fraction'] for r in depth_rows})
    except Exception as exc:
        record.update(status='FAILED', error=type(exc).__name__+':'+str(exc))
    finally:
        for camera in cameras:
            if camera.camera_on: camera.stop_camera()
        write_json(run/'summary.json', record)
        print(json.dumps(record, ensure_ascii=False, allow_nan=False), flush=True)
    return 0 if record['status']=='CAPTURED' else 1

if __name__ == '__main__': raise SystemExit(main())
