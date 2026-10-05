"""Live port for a single operator-authorized +World-Z 10 mm position step.

All setup is read-only. The sole actuation call is fixed in position_step().
No model output, arbitrary target, frame setter, stop/retry, or gripper API exists.
"""
import copy
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from io_utils import ROOT, write_json, read_json
from supervised_step import (EXACT_ACTION, HUMAN_EVIDENCE, SCHEMA_VERSION,
                             validate_step)

PYTHON = "/home/tongji/miniconda3/envs/dp/bin/python"
BINDING = ROOT / "docs/supervised_step_evidence.json"
CLAIM = ROOT / "logs/supervised-left-World-plusZ10mm-20261002.claim.json"
READ_NAMES = frozenset((
    "rm_get_robot_info", "rm_get_arm_software_info", "rm_get_teach_frame",
    "rm_get_arm_max_line_speed", "rm_get_arm_max_line_acc", "rm_get_DH_data",
    "rm_get_joint_min_pos", "rm_get_joint_max_pos",
))

def durable_claim(path, value):
    """O_EXCL and fsync; never delete or overwrite an ambiguous attempt."""
    path = Path(path)
    if path.resolve() != CLAIM.resolve():
        raise ValueError("CLAIM_PATH_FIXED")
    payload = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n").encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        # Reservation stays consumed. A failed/partial write never permits dispatch.
        raise

