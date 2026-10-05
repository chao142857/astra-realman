"""Pinned RealMan API2 read-only adapter; no motion/configuration API surface."""
import copy
import hashlib
import importlib.util
import importlib
import inspect
import json
import sys
import time
import traceback
from pathlib import Path
from io_utils import write_json, number, vector
from realman_state import RPY_METADATA

SDK_PACKAGE = Path("/home/tongji/aloha/RealMan_Control/Robotic_Arm")
SDK_LIBRARY = SDK_PACKAGE/"libs/linux_x86/libapi_c.so"
SDK_SOURCE = SDK_PACKAGE/"rm_robot_interface.py"
LIFECYCLE = frozenset(("rm_init", "rm_create_robot_arm", "rm_delete_robot_arm", "rm_destroy"))
READS = frozenset(("rm_get_current_arm_state", "rm_get_current_work_frame", "rm_get_current_tool_frame"))
ALLOWED = LIFECYCLE | READS
FRAME_EVIDENCE = "/home/tongji/alex/astra_realman_harness/docs/api2_frame_evidence.json"

def load_sdk():
    """Import only the specified package; verify the actually loaded .so path."""
    if "Robotic_Arm" in sys.modules:
        raise RuntimeError("SDK_ALREADY_IMPORTED_REFUSE_AMBIGUOUS_VERSION")
    spec = importlib.util.spec_from_file_location("Robotic_Arm", SDK_PACKAGE/"__init__.py",
                                                 submodule_search_locations=[str(SDK_PACKAGE)])
    package = importlib.util.module_from_spec(spec)
    sys.modules["Robotic_Arm"] = package
    spec.loader.exec_module(package)
    sdk = importlib.import_module("Robotic_Arm.rm_robot_interface")
    wrap = importlib.import_module("Robotic_Arm.rm_ctypes_wrap")
    actual = Path(wrap._libs[wrap.libname].access["cdecl"]._name).resolve()
    if Path(sdk.__file__).resolve() != SDK_SOURCE or actual != SDK_LIBRARY:
        raise RuntimeError("SDK_PATH_MISMATCH_NO_VERSION_FALLBACK")
    return sdk

def sdk_pose(values):
    # SDK fields already have m/rad units. Never run the raw JSON converter here.
    if not vector(values, 6):
        raise ValueError("SDK_POSE_SHAPE_OR_NONFINITE")
    return {"xyz_m": list(values[:3]), "rpy_rad": list(values[3:]),
            "units": {"xyz": "m", "rpy": "rad"}, "orientation_metadata": dict(RPY_METADATA),
            "unit_conversion": "identity; SDK already returns m/rad", "unit_scale_applied": 1}

def sdk_errors(raw):
    if not isinstance(raw, dict) or type(raw.get("err_len")) is not int:
        raise ValueError("SDK_ERROR_STRUCTURE")
    values = raw.get("err")
    if not isinstance(values, list) or raw["err_len"] != len(values) or raw["err_len"] < 0:
        raise ValueError("SDK_ERROR_LENGTH")
    codes = []
    for value in values:
        if type(value) is int and value >= 0:
            codes.append(value)
        elif isinstance(value, str) and value.isascii() and value.isdigit():
            codes.append(int(value))
        else:
            raise ValueError("SDK_ERROR_CODE_TYPE")
    return {"codes": codes, "has_error": any(code != 0 for code in codes), "raw": copy.deepcopy(raw)}

def canonical_state(arm, sample, dof=6, connection=None):
    """Normalize only successful SDK returns; raw returns remain in the sample."""
    labels = ("work_before", "tool_before", "state", "work_after", "tool_after")
    if any(type(sample["calls"].get(k, {}).get("return_code")) is not int or
           sample["calls"][k]["return_code"] != 0 for k in labels):
        raise ValueError("SDK_READ_FAILED_NO_CANONICAL_DEFAULTS")
    work = sample["calls"]["work_before"]["raw_return"][1]
    tool = sample["calls"]["tool_before"]["raw_return"][1]
    state = sample["calls"]["state"]["raw_return"][1]
    joints = state.get("joint")
    if not vector(joints, dof):
        raise ValueError("SDK_JOINT_SHAPE_OR_NONFINITE")
    def frame(raw, kind):
        if not isinstance(raw.get("name"), str) or not raw["name"]:
            raise ValueError("SDK_FRAME_NAME")
        fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {"id": "realman:%s:%s:%s" % (arm, kind, raw["name"]),
                "name": raw["name"], "pose": sdk_pose(raw["pose"]),
                "definition_fingerprint": fingerprint, "read_status": "VERIFIED",
                "relative_to": "controller_base" if kind == "work" else "controller_flange",
                "definition_status": "DOCUMENTED", "physical_grasp_calibration": "UNCONFIRMED"}
    ee = sdk_pose(state["pose"])
    ee.update(reference_frame=None, target_frame=None, reference_frame_id=None, target_frame_id=None,
              active_work_frame_id="realman:%s:work:%s" % (arm, work["name"]),
              active_tool_frame_id="realman:%s:tool:%s" % (arm, tool["name"]),
              frame_semantics_status="UNKNOWN",
              reported_active_work_frame=work["name"], reported_active_tool_frame=tool["name"],
              evidence=FRAME_EVIDENCE,
              note="Local current-state definition does not specify reference/target frames. Do not bind by name or zero offsets.")
    stable = (work == sample["calls"]["work_after"]["raw_return"][1] and
              tool == sample["calls"]["tool_after"]["raw_return"][1])
    return {"schema_version": "astra.realman.canonical_state.v1", "arm": arm,
            "joint_deg": list(joints), "ee_pose": ee,
            "connection": copy.deepcopy(connection),
            "raw_sdk_state": copy.deepcopy(state),
            "raw_work_frame": copy.deepcopy(work), "raw_tool_frame": copy.deepcopy(tool),
            "work_frame": frame(work, "work"), "tool_frame": frame(tool, "tool"),
            "system_error": sdk_errors(state["err"]),
            "timestamp": sample["calls"]["state"]["finished_at"],
            "frame_snapshot_stable": stable, "snapshot_atomic": False,
            "source": {"kind": "realman_api2_sdk", "python": str(SDK_SOURCE),
                       "library": str(SDK_LIBRARY), "joint_unit": "deg",
                       "normalization": "identity; no /1000 or /1e6 on SDK values",
                       "expected_dof": dof},
            "execution_permitted": False}

