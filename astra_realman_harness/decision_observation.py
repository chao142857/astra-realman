"""Four real images plus two read-only SDK canonical states, owned by the harness."""
import time
import uuid
from camera_session import CameraSession
from realman_api2_readonly import SDKReadOnly
from io_utils import write_json, new_run

def capture_decision(config, run, task, previous=None, camera_session=None):
    if camera_session is None:
        with CameraSession(config["devices"]["cameras"]) as cameras:
            return capture_decision(config, run, task, previous, cameras)
    started = time.time()
    samples, states, failures = {}, {}, []
    sdk_run = new_run(run/"sdk")
    with SDKReadOnly(sdk_run) as sdk:
        for arm in ("left", "right"):
            endpoint = config["devices"]["arms"][arm]
            connection = sdk.connect(arm, endpoint["host"], endpoint["port"], 6)
            if not connection["connected"]:
                states[arm] = {}
                failures.append({"device": arm, "error": "SDK_CONNECTION_FAILED"})
                continue
            samples[arm] = sdk.snapshot(arm)
            states[arm] = samples[arm].get("canonical") or {}
            if not states[arm]:
                failures.append({"device": arm, "error": "SDK_CANONICAL_STATE_UNAVAILABLE"})
    images, camera_failures, metrics = camera_session.snapshot(run)
    failures += camera_failures
    times = [c["captured_at"] for c in images] + [s["timestamp"] for s in states.values() if s.get("timestamp")]
    observation = {
        "schema_version": "astra.decision.observation.v1",
        "observation_id": "shadow-" + uuid.uuid4().hex,
        "task": task, "captured_at": min(times) if times else started,
        "capture_started_at": started, "capture_finished_at": time.time(),
        "source": {"kind": "real_capture", "physical": True,
                   "robot_transport": "realman_api2_sdk_readonly"},
        "canonical_states": states, "cameras": images, "camera_capture": metrics,
        "capture_span_ms": metrics["capture_span_ms"], "capture_failures": failures,
        "frames": config["frames"], "allowed_proposal_arms": config["safety"]["allowed_arms"],
        "decision_safety_context": config.get("decision_safety_context"),
        "previous": previous, "hardware_commands_sent": 0, "motion_commands_sent": 0
    }
    write_json(run/"sdk_samples.json", samples)
    write_json(run/"observation.json", observation)
    return observation