class SupervisedPort:
    def __init__(self, session, run, execute=False):
        self.session = session
        self.run = Path(run)
        self.execute_enabled = execute
        self.sequence = 0
        self.hardware_calls_attempted = 0
        self.before_dispatch = None
        self.after_snapshot = None
        self.evidence = None
        self.model_input = None

    def _read(self, name, obj, conversion):
        if name not in READ_NAMES:
            raise ValueError("READ_NOT_ALLOWLISTED")
        self.sequence += 1
        stem = "%03d-extra-%s" % (self.sequence, name)
        event = {"function": name, "arm": "left", "started_at": time.time(),
                 "call_site": str(Path(__file__).resolve()),
                 "ip": "192.168.1.19"}
        write_json(self.run / (stem + "-start.json"), event)
        handle = self.session.connected["left"].handle
        try:
            argument = obj if isinstance(obj, ctypes.Array) else ctypes.byref(obj)
            ret = getattr(self.session.sdk, name)(handle, argument)
            event.update(return_code=ret, raw_hex=bytes(obj).hex(),
                         value=conversion(obj), finished_at=time.time())
            write_json(self.run / (stem + "-result.json"), event)
        except BaseException as exc:
            event.update(exception=repr(exc), finished_at=time.time())
            write_json(self.run / (stem + "-exception.json"), event)
            raise
        if type(ret) is not int or ret != 0:
            raise RuntimeError("READ_FAILED:%s:%s" % (name, ret))
        return event

    def capture(self):
        sdk = self.session.sdk
        reads = {}
        reads["rm_get_robot_info"] = self._read(
            "rm_get_robot_info", sdk.rm_robot_info_t(),
            lambda info: {key: int(getattr(info, key)) for key in
                          ("arm_dof", "arm_model", "force_type", "robot_controller_version")})
        generation = reads["rm_get_robot_info"]["value"]["robot_controller_version"]
        reads["rm_get_arm_software_info"] = self._read(
            "rm_get_arm_software_info", sdk.rm_arm_software_version_t(),
            lambda version: version.to_dict(generation))
        for name, kind in (("rm_get_teach_frame", ctypes.c_int),
                           ("rm_get_arm_max_line_speed", ctypes.c_float),
                           ("rm_get_arm_max_line_acc", ctypes.c_float)):
            reads[name] = self._read(name, kind(), lambda value: value.value)
        reads["rm_get_DH_data"] = self._read(
            "rm_get_DH_data", sdk.rm_dh_t(),
            lambda value: {key: list(getattr(value, key)) for key in ("d", "a", "alpha", "offset")})
        for name in ("rm_get_joint_min_pos", "rm_get_joint_max_pos"):
            reads[name] = self._read(name, (ctypes.c_float * 6)(), list)
        arms = {}
        for arm in ("right", "left"):  # Left pose is the last hardware-state read.
            raw = self.session.snapshot(arm)
            if raw["canonical"] is None:
                raise RuntimeError("CANONICAL_READ_FAILED:" + arm)
            arms[arm] = raw["canonical"]
        result = {"timestamp": time.time(), "arms": arms, "readbacks": reads,
                  "teach_state": reads["rm_get_teach_frame"]["value"]}
        write_json(self.run / ("snapshot-%03d.json" % self.sequence), result)
        return result

    @staticmethod
    def parameters(snapshot):
        readbacks = snapshot["readbacks"]
        return {"controller_dh": readbacks["rm_get_DH_data"]["value"],
                "joint_limits_deg": [list(pair) for pair in zip(
                    readbacks["rm_get_joint_min_pos"]["value"],
                    readbacks["rm_get_joint_max_pos"]["value"])]}

    def _fresh_pair(self):
        snapshots = [self.capture()]
        time.sleep(0.15)
        snapshots.append(self.capture())
        for snapshot in snapshots:
            if self.parameters(snapshot) != {key: self.model_input[key]
                                             for key in ("controller_dh", "joint_limits_deg")}:
                raise RuntimeError("CONTROLLER_MODEL_OR_LIMITS_CHANGED")
        return snapshots

    def prepare(self):
        if not BINDING.is_file():
            raise RuntimeError("BINDING_EVIDENCE_MISSING")
        if self.execute_enabled and CLAIM.exists():
            raise RuntimeError("PERSISTENT_ONE_SHOT_ALREADY_CLAIMED")
        measured = self.capture()
        info = measured["readbacks"]["rm_get_robot_info"]["value"]
        software = measured["readbacks"]["rm_get_arm_software_info"]["value"]
        if info != {"arm_dof": 6, "arm_model": 0, "force_type": 3, "robot_controller_version": 3}:
            raise RuntimeError("MEASURED_CONTROLLER_VARIANT_MISMATCH")
        if software.get("product_version") != "RM65-6FB":
            raise RuntimeError("MEASURED_PRODUCT_MISMATCH")
        self.model_input = dict(
            self.parameters(measured), model_enum=info["arm_model"],
            force_type_enum=info["force_type"], canonical_left=measured["arms"]["left"],
            readbacks=copy.deepcopy(measured["readbacks"]),
            input_evidence=str(self.run / "kinematics-input.json"),
            binding_evidence=str(BINDING))
        write_json(self.run / "kinematics-input.json", self.model_input)
        command = [PYTHON, "-I", "-B", str(ROOT / "supervised_kinematics.py"),
                   "--input", str(self.run / "kinematics-input.json"),
                   "--output", str(self.run / "kinematics-result.json")]
        # Offline worker has no connection or motion interface. Timeout affects only math.
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=30, cwd=str(ROOT), check=False)
        write_json(self.run / "kinematics-process.json",
                   {"command": command, "return_code": completed.returncode,
                    "stdout": completed.stdout, "stderr": completed.stderr})
        result = read_json(self.run / "kinematics-result.json")
        if completed.returncode != 0 or result.get("path") is None:
            raise RuntimeError("OFFLINE_KINEMATICS_REJECT:" + str(result.get("errors", [])))
        snapshots = self._fresh_pair()
        latest = snapshots[-1]
        self.evidence = {
            "schema_version": SCHEMA_VERSION, "source": "trusted_supervised_runner",
            "human": copy.deepcopy(HUMAN_EVIDENCE),
            "controller": {"ip": latest["arms"]["left"]["connection"]["ip"],
                           "model": software["product_version"],
                           "generation": info["robot_controller_version"],
                           "sdk_handle_id": latest["arms"]["left"]["connection"]["sdk_handle_id"]},
            "speed": {"percent": 1,
                      "max_line_m_s": latest["readbacks"]["rm_get_arm_max_line_speed"]["value"],
                      "max_acc_m_s2": latest["readbacks"]["rm_get_arm_max_line_acc"]["value"]},
            "prechecks": snapshots, "path": result["path"]}
        write_json(self.run / "prepared-evidence.json", self.evidence)
        return copy.deepcopy(self.evidence)

    def refresh(self):
        refreshed = copy.deepcopy(self.evidence)
        refreshed["prechecks"] = self._fresh_pair()
        self.evidence = refreshed
        write_json(self.run / "refreshed-evidence.json", refreshed)
        return copy.deepcopy(refreshed)

    def position_step(self, *, axis, step_m, speed_percent, block):
        if (not self.execute_enabled or self.hardware_calls_attempted != 0 or
                type(axis) is not int or axis != 2 or type(step_m) not in (int, float) or step_m != .01 or
                type(speed_percent) is not int or speed_percent != 1 or type(block) is not int or block != 1):
            raise RuntimeError("FIXED_SINGLE_STEP_ONLY")
        safety = validate_step(EXACT_ACTION, self.evidence, time.time())
        if safety["outcome"] != "PASS_EXECUTABLE":
            raise RuntimeError("FINAL_DISPATCH_GATE_REJECT:" + ",".join(safety["errors"]))
        connection = self.session.connection_info["left"]
        if connection["ip"] != "192.168.1.19":
            raise RuntimeError("DISPATCH_IP_MISMATCH")
        self.before_dispatch = copy.deepcopy(self.evidence["prechecks"][-1]["arms"]["left"])
        claim = {"authorization": HUMAN_EVIDENCE, "action": EXACT_ACTION, "run": str(self.run),
                 "reserved_at": time.time(), "policy": "consumed permanently; never auto-retry",
                 "evidence_sha256": hashlib.sha256(json.dumps(
                     self.evidence, sort_keys=True, allow_nan=False).encode()).hexdigest()}
        durable_claim(CLAIM, claim)
        write_json(self.run / "dispatch-intent.json",
                   {"function": "rm_set_pos_step", "ip": connection["ip"],
                    "axis": 2, "step_m": .01, "speed_percent": 1, "block": 1,
                    "timestamp": time.time(), "claim": str(CLAIM)})
        final_check = validate_step(EXACT_ACTION, self.evidence, time.time())
        if final_check["outcome"] != "PASS_EXECUTABLE":
            raise RuntimeError("STATE_EXPIRED_AFTER_DURABLE_CLAIM")
        self.hardware_calls_attempted = 1  # Before entering C; exceptions may be after send.
        started = time.time()
        try:
            ret = self.session.sdk.rm_set_pos_step(
                self.session.connected["left"].handle, 2, .01, 1, 1)
        except BaseException as exc:
            write_json(self.run / "dispatch-exception.json",
                       {"started_at": started, "finished_at": time.time(), "exception": repr(exc),
                        "motion_command_attempts": 1, "retry_allowed": False})
            raise
        write_json(self.run / "dispatch-result.json",
                   {"started_at": started, "finished_at": time.time(), "return_code": ret,
                    "motion_command_attempts": 1, "retry_allowed": False})
        return ret

    def observe_result(self):
        self.after_snapshot = self.capture()
        write_json(self.run / "post-observation.json", self.after_snapshot)
        if self.after_snapshot["teach_state"] != 0:
            raise RuntimeError("POST_TEACH_FRAME_CHANGED")
        if self.after_snapshot["arms"]["right"]["system_error"]["has_error"]:
            raise RuntimeError("POST_RIGHT_ERROR")
        return self.after_snapshot["arms"]["left"]
