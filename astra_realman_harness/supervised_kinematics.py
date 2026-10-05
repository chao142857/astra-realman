"""Offline, fail-closed verification of one fixed left World +Z 10 mm path.

No rm_init, connection, motion, controller setter, or algorithm parameter setter is
called. Run in a dedicated process: the pinned SDK algorithm initializer changes
only that process's algorithm state. This output alone never authorizes motion.
"""
import argparse
import copy
import ctypes
import hashlib
import json
import math
import time
import sys
import traceback
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))

from io_utils import output_path, read_json, write_json, vector
from realman_api2_readonly import load_sdk, SDK_LIBRARY, SDK_SOURCE

STEP_M = 0.01
SAMPLE_COUNT = 201
TOTAL_JOINT_DELTA_DEG = 5.0
SAMPLE_JOINT_DELTA_DEG = 0.05
START_XYZ_TOL_M = 0.0002
START_RPY_TOL_RAD = 0.002
FK_XYZ_TOL_M = 0.00005
FK_ORIENTATION_TOL_RAD = 0.0002
DH_TOL = {"d": 1e-7, "a": 1e-7, "alpha": 1e-5, "offset": 1e-5}
BINDING_KIND = "operator_ui_work_mode_and_documented_relative_position_step"
WORK_ID = "realman:left:work:World"
TOOL_ID = "realman:left:tool:Arm_Tip"
ALGORITHM_CALLS = frozenset((
    "rm_algo_init_sys_data_by_dh", "rm_algo_get_dh", "rm_algo_forward_kinematics",
    "rm_algo_inverse_kinematics", "rm_algo_safety_robot_self_collision_detection",
    "rm_algo_kin_robot_singularity_analyse",
))

def _require(ok, code):
    if not ok:
        raise ValueError(code)

def _zero(code):
    return type(code) is int and code == 0

def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def _pose(raw):
    p = {"xyz_m":[raw.position.x,raw.position.y,raw.position.z],
         "rpy_rad":[raw.euler.rx,raw.euler.ry,raw.euler.rz],
         "quaternion_wxyz":[raw.quaternion.w,raw.quaternion.x,
                           raw.quaternion.y,raw.quaternion.z]}
    _require(all(vector(p[key], n) for key,n in
                 (("xyz_m",3),("rpy_rad",3),("quaternion_wxyz",4))),"FK_NONFINITE_POSE")
    norm = math.sqrt(sum(x*x for x in p["quaternion_wxyz"]))
    _require(abs(norm-1) <= 1e-4,"FK_INVALID_QUATERNION_NORM")
    return p

def _distance(a,b):
    return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))

def _geodesic(a,b):
    denominator=math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
    _require(denominator>0,"QUATERNION_ZERO_NORM")
    return 2*math.acos(min(1.,max(0.,abs(sum(x*y for x,y in zip(a,b))/denominator))))

def _dh(raw):
    return {key:list(getattr(raw,key)) for key in ("d","a","alpha","offset")}

def _validated_input(data):
    _require(type(data.get("model_enum")) is int and data["model_enum"] == 0,
             "MODEL_MUST_BE_MEASURED_RM65")
    _require(type(data.get("force_type_enum")) is int and data["force_type_enum"] == 3,
             "FORCE_TYPE_MUST_BE_MEASURED_ISF")
    dh=data.get("controller_dh",{})
    _require(isinstance(dh,dict) and all(vector(dh.get(k),8) for k in DH_TOL),"CONTROLLER_DH_SHAPE")
    limits=data.get("joint_limits_deg")
    _require(isinstance(limits,list) and len(limits)==6 and
             all(vector(p,2) and p[0]<p[1] for p in limits),"JOINT_LIMITS_INVALID")
    for key in ("input_evidence","binding_evidence"):
        _require(isinstance(data.get(key),str) and bool(data[key].strip()),key.upper()+"_MISSING")
    state=data.get("canonical_left",{})
    _require(state.get("arm")=="left" and state.get("schema_version")==
             "astra.realman.canonical_state.v1","CANONICAL_LEFT_REQUIRED")
    q=state.get("joint_deg")
    ee=state.get("ee_pose",{})
    raw=state.get("raw_sdk_state",{})
    _require(vector(q,6) and vector(ee.get("xyz_m"),3) and vector(ee.get("rpy_rad"),3),
             "CANONICAL_STATE_SHAPE")
    _require(ee.get("units")=={"xyz":"m","rpy":"rad"} and
             type(ee.get("unit_scale_applied")) in (float,int) and ee["unit_scale_applied"]==1 and
             state.get("source",{}).get("joint_unit")=="deg" and
             state["source"].get("kind")=="realman_api2_sdk" and
             raw.get("joint")==q and raw.get("pose")==ee["xyz_m"]+ee["rpy_rad"],
             "CANONICAL_UNITS_OR_RAW_MISMATCH")
    _require(state.get("frame_snapshot_stable") is True,"UNSTABLE_ACTIVE_FRAMES")
    for kind,name,ident in (("work","World",WORK_ID),("tool","Arm_Tip",TOOL_ID)):
        frame=state.get(kind+"_frame",{})
        raw_frame=state.get("raw_"+kind+"_frame",{})
        _require(frame.get("id")==ident and frame.get("name")==name and
                 frame.get("read_status")=="VERIFIED" and raw_frame.get("name")==name and
                 vector(raw_frame.get("pose"),6) and all(x==0 for x in raw_frame["pose"]),
                 "OFFLINE_REQUIRES_RECORDED_ZERO_"+kind.upper()+"_FRAME")
    readbacks=data.get("readbacks",{})
    for name in ("rm_get_DH_data","rm_get_joint_min_pos","rm_get_joint_max_pos"):
        entry=readbacks.get(name,{})
        _require(_zero(entry.get("return_code")),"MEASURED_READBACK_FAILED:"+name)
    _require(readbacks["rm_get_DH_data"].get("value")==dh,"CONTROLLER_DH_READBACK_MISMATCH")
    _require(readbacks["rm_get_joint_min_pos"].get("value")==[x[0] for x in limits] and
             readbacks["rm_get_joint_max_pos"].get("value")==[x[1] for x in limits],
             "JOINT_LIMIT_READBACK_MISMATCH")
    _require(all(lo<=x<=hi for x,(lo,hi) in zip(q,limits)),"START_JOINT_OUT_OF_LIMIT")
    return state,dh,limits

