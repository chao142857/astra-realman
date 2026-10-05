"""Canonical observations and persistent-camera capture; robot transport is read-only."""
import hashlib
import struct
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from io_utils import write_json, output_path
from realman_state import query_state, query_snapshot, RPY_METADATA
from camera_session import CameraSession

def offline_observation(task):
    now = time.time()
    # Synthetic coordinates exist only in this visibly marked test fixture.
    return {
        "schema_version": "astra.observation.v1", "observation_id": "offline-" + uuid.uuid4().hex,
        "captured_at": now, "source": {"kind": "offline_fixture", "physical": False},
        "task": task, "frames": {"right_base": {"status": "SYNTHETIC_TEST_ONLY"}},
        "cameras": [{"serial": "SYNTHETIC", "role": "synthetic_fixed",
                     "captured_at": now, "image_path": None, "intrinsics": None,
                     "extrinsics": None}],
        "robot": {"arms": {"right": {
            "available": True, "captured_at": now, "joints_deg": [0]*6, "controller_errors": [0],
            "gripper_opening_fraction": 0.5,
            "poses": {"tcp": {"frame": "right_base", "position_m": [0.3,0,0.3],
                             "rpy_rad": [0,0,0], "orientation_metadata": dict(RPY_METADATA)},
                      "flange": {"frame": "right_base", "position_m": [0.3,0,0.2],
                                "rpy_rad": [0,0,0], "orientation_metadata": dict(RPY_METADATA)}},
            "provenance": "SYNTHETIC_TEST_ONLY"}}},
    }

def _chunk(kind, data):
    return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)

def png_rgb(path, width, height, data, stride):
    if len(data) < stride * height or stride < width*3:
        raise ValueError("IMAGE_BUFFER_SIZE")
    pixels = b"".join(b"\0"+data[y*stride:y*stride+width*3] for y in range(height))
    body = (b"\x89PNG\r\n\x1a\n" +
            _chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0)) +
            _chunk(b"IDAT",zlib.compress(pixels)) + _chunk(b"IEND",b""))
    with output_path(path).open("xb") as f:
        f.write(body)
    return hashlib.sha256(body).hexdigest()


def capture_camera(config, run):
    """Standalone compatibility entry; multi-observation callers use CameraSession."""
    with CameraSession([config]) as session:
        cameras, failures, _ = session.snapshot(run)
        if failures or not cameras:
            raise RuntimeError("CAMERA_CAPTURE_FAILED:" + str(failures))
        return cameras[0]

def capture(config, run, task, camera_serials, arm_names, camera_session=None):
    if any(a not in config["safety"]["allowed_arms"] for a in arm_names):
        raise ValueError("ARM_CAPTURE_NOT_ENABLED")
    started = time.time()
    known = {c["serial"]: c for c in config["devices"]["cameras"]}
    if len(set(camera_serials)) != len(camera_serials) or any(s not in known for s in camera_serials):
        raise ValueError("CAMERA_NOT_IN_TRUSTED_CONFIG_OR_DUPLICATE")
    if camera_session is None:
        with CameraSession([known[s] for s in camera_serials]) as session:
            return capture(config, run, task, camera_serials, arm_names, session)
    if [c["serial"] for c in camera_session.configs] != list(camera_serials):
        raise ValueError("CAMERA_SESSION_CONFIG_MISMATCH")
    cameras, failures, metrics = camera_session.snapshot(run)
    arms = {}
    def read_arm(arm):
        endpoint = config["devices"]["arms"][arm]
        return query_snapshot(endpoint["host"], endpoint["port"], arm)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {a: pool.submit(read_arm, a) for a in arm_names}
        for arm, future in jobs.items():
            try:
                arms[arm] = future.result()
                failures.extend({"device": arm, **e} for e in arms[arm].get("query_failures", []))
            except Exception as exc:
                arms[arm] = {"available": False, "captured_at": time.time(),
                             "poses": {}, "joints_deg": None, "controller_errors": None,
                             "state_units_confirmed": False, "error": str(exc)[:300]}
                failures.append({"device": arm, "error_type": type(exc).__name__})
    times = [c["captured_at"] for c in cameras] + [s["captured_at"] for s in arms.values()]
    result = {
        "schema_version": "astra.observation.v1", "observation_id": "real-" + uuid.uuid4().hex,
        "captured_at": min(times) if times else started,
        "capture_started_at": started, "capture_finished_at": time.time(),
        "source": {"kind": "real_capture", "physical": True,
                   "camera_capture": "persistent pipelines; concurrent producers; atomic latest-buffer snapshot"},
        "task": task, "cameras": cameras,
        "robot": {"arms": arms, "enabled_arms": list(config["safety"]["allowed_arms"])},
        "capture_span_ms": metrics["capture_span_ms"], "camera_capture": metrics,
        "frames": config["frames"], "capture_failures": failures, "motion_commands_sent": 0,
    }
    write_json(run/"observation.json", result)
    return result