class SDKReadOnly:
    """A process-local session. Public methods expose only connect/read/close."""
    def __init__(self, run, sdk=None):
        self.run = Path(run)
        self.sdk = sdk
        self.connected = {}
        self.connection_info = {}
        self.events = []
        self.initialized = False
        self.sequence = 0

    def _call(self, name, function, *args, arm=None, pointer=False, arguments=None):
        if name not in ALLOWED:
            raise ValueError("SDK_CALL_NOT_ALLOWED")
        self.sequence += 1
        stem = "%03d-%s-%s" % (self.sequence, arm or "session", name)
        code = getattr(function, "__code__", None)
        event = {"function": name, "arm": arm, "started_at": time.time(),
                 "arguments": arguments,
                 "call_site": {"file": __file__, "function": "_call", "caller_line": inspect.currentframe().f_back.f_lineno},
                 "sdk_python_location": {"file": code.co_filename, "line": code.co_firstlineno} if code else
                                        {"file": str(SDK_PACKAGE/"rm_ctypes_wrap.py"), "symbol": name}}
        write_json(self.run/(stem+"-start.json"), event)
        try:
            raw = function(*args)
            if pointer:
                event.update(raw_return={"is_null": not bool(raw),
                                        "handle_id": raw.contents.id if raw else None},
                             return_code=None)
            elif name in READS:
                event.update(raw_return=copy.deepcopy(raw), return_code=raw[0])
            else:
                event.update(raw_return=raw, return_code=raw)
            event["finished_at"] = time.time()
            self.events.append(event)
            write_json(self.run/(stem+"-result.json"), event)
            return raw, event
        except Exception as exc:
            event.update(finished_at=time.time(), exception_type=type(exc).__name__,
                         exception=str(exc), traceback=traceback.format_exc(), return_code=None)
            self.events.append(event)
            write_json(self.run/(stem+"-exception.json"), event)
            raise

    def __enter__(self):
        if self.sdk is None:
            self.sdk = load_sdk()
        ret, event = self._call("rm_init", self.sdk.rm_init,
                                int(self.sdk.rm_thread_mode_e.RM_DUAL_MODE_E),
                                arguments={"mode": "RM_DUAL_MODE_E"})
        if ret != 0:
            self._call("rm_destroy", self.sdk.rm_destroy)
            raise RuntimeError("SDK_INIT_FAILED:%s" % ret)
        self.initialized = True
        return self

    def connect(self, arm, host, port, dof=6):
        if arm not in ("left", "right") or arm in self.connected or dof != 6:
            raise ValueError("INVALID_OR_DUPLICATE_ARM")
        if not self.initialized:
            raise RuntimeError("SDK_NOT_INITIALIZED")
        handle, event = self._call("rm_create_robot_arm", self.sdk.rm_create_robot_arm,
                                  host, port, arm=arm, pointer=True,
                                  arguments={"ip": host, "port": port})
        if not handle or handle.contents.id == -1:
            return {"connected": False, "event": event}
        # RoboticArm(mode=None) is an inert Python container. Avoid the high-level
        # create helper, which would add log-configuration and robot-info calls.
        robot = self.sdk.RoboticArm()
        robot.handle = handle
        robot.arm_dof = dof  # Both trusted rm_*_arm.yaml files specify arm_axis: 6.
        self.connected[arm] = robot
        self.connection_info[arm] = {
            "arm": arm, "ip": host, "port": port, "controller_id": "realman:%s:%s" % (host, port),
            "sdk_handle_id": handle.contents.id, "handle_scope": "this SDK process only; not a hardware serial number",
            "connection_verified": True, "source": event}
        return {"connected": True, "handle_id": handle.contents.id, "event": event}

    def snapshot(self, arm):
        robot = self.connected[arm]
        calls = {}
        for label, name in (("work_before", "rm_get_current_work_frame"),
                            ("tool_before", "rm_get_current_tool_frame"),
                            ("state", "rm_get_current_arm_state"),
                            ("work_after", "rm_get_current_work_frame"),
                            ("tool_after", "rm_get_current_tool_frame")):
            try:
                _, calls[label] = self._call(name, getattr(robot, name), arm=arm)
            except Exception:
                calls[label] = self.events[-1]
        result = {"arm": arm, "calls": calls, "canonical": None}
        try:
            result["canonical"] = canonical_state(arm, result, robot.arm_dof, self.connection_info.get(arm))
        except Exception as exc:
            result["canonical_error"] = {"type": type(exc).__name__, "message": str(exc)}
        return result

    def __exit__(self, *args):
        # These handles and the SDK runtime belong only to this diagnostic process.
        try:
            for arm, robot in self.connected.items():
                try:
                    self._call("rm_delete_robot_arm", self.sdk.rm_delete_robot_arm, robot.handle, arm=arm)
                except Exception:
                    pass  # exact failure retained; continue cleanup of other handles
        finally:
            if self.initialized:
                try:
                    self._call("rm_destroy", self.sdk.rm_destroy)
                finally:
                    self.initialized = False
