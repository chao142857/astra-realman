"""One normal pick-task observation to one supervised proposal; no actuation APIs."""
import copy
import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path
from io_utils import ROOT, output_path, strict_json, vector, write_json
from decision_backends import (DecisionBackend, BackendResult, BackendFailure, build_context,
                              codex_command, check_events, redact)
from model_step_review import FRAME_FINGERPRINTS

TASK = "Use the left arm to pick up the tennis ball."
SCHEMA = ROOT/"schema/pick_action.schema.json"
MAX_TRANSLATION_M = .003
MAX_ROTATION_RAD = math.pi/180
KEYS = {"action_type","arm","frame","tool_frame","translation_m","rotation_rpy_rad","gripper","done"}

def parse_pick(raw, *, translation_limit_m=MAX_TRANSLATION_M, rotation_limit_rad=MAX_ROTATION_RAD, translation_norm_limit_m=None):
    if not ((translation_limit_m is None and rotation_limit_rad is None) or
                (type(translation_limit_m) in (int,float) and type(rotation_limit_rad) in (int,float) and
                 0 < translation_limit_m <= .05 and 0 < rotation_limit_rad <= math.radians(5))):
        raise ValueError("INVALID_HARD_LIMITS")
    a = strict_json(raw)
    errors = []
    if not isinstance(a,dict) or set(a)!=KEYS:
        raise ValueError("ACTION_SCHEMA_FIELDS")
    if a["action_type"]!="cartesian_delta" or a["arm"]!="left":
        errors.append("LEFT_CARTESIAN_ACTION_REQUIRED")
    if a["frame"]!="realman:left:work:World" or a["tool_frame"]!="realman:left:tool:Arm_Tip":
        errors.append("FRAME_MISMATCH")
    if not vector(a["translation_m"],3) or (translation_limit_m is not None and any(abs(x)>translation_limit_m for x in a["translation_m"])):
        errors.append("TRANSLATION_LIMIT")
    if translation_norm_limit_m is not None:
        if not (type(translation_norm_limit_m) in (int,float) and 0 < translation_norm_limit_m <= .05):
            errors.append("INVALID_TRANSLATION_NORM_LIMIT")
        elif vector(a["translation_m"],3) and math.sqrt(sum(v*v for v in a["translation_m"]))>translation_norm_limit_m+1e-12:
            errors.append("TRANSLATION_NORM_LIMIT")
    if not vector(a["rotation_rpy_rad"],3) or (rotation_limit_rad is not None and any(abs(x)>rotation_limit_rad for x in a["rotation_rpy_rad"])):
        errors.append("ROTATION_LIMIT")
    normalized_gripper=(translation_limit_m is None and type(a["gripper"]) in (int,float) and math.isfinite(a["gripper"]) and 0<=a["gripper"]<=1)
    if (a["gripper"] not in ("open","close","hold") and not normalized_gripper) or type(a["done"]) is not bool:
        errors.append("GRIPPER_OR_DONE")
    if not errors:
        motion=any(a["translation_m"]+a["rotation_rpy_rad"])
        if a["done"] and (motion or a["gripper"]!="hold"):
            errors.append("DONE_WITH_ACTUATION")
    if errors:
        raise ValueError(",".join(errors))
    return a

def pose_preview(current, action):
    # User-specified componentwise delta semantics; do not wrap, clamp or compose rotations.
    xyz=[p+d for p,d in zip(current["xyz_m"],action["translation_m"])]
    rpy=[p+d for p,d in zip(current["rpy_rad"],action["rotation_rpy_rad"])]
    if not vector(xyz,3) or not vector(rpy,3):raise ValueError("TARGET_POSE_NONFINITE")
    return {"xyz_m":xyz,"rpy_rad":rpy,"frame":action["frame"],"tool_frame":action["tool_frame"]}

