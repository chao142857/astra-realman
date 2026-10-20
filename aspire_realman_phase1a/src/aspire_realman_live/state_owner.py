"""Single-arm SDKReadOnly.snapshot inbox preparation; no SDK or transport.

Future sole SDK owner may publish one already-acquired five-read sample with its
host receipt interval. This module cannot connect/poll, construct RobotState,
start an arm, or dispatch motion. Existing LiveSource/CAP runtime stays unbound.
"""
import copy
import math
import threading
import time


READ_LABELS = ("work_before", "tool_before", "state", "work_after", "tool_after")
SOURCE_KINDS = {"LIVE_SDK_READ_ONLY", "HISTORICAL_REPLAY", "OFFLINE_SDK_TRANSPORT_FIXTURE"}


def vector(value, size):
    return (isinstance(value, (list, tuple)) and len(value) == size
            and all(type(x) in (int, float) and math.isfinite(x) for x in value))


class SingleArmStateOwner:
    """One explicit arm and producer identity, immutable diagnostic snapshots."""
    def __init__(self, owner_id, arm, *, source_kind, clock_id, expected_fingerprints=None):
        if not owner_id or arm not in {"left", "right"} or source_kind not in SOURCE_KINDS or not clock_id:
            raise ValueError("EXPLICIT_SINGLE_ARM_SOURCE_AND_CLOCK_REQUIRED")
        self.owner_id, self.arm = owner_id, arm
        self.source_kind, self.clock_id = source_kind, clock_id
        self.expected = copy.deepcopy(expected_fingerprints)
        self._lock = threading.Lock()
        self._latest = None
        self.closed = False
        self.failure = None

    def connect(self, *args, **kwargs):
        raise RuntimeError("PHYSICAL_CONNECTION_DISABLED_OWNER_PREPARATION_ONLY")

    start = connect
    poll_once = connect

    def publish(self, sample, *, owner_id, sequence, read_interval_monotonic_s, host_clock_id):
        try:
            raw = copy.deepcopy(sample["canonical"])
            if owner_id != self.owner_id or sample["arm"] != self.arm or raw["arm"] != self.arm:
                raise ValueError("OWNER_OR_SINGLE_ARM_SCOPE_MISMATCH")
            if host_clock_id != self.clock_id:
                raise ValueError("HOST_BOOT_OR_CLOCK_DOMAIN_MISMATCH")
            if type(sequence) is not int or sequence < 1:
                raise ValueError("POSITIVE_SEQUENCE_REQUIRED")
            if not vector(read_interval_monotonic_s, 2) or not 0 <= read_interval_monotonic_s[0] <= read_interval_monotonic_s[1]:
                raise ValueError("READ_RECEIPT_INTERVAL_REQUIRED")
            if not vector(raw["joint_deg"], 6) or type(raw.get("timestamp")) not in (int, float) or not math.isfinite(raw["timestamp"]):
                raise ValueError("SIX_FINITE_JOINT_DEGREES_AND_SOURCE_TIME_REQUIRED")
            pose = raw["ee_pose"]
            if pose.get("units") != {"xyz": "m", "rpy": "rad"} or not vector(pose.get("xyz_m"), 3) or not vector(pose.get("rpy_rad"), 3):
                raise ValueError("SDK_METRES_RADIANS_REQUIRED_NO_SCALE_GUESS")
            if raw.get("frame_snapshot_stable") is not True:
                raise ValueError("WORK_TOOL_CHANGED_DURING_SAMPLE")
            frames = {k: raw[k]["definition_fingerprint"] for k in ("work_frame", "tool_frame")}
            if self.expected is not None and frames != self.expected:
                raise ValueError("CURRENT_FRAME_FINGERPRINT_MISMATCH")
            velocity = raw.get("joint_velocity_deg_s")
            if velocity is not None and not vector(velocity, 6):
                raise ValueError("INVALID_MEASURED_VELOCITY")
            if self.source_kind == "LIVE_SDK_READ_ONLY":
                if any(type(sample.get("calls", {}).get(k, {}).get("return_code")) is not int
                       or sample["calls"][k]["return_code"] != 0 for k in READ_LABELS):
                    raise ValueError("FIVE_SUCCESSFUL_SDK_READS_REQUIRED")
            with self._lock:
                if self.closed or self.failure:
                    raise RuntimeError("STATE_OWNER_NOT_RUNNING")
                if self._latest is not None:
                    if sequence <= self._latest["sequence"] or read_interval_monotonic_s[1] <= self._latest["read_interval_monotonic_s"][1]:
                        raise ValueError("REPEATED_OR_REGRESSED_SAMPLE")
                    if self.source_kind == "LIVE_SDK_READ_ONLY" and raw["timestamp"] <= self._latest["canonical_state"]["timestamp"]:
                        raise ValueError("UNCHANGED_SOURCE_TIMESTAMP_CANNOT_BE_FRESHENED")
                self._latest = {"owner_id": self.owner_id, "arm_scope": [self.arm],
                    "source_kind": self.source_kind, "sequence": sequence,
                    "host_clock_id": self.clock_id, "source_timestamp_domain": "host_epoch_from_SDKReadOnly_state_finished_at",
                    "device_timestamp": None, "device_time_domain": "NOT_PROVIDED_BY_CURRENT_SDK_SNAPSHOT",
                    "read_interval_monotonic_s": list(read_interval_monotonic_s), "canonical_state": raw,
                    "joint_velocity_deg_s": velocity, "gripper_telemetry": raw.get("gripper_state"),
                    "motion_permitted": False, "snapshot_atomic": raw.get("snapshot_atomic", False),
                    "current_field_binding_verified": False, "native_robot_state_available": False,
                    "world_transform": None, "actual_grasp_tcp": None}
        except Exception as exc:
            self.fail(type(exc).__name__+":"+str(exc))
            raise

    def read(self, *, now_monotonic_s=None, now_epoch_s=None, host_clock_id=None, max_age_s=1.0):
        now_mono = time.monotonic() if now_monotonic_s is None else now_monotonic_s
        now_wall = time.time() if now_epoch_s is None else now_epoch_s
        with self._lock:
            if self._latest is None:
                raise RuntimeError("NO_STATE_SAMPLE_NO_SYNTHETIC_FALLBACK")
            result = copy.deepcopy(self._latest)
            running = not self.closed and self.failure is None
            result["owner_error"] = self.failure
        interval = result["read_interval_monotonic_s"]
        clock_match = host_clock_id == self.clock_id
        source_age = now_wall-result["canonical_state"]["timestamp"] if clock_match else None
        source_fresh = source_age is not None and -.05 <= source_age <= max_age_s
        receipt_fresh = clock_match and -.001 <= now_mono-interval[1] and now_mono-interval[0] <= max_age_s
        result["quality"] = {"owner_running": running, "clock_match": clock_match,
            "source_epoch_age_s": source_age, "host_read_duration_ms": (interval[1]-interval[0])*1000,
            "host_receipt_age_bounds_s": [now_mono-interval[1], now_mono-interval[0]] if clock_match else None,
            "source_epoch_fresh": source_fresh,
            "host_receipt_fresh": receipt_fresh,
            "live_host_time_eligible": running and self.source_kind == "LIVE_SDK_READ_ONLY" and receipt_fresh and source_fresh,
            "device_measurement_freshness_verified": False,
            "controller_timestamp_or_latency_bound_available": False,
            "endpoint_semantics": result["canonical_state"]["ee_pose"].get("frame_semantics_status", "UNKNOWN"),
            "velocity_available": result["joint_velocity_deg_s"] is not None,
            "native_robot_state_available": False,
            "reason": "READONLY_DIAGNOSTIC_NO_COMPLETE_NATIVE_BINDING; no zero velocity/TCP/World fallback"}
        return result

    def as_native_state(self):
        raise RuntimeError("CURRENT_FIELD_BINDING_AND_NATIVE_CODEC_NOT_ENABLED")

    def fail(self, error):
        with self._lock:
            self.failure = str(error)

    def close(self):
        with self._lock:
            self.closed = True


def camera_state_receipt_bounds_ms(camera_interval, state_interval, *, camera_clock, state_clock):
    """Host receipt interval bounds only; NEVER a device-exposure sync claim."""
    if camera_clock != state_clock or not vector(camera_interval, 2) or not vector(state_interval, 2):
        return {"comparable": False, "minimum_ms": None, "maximum_ms": None}
    if camera_interval[0] > camera_interval[1] or state_interval[0] > state_interval[1]:
        raise ValueError("ORDERED_RECEIPT_INTERVALS_REQUIRED")
    minimum = max(0, camera_interval[0]-state_interval[1], state_interval[0]-camera_interval[1])
    maximum = max(abs(camera_interval[0]-state_interval[1]), abs(camera_interval[1]-state_interval[0]))
    return {"comparable": True, "minimum_ms": minimum*1000, "maximum_ms": maximum*1000,
            "physical_exposure_or_controller_synchronization_verified": False}