def verify(input_dict,evidence_file,*,sdk=None):
    """Return {path, errors, raw_algorithm_calls}; save exact evidence exclusively.

    sdk injection exists only for offline mock tests. Production CLI loads the
    fixed local SDK. All pose semantics remain in canonical data; the separate
    binding evidence describes the operator-confirmed relative-step semantics.
    """
    evidence_file=output_path(evidence_file)
    _require(not evidence_file.exists(),"EVIDENCE_FILE_ALREADY_EXISTS")
    started=time.time()
    result={"schema_version":"realman.offline_kinematic_verification.v1",
            "source":"offline_kinematic_verifier","started_at":started,
            "outcome":"REJECT","errors":[],"path":None,"raw_algorithm_calls":[],
            "hardware_connections_opened":0,"motion_commands_sent":0,
            "execution_permitted":False,
            "scope":{"arm":"left","frame":WORK_ID,"tool_frame":TOOL_ID,
                     "translation_m":[0,0,STEP_M],"rotation_rpy_rad":[0,0,0],"gripper":"hold"},
            "thresholds":{"sample_count":SAMPLE_COUNT,"total_joint_delta_deg":TOTAL_JOINT_DELTA_DEG,
                          "per_sample_joint_delta_deg":SAMPLE_JOINT_DELTA_DEG,
                          "start_xyz_m":START_XYZ_TOL_M,"start_rpy_rad":START_RPY_TOL_RAD,
                          "sample_fk_xyz_m":FK_XYZ_TOL_M,
                          "sample_fk_orientation_rad":FK_ORIENTATION_TOL_RAD,"dh":DH_TOL},
            "limits_of_claim":["Sampled kinematic checks and native SDK collision return codes, not continuous collision proof.",
                               "Native DH-only algorithm geometry coverage is UNKNOWN; physical segment clearance comes from the onsite operator.",
                               "No environment, gripper, cable, or opposite-arm collision model is fabricated.",
                               "Execution requires separate operator clearance, fresh state and guarded executor."]}
    path={"source":"offline_kinematic_verifier","evidence_file":str(evidence_file),
          "binding_kind":BINDING_KIND,"binding_evidence":input_dict.get("binding_evidence"),
          "collision_geometry_coverage":"UNKNOWN; generic DH SDK collision model is not proof of complete 6FB geometry",
          "kinematics_passed":False,"kinematics_evidence":str(evidence_file),
          "orientation_preserved":False,"orientation_evidence":str(evidence_file),
          "native_self_collision_checks_passed":False,"self_collision_evidence":str(evidence_file)}
    result["path"]=path
    try:
        state,measured_dh,limits=_validated_input(input_dict)
        q_start=list(state["joint_deg"])
        ee=state["ee_pose"]
        start_pose={"xyz_m":list(ee["xyz_m"]),"rpy_rad":list(ee["rpy_rad"])}
        target_pose=copy.deepcopy(start_pose)
        target_pose["xyz_m"][2]+=STEP_M
        path.update(start_joint_deg=q_start,start_pose=start_pose,target_pose=target_pose,
                    sampled_joint_deg=[],joint_limits_deg=copy.deepcopy(limits),
                    work_frame_id=WORK_ID,tool_frame_id=TOOL_ID,input_evidence=input_dict["input_evidence"])
        result["input_sha256"]=_hash(input_dict)
        result["input"]=copy.deepcopy(input_dict)
        result["sdk"]={"source":str(SDK_SOURCE),"library":str(SDK_LIBRARY),
                       "algorithm_input_units":{"joint":"deg","xyz":"m","rpy":"rad"}}
        if sdk is None:
            result["sdk"]["library_sha256"]=hashlib.sha256(SDK_LIBRARY.read_bytes()).hexdigest()
            sdk=load_sdk()
        def call(name,*args,arguments=None,serialize=lambda value:value):
            _require(name in ALGORITHM_CALLS,"ALGORITHM_NOT_ALLOWED")
            event={"function":name,"arguments":arguments,"started_at":time.time()}
            result["raw_algorithm_calls"].append(event)
            try:
                raw=getattr(sdk,name)(*args)
                event.update(finished_at=time.time(),raw_return=serialize(raw))
                return raw
            except Exception as exc:
                event.update(finished_at=time.time(),exception_type=type(exc).__name__,exception=str(exc))
                raise
        result["initialization_source"]="measured_controller_DH"
        result["sdk"]["algorithm_initialization"]={
            "source":"measured_controller_DH","force_type_enum":3,"dof":6,
            "controller_readback":input_dict["input_evidence"],
            "parameter_fitting_performed":False,"controller_configuration_changed":False}
        dh_struct=sdk.rm_dh_t(**copy.deepcopy(measured_dh))
        call("rm_algo_init_sys_data_by_dh",3,dh_struct,6,
             arguments={"force_type_enum":3,"dh_all8":copy.deepcopy(measured_dh),"dof":6})
        actual_dh=call("rm_algo_get_dh",serialize=_dh)
        algorithm_dh=_dh(actual_dh)
        result["dh_comparison"]={"algorithm_all8":algorithm_dh,"controller_all8":copy.deepcopy(measured_dh),
            "active_dof":6,"absolute_differences":{k:[abs(a-b) for a,b in
                zip(algorithm_dh[k][:6],measured_dh[k][:6])] for k in DH_TOL}}
        _require(all(vector(algorithm_dh.get(k),8) for k in DH_TOL),"ALGORITHM_DH_INVALID")
        _require(all(x<=DH_TOL[k] for k in DH_TOL for x in
                     result["dh_comparison"]["absolute_differences"][k]),"ALGORITHM_CONTROLLER_DH_MISMATCH")
        def fk(q):
            array=(ctypes.c_float*7)(*q)
            raw=call("rm_algo_forward_kinematics",None,array,arguments={"handle":None,"joint_deg":list(q)},
                     serialize=lambda p:{"xyz_m":[p.position.x,p.position.y,p.position.z],
                       "rpy_rad":[p.euler.rx,p.euler.ry,p.euler.rz],
                       "quaternion_wxyz":[p.quaternion.w,p.quaternion.x,p.quaternion.y,p.quaternion.z]})
            return _pose(raw)
        start_fk=fk(q_start)
        rpy_error=[abs(math.atan2(math.sin(a-b),math.cos(a-b)))
                   for a,b in zip(start_fk["rpy_rad"],ee["rpy_rad"])]
        result["initial_fk"]={"pose":start_fk,"xyz_error_m":_distance(start_fk["xyz_m"],ee["xyz_m"]),
                              "rpy_error_rad":rpy_error}
        _require(result["initial_fk"]["xyz_error_m"]<=START_XYZ_TOL_M,"START_FK_POSITION_MISMATCH")
        _require(max(rpy_error)<=START_RPY_TOL_RAD,"START_FK_ORIENTATION_MISMATCH")
        quaternion=list(start_fk["quaternion_wxyz"])
        result["algorithm_target_pose"]={"xyz_m":list(start_fk["xyz_m"]),
                                         "quaternion_wxyz":quaternion}
        result["algorithm_target_pose"]["xyz_m"][2]+=STEP_M
        samples=[]
        previous=list(q_start)
        for index in range(SAMPLE_COUNT):
            desired=list(start_fk["xyz_m"])
            desired[2]+=STEP_M*index/(SAMPLE_COUNT-1)
            if index==0:
                q=list(q_start)
            else:
                params=sdk.rm_inverse_kinematics_params_t(previous,desired+quaternion,0)
                q_out=(ctypes.c_float*7)()
                ret=call("rm_algo_inverse_kinematics",None,params,q_out,
                         arguments={"handle":None,"q_in_deg":list(previous),"xyz_m":desired,
                                    "quaternion_wxyz":quaternion,"flag":0,"sample_index":index},
                         serialize=lambda rc:{"return_code":rc,"q_out_all7_deg":list(q_out)})
                _require(_zero(ret),"IK_FAILED_AT_SAMPLE:"+str(index))
                q=list(q_out)[:6]
            _require(vector(q,6),"NONFINITE_IK_AT_SAMPLE:"+str(index))
            _require(all(lo<=x<=hi for x,(lo,hi) in zip(q,limits)),
                     "ACTUAL_JOINT_LIMIT_AT_SAMPLE:"+str(index))
            _require(max(abs(a-b) for a,b in zip(q,q_start))<=TOTAL_JOINT_DELTA_DEG,
                     "TOTAL_JOINT_DELTA_AT_SAMPLE:"+str(index))
            _require(max(abs(a-b) for a,b in zip(q,previous))<=SAMPLE_JOINT_DELTA_DEG,
                     "JOINT_DISCONTINUITY_AT_SAMPLE:"+str(index))
            measured_fk=start_fk if index==0 else fk(q)
            pos_error=_distance(measured_fk["xyz_m"],desired)
            orientation_error=_geodesic(measured_fk["quaternion_wxyz"],quaternion)
            array=(ctypes.c_float*7)(*q)
            collision=call("rm_algo_safety_robot_self_collision_detection",array,
                           arguments={"sample_index":index,"joint_deg":q})
            distance=ctypes.c_float()
            singularity=call("rm_algo_kin_robot_singularity_analyse",array,ctypes.byref(distance),
                            arguments={"sample_index":index,"joint_deg":q},
                            serialize=lambda rc:{"return_code":rc,"shoulder_distance_m":distance.value})
            samples.append({"index":index,"desired_xyz_m":desired,"joint_deg":q,"fk":measured_fk,
                            "xyz_error_m":pos_error,"orientation_error_rad":orientation_error,
                            "self_collision_return":collision,"singularity_return":singularity,
                            "shoulder_distance_m":distance.value})
            result["samples"]=samples
            _require(pos_error<=FK_XYZ_TOL_M,"FK_RESIDUAL_AT_SAMPLE:"+str(index))
            _require(orientation_error<=FK_ORIENTATION_TOL_RAD,"ORIENTATION_RESIDUAL_AT_SAMPLE:"+str(index))
            _require(_zero(collision),"SELF_COLLISION_AT_SAMPLE:"+str(index))
            _require(_zero(singularity),"SINGULARITY_AT_SAMPLE:"+str(index))
            path["sampled_joint_deg"].append(list(q))
            previous=list(q)
        path.update(kinematics_passed=True,orientation_preserved=True,native_self_collision_checks_passed=True)
        result["outcome"]="PASS_OFFLINE_KINEMATICS"
        result["metrics"]={"sample_count":len(samples),"max_fk_residual_m":max(s["xyz_error_m"] for s in samples),
            "max_orientation_residual_rad":max(s["orientation_error_rad"] for s in samples),
            "max_total_joint_delta_deg":max(abs(v-initial) for s in samples
                                           for v,initial in zip(s["joint_deg"],q_start)),
            "max_sample_joint_delta_deg":max(abs(a-b) for before,after in zip(samples,samples[1:])
                                             for a,b in zip(before["joint_deg"],after["joint_deg"]))}
    except Exception as exc:
        result["errors"].append(str(exc))
        result["exception_type"]=type(exc).__name__
        result["traceback"]=traceback.format_exc()
        path.update(kinematics_passed=False,orientation_preserved=False,native_self_collision_checks_passed=False)
    result["finished_at"]=time.time()
    result["latency_s"]=result["finished_at"]-started
    write_json(evidence_file,result)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--binding-evidence")
    args=parser.parse_args()
    data=read_json(args.input)
    # Accept this session's earlier measurement export without altering that file.
    if "force_type_enum" not in data and "force_enum" in data:
        data["force_type_enum"]=data["force_enum"]
    if "controller_dh" not in data and "dh" in data:
        data["controller_dh"]=data["dh"]
    data.setdefault("input_evidence",str(Path(args.input).resolve()))
    if args.binding_evidence:
        data["binding_evidence"]=args.binding_evidence
    result=verify(data,args.output)
    print(json.dumps({key:result.get(key) for key in
        ("outcome","errors","metrics","latency_s","motion_commands_sent","hardware_connections_opened")},
        ensure_ascii=False))
    return 0 if result["outcome"]=="PASS_OFFLINE_KINEMATICS" else 2

if __name__=="__main__":
    raise SystemExit(main())