def review_pick(action, observation, *, translation_limit_m=MAX_TRANSLATION_M, rotation_limit_rad=MAX_ROTATION_RAD, translation_norm_limit_m=None):
    errors=[]
    try:
        parse_pick(json.dumps(action,allow_nan=False), translation_limit_m=translation_limit_m, rotation_limit_rad=rotation_limit_rad, translation_norm_limit_m=translation_norm_limit_m)
    except (ValueError,TypeError) as exc:
        errors.append(str(exc))
    states=observation.get("canonical_states",{})
    for arm in ("left","right"):
        s=states.get(arm,{})
        error=s.get("system_error",{})
        raw=s.get("raw_sdk_state",{})
        codes=error.get("codes")
        raw_error=raw.get("err",{})
        if (not isinstance(codes,list) or not codes or any(type(x)is not int or x!=0 for x in codes)
            or error.get("has_error") is not False or error.get("raw")!=raw_error
            or raw_error.get("err_len")!=len(codes)
            or raw_error.get("err") not in ([0]*len(codes),["0"]*len(codes))):
            errors.append(arm.upper()+"_ERROR_OR_UNKNOWN")
        ee=s.get("ee_pose",{})
        if (not vector(s.get("joint_deg"),6) or not vector(ee.get("xyz_m"),3) or
            not vector(ee.get("rpy_rad"),3) or ee.get("units")!={"xyz":"m","rpy":"rad"} or
            ee.get("unit_scale_applied")!=1 or raw.get("joint")!=s.get("joint_deg") or
            raw.get("pose")!=ee.get("xyz_m",[])+ee.get("rpy_rad",[])):
            errors.append(arm.upper()+"_STATE_INVALID")
    left=states.get("left",{})
    if left.get("connection",{}).get("ip")!="192.168.1.19" or left.get("frame_snapshot_stable") is not True:
        errors.append("LEFT_CONNECTION_OR_FRAME")
    for key,expected in FRAME_FINGERPRINTS.items():
        frame=left.get(key,{})
        raw=left.get("raw_"+key,{})
        actual=hashlib.sha256(json.dumps(raw,sort_keys=True,allow_nan=False).encode()).hexdigest()
        if frame.get("definition_fingerprint")!=expected or actual!=expected:
            errors.append(key.upper()+"_CHANGED")
    if observation.get("capture_failures") or len(observation.get("cameras",[]))!=4:
        errors.append("OBSERVATION_FAILED")
    current=copy.deepcopy(left.get("ee_pose",{}))
    target=None
    if not errors:
        try:
            target=pose_preview(current,action)
        except ValueError as exc:
            errors.append(str(exc))
    actuation=bool(not errors and (any(action["translation_m"]+action["rotation_rpy_rad"]) or action["gripper"]!="hold"))
    return {"status":"REJECT" if errors else ("AWAITING_EXECUTE" if actuation else "PASS_NOOP"),
            "errors":errors,"action":action,
            "current_pose":{"xyz_m":current.get("xyz_m"),"rpy_rad":current.get("rpy_rad")},
            "target_pose":target,"actuation_requested":actuation,
            "numeric_limits":{"translation_axis_m":translation_limit_m,"rotation_axis_rad":rotation_limit_rad,"translation_norm_m":translation_norm_limit_m},
            "local_workspace":{"status":"PENDING_REVIEW_OF_THIS_EXACT_ACTION" if actuation else "NOT_APPLICABLE",
                               "note":"Prior cleared segment preserved; no enlarged geometric bounds fabricated.",
                               "known_motion_evidence":"logs/supervised-step-20261002T203531-b1cddd33"},
            "required_before_execution":["literal EXECUTE for this exact proposal",
                                         "fresh state/error/frame/teach-mode validation",
                                         "same local segment and endpoint clearance",
                                         "single-command SDK mapping, no automatic retries"],
            "execution_permitted":False,"motion_commands_sent":0}

