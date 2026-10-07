"""Wrapper of the laboratory's unchanged RmArm gripper implementation."""
import importlib.util
import json
import math
from pathlib import Path

SOURCE=Path("/home/tongji/aloha/RealMan_Control/realman_arm.py")
CONFIG=Path("/home/tongji/aloha/RealMan_Control/config/rm_left_arm.yaml")

class _ObservedSocket:
    """Observe the original send/recv without generating or replacing protocol."""
    def __init__(self, original):
        self.original=original
        self.record=None
        self.target=None

    def send(self, data):
        if self.record is None or self.record["send_attempts"]:
            raise RuntimeError("ONE_GRIPPER_SEND_ONLY")
        decoded=json.loads(data.decode("utf-8"))
        if decoded!={"command":"hand_follow_pos","hand_pos":[self.target]}:
            raise RuntimeError("ORIGINAL_DRIVER_COMMAND_MISMATCH")
        self.record["wire_command"]=data.decode("utf-8")
        self.record["send_attempts"]=1
        count=self.original.send(data)
        self.record["bytes_sent"]=count
        if count!=len(data):
            raise RuntimeError("PARTIAL_SEND_NO_RETRY")
        return count

    def recv(self, size):
        data=self.original.recv(size)
        self.record["wire_reply_hex"]=data.hex()
        self.record["wire_reply_text"]=data.decode("utf-8",errors="replace")
        return data

    def close(self):
        self.original.close()

class LabGripperAdapter:
    def __init__(self, arm_id="left", config_path=None):
        if arm_id not in ("left","right"):raise ValueError("ARM_ID")
        self.arm_id=arm_id
        self.config=Path(config_path) if config_path is not None else (CONFIG if arm_id=="left" else CONFIG.with_name("rm_right_arm.yaml"))
        spec=importlib.util.spec_from_file_location("lab_existing_realman_arm",SOURCE)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.driver=module.RmArm(str(self.config))
        if self.driver.arm_ip!={"left":"192.168.1.19","right":"192.168.1.18"}[arm_id] or self.driver.arm_port!=8080:
            self.driver.arm.close()
            raise RuntimeError(arm_id.upper()+"_ENDPOINT_MISMATCH")
        self.transport=_ObservedSocket(self.driver.arm)
        self.driver.arm=self.transport
        self.consumed=False
        self.last_result=None

    def set_gripper(self, arm, mode):
        numeric=type(mode) in (int,float) and math.isfinite(mode) and 0<=mode<=1
        if arm!=getattr(self,"arm_id","left") or (mode not in ("open","close") and not numeric):
            raise ValueError("ARM_MISMATCH_OR_INVALID_OPENING")
        if self.consumed:
            raise RuntimeError("SINGLE_ATTEMPT_ADAPTER_ALREADY_CONSUMED")
        self.consumed=True
        requested=float(mode) if numeric else {"open":1.0,"close":0.0}[mode]
        target=int(requested*1000)  # Original driver wire resolution; never feed this back into the request.
        result={"arm":arm,"mode":mode,"target":target,"existing_source":str(SOURCE),
                "existing_config":str(getattr(self,"config",CONFIG)),"existing_function":"RmArm.set_gripper_position",
                "existing_argument":requested,"function_return":None,
                "send_attempts":0,"arm_motion_commands":0}
        self.last_result=result
        self.transport.record=result
        self.transport.target=target
        try:
            # The existing function multiplies by 1000, builds the JSON, and sends/receives once.
            result["function_return"]=self.driver.set_gripper_position(requested)
            text=result.get("wire_reply_text","")
            if not text:
                raise RuntimeError("EMPTY_ORIGINAL_DRIVER_REPLY")
            result["command_return"]=json.loads(text)
            if not isinstance(result["command_return"],dict):
                raise RuntimeError("INVALID_COMMAND_REPLY")
        except Exception as exc:
            result.update(exception_type=type(exc).__name__,exception=str(exc))
            raise
        return result

    def close(self):
        self.transport.close()