class PickBackend(DecisionBackend):
    def __init__(self, config, model="gpt-6-astra", *, translation_limit_m=MAX_TRANSLATION_M,
                 rotation_limit_rad=MAX_ROTATION_RAD, schema=SCHEMA, automatic=False, translation_norm_limit_m=None):
        if not ((translation_limit_m is None and rotation_limit_rad is None) or
                (type(translation_limit_m) in (int,float) and type(rotation_limit_rad) in (int,float) and
                 0 < translation_limit_m <= .05 and 0 < rotation_limit_rad <= math.radians(5))):
            raise ValueError("INVALID_HARD_LIMITS")
        self.config,self.model=config,model
        self.translation_limit_m,self.rotation_limit_rad=translation_limit_m,rotation_limit_rad
        self.schema,self.automatic=Path(schema),automatic
        self.translation_norm_limit_m=translation_norm_limit_m

    def decide(self, observation, run):
        checked=build_context(observation) # Reuse four-file/serial/hash checks only.
        run=output_path(run)
        (run/"input_only").mkdir()
        (run/"runtime").mkdir()
        states={}
        for arm,s in observation["canonical_states"].items():
            states[arm]={"arm":arm,"joint_deg":s["joint_deg"],
                "ee_pose":{"xyz_m":s["ee_pose"]["xyz_m"],"rpy_rad":s["ee_pose"]["rpy_rad"],
                           "units":{"xyz":"m","rpy":"rad"}},
                "system_error":s["system_error"],"timestamp":s["timestamp"]}
        for arm,s in observation["canonical_states"].items():
            if "gripper_state" in s:
                states[arm]["gripper_state"]=s["gripper_state"]
        def frame(f):
            return {"id":f["id"],"name":f["name"],
                    "pose":{"xyz_m":f["pose"]["xyz_m"],"rpy_rad":f["pose"]["rpy_rad"]}}
        context={"task":TASK,"observation_id":observation["observation_id"],
                 "images_in_attachment_order":[{k:image.get(k) for k in
                     ("input_index","serial","role","role_confirmed","captured_at","image_path")}
                     for image in checked["images_in_attachment_order"]],
                 "robot_states":states,
                 "work_frames":{a:frame(s["work_frame"]) for a,s in observation["canonical_states"].items()},
                 "tool_frames":{a:frame(s["tool_frame"]) for a,s in observation["canonical_states"].items()},
                 "previous":observation.get("previous")}
        prompt=json.dumps(context,ensure_ascii=False,allow_nan=False)
        write_json(run/"input_context.json",context)
        (run/"prompt.txt").write_text(prompt)
        command=codex_command(self.config["executable"],self.model,checked["images_in_attachment_order"],
                              run,self.config["provider"],schema=self.schema)
        write_json(run/"command.json",command)
        env={k:v for k,v in os.environ.items() if k in
             ("HOME","USER","LOGNAME","LANG","LC_ALL","SSL_CERT_FILE","SSL_CERT_DIR")}
        env.update(PATH="/usr/bin:/bin",TMPDIR=str(run/"runtime"))
        meta={"backend":"PickBackend/CodexCLI","model":self.model,"started_at":time.time(),
              "image_count":4,"sandbox":"read-only","ephemeral":True,"execution_permitted":False,
              "schema_sha256":hashlib.sha256(self.schema.read_bytes()).hexdigest()}
        start=time.monotonic()
        try:
            proc=subprocess.run(command,input=prompt,text=True,capture_output=True,
                timeout=self.config["timeout_s"],cwd=str(run/"input_only"),env=env)
            meta["return_code"]=proc.returncode
            (run/"events.jsonl").write_text(redact(proc.stdout))
            (run/"stderr.log").write_text(redact(proc.stderr))
            if proc.returncode!=0:
                raise BackendFailure("CODEX_EXIT_NONZERO")
            final=check_events(proc.stdout)
            output=run/"last_message.json"
            if not output.is_file() or output.stat().st_size>65536:
                raise BackendFailure("OUTPUT_FILE_MISSING_OR_OVERSIZE")
            raw=output.read_text()
            if raw.strip()!=final.strip():
                raise BackendFailure("FINAL_OUTPUT_MISMATCH")
            proposal=parse_pick(raw, translation_limit_m=self.translation_limit_m, rotation_limit_rad=self.rotation_limit_rad, translation_norm_limit_m=self.translation_norm_limit_m)
            return BackendResult(proposal,meta)
        except Exception as exc:
            meta["error"]=str(exc)
            raise
        finally:
            meta.update(finished_at=time.time(),inference_latency_s=time.monotonic()-start)
            write_json(run/"backend_result.json",meta)
