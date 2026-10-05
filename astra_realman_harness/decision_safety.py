"""Independent gate-by-gate safety. Classification never authorizes this shadow executor."""
from io_utils import number, vector
from decision_protocol import validate_action
from decision_frame_adapter import current_frame_ids, local_translation_preview, TRANSFORM_CONTRACT

OUTCOMES = ("PASS_NOOP", "PASS_EXECUTABLE", "REJECT")

def rejected(errors):
    return {"decision": "REJECT", "outcome": "REJECT", "errors": list(dict.fromkeys(errors)),
            "warnings": [], "gates": [{"gate": "backend_or_schema", "status": "FAIL",
                "blocking": True, "details": list(errors)}], "action_schema_valid": False,
            "execution_permitted": False, "hardware_commands_sent": 0, "motion_commands_sent": 0,
            "execution_backend": "DryRunExecutor"}

def check_phase_policy(policy):
    if not isinstance(policy, dict) or policy.get("schema_version") != "astra.shadow_safety.v2":
        raise ValueError("PHASE1_POLICY_VERSION_REQUIRED")
    if policy.get("mode") != "dry_run_only" or policy.get("max_translation_axis_m") != .002:
        raise ValueError("PHASE1_MODE_OR_LIMIT")
    if type(policy.get("fixture_only")) is not bool:
        raise ValueError("FIXTURE_FLAG")
    if policy.get("allowed_arms") != ["left"]:
        raise ValueError("PHASE1_LEFT_ONLY")
    for key in ("max_observation_age_s","max_proposal_age_s","max_clock_skew_s","max_camera_skew_s"):
        if not number(policy.get(key)) or policy[key] <= 0:
            raise ValueError("INVALID_POLICY:"+key)
    for key in ("arm_identities","local_workspaces","full_gripper_geometry","camera_extrinsics"):
        if not isinstance(policy.get(key),dict):
            raise ValueError("INVALID_POLICY:"+key)
    return policy

def _verified(value):
    return isinstance(value, dict) and value.get("status") == "VERIFIED" and bool(value.get("evidence"))

def _assess_decision(action, observation, policy, now, generated_at=None, execution_readiness=None):
    if not number(now):
        return rejected(["EVALUATION_TIME_INVALID"])
    try:
        check_phase_policy(policy)
    except ValueError as exc:
        return rejected([str(exc)])
    schema_errors = validate_action(action)
    a = action if isinstance(action,dict) else {}
    obs = observation if isinstance(observation,dict) else {}
    delta = a.get("translation_m")
    is_noop = not schema_errors and all(v == 0 for v in delta)
    gates, errors, warnings = [], [], []

    def gate(name, ok, code, details=None, motion_only=False, unknown=False, warning=False):
        observed = "PASS" if ok else ("UNCONFIRMED" if unknown else "FAIL")
        if motion_only and is_noop:
            status, blocking = "NOT_APPLICABLE", False
            if not ok:
                warnings.append(code)
        elif not ok and warning:
            status, blocking = "WARNING", False
            warnings.append(code)
        else:
            status, blocking = observed, not ok
            if blocking:
                errors.append(code)
        gates.append({"gate":name,"status":status,"observed_status":observed,
                      "blocking":blocking,"code":None if ok else code,
                      "details":details,"required_for_actuation":motion_only})
        return ok

    gate("action_schema",not schema_errors,"ACTION_SCHEMA_REJECT",schema_errors)
    if schema_errors:
        errors.extend(schema_errors)
    arm = a.get("arm")
    gate("arm_scope",arm in policy["allowed_arms"],"ARM_NOT_ALLOWED",{"requested":arm,"allowed":policy["allowed_arms"]})
    gate("observation_schema",obs.get("schema_version")=="astra.decision.observation.v1",
         "DECISION_OBSERVATION_SCHEMA")
    gate("test_fixture_scope",not(policy["fixture_only"] and obs.get("source",{}).get("physical") is not False),
         "SYNTHETIC_POLICY_FORBIDDEN_FOR_REAL_OBSERVATION")
    states = obs.get("canonical_states",{})
    if not isinstance(states,dict): states={}
    gate("both_robot_states",set(states)=={"left","right"} and all(isinstance(s,dict) and s for s in states.values()),
         "BOTH_CANONICAL_STATES_REQUIRED")
    target = states.get(arm,{}) if isinstance(arm,str) else {}
    if not isinstance(target,dict): target={}
    work,tool = current_frame_ids(target)
    canonical_ids_ok = (target.get("arm")==arm and
                        work=="realman:%s:work:%s" % (arm, target.get("work_frame",{}).get("name")) and
                        tool=="realman:%s:tool:%s" % (arm, target.get("tool_frame",{}).get("name")))
    gate("explicit_work_tool_ids",bool(work and tool) and canonical_ids_ok and a.get("frame")==work and a.get("tool_frame")==tool,
         "ACTION_FRAME_OR_TOOL_MISMATCH",{"requested_work":a.get("frame"),"current_work":work,
                                        "requested_tool":a.get("tool_frame"),"current_tool":tool})
    gate("translation_step",vector(delta,3) and all(abs(v)<=.002 for v in delta),
         "TRANSLATION_AXIS_LIMIT",{"limit_per_axis_m":.002,"requested":delta})
    gate("rotation",vector(a.get("rotation_rpy_rad"),3) and all(v==0 for v in a["rotation_rpy_rad"]),
         "ROTATION_DISABLED")
    gate("gripper",a.get("gripper")=="hold","GRIPPER_DISABLED")

    for name in ("left","right"):
        state=states.get(name,{})
        if not isinstance(state,dict): state={}
        ee=state.get("ee_pose",{})
        if not isinstance(ee,dict): ee={}
        fault=state.get("system_error",{})
        if not isinstance(fault,dict): fault={}
        codes=fault.get("codes")
        healthy=(isinstance(codes,list) and all(type(c) is int and c>=0 for c in codes) and
                 type(fault.get("has_error")) is bool and not fault["has_error"] and
                 not any(codes))
        # Controller faults and unverified units retain the earlier fail-closed
        # requirement, including a NOOP; do not call PASS_NOOP "hardware healthy".
        gate(name+"_controller_health",healthy,"ARM_"+name+":CONTROLLER_ERROR_OR_UNKNOWN",{"reported":fault})
        units=(vector(state.get("joint_deg"),6) and vector(ee.get("xyz_m"),3) and vector(ee.get("rpy_rad"),3) and
               ee.get("units")=={"xyz":"m","rpy":"rad"} and number(ee.get("unit_scale_applied")) and
               ee.get("unit_scale_applied")==1 and
               state.get("source",{}).get("joint_unit")=="deg")
        gate(name+"_units",units,"ARM_"+name+":STATE_UNITS_UNCONFIRMED",unknown=True)
        gate(name+"_frame_snapshot",state.get("frame_snapshot_stable") is True,
             "ARM_"+name+":FRAME_SNAPSHOT_UNCONFIRMED",motion_only=True,unknown=True)
        stamp=state.get("timestamp")
        fresh=number(stamp) and -policy["max_clock_skew_s"]<=now-stamp<=policy["max_observation_age_s"]
        gate(name+"_state_freshness",fresh,"ARM_"+name+":STATE_STALE_OR_FUTURE",
             {"age_s":now-stamp if number(stamp) else None,"limit_s":policy["max_observation_age_s"]},motion_only=True)
    stamp=obs.get("captured_at")
    gate("observation_freshness",number(stamp) and -policy["max_clock_skew_s"]<=now-stamp<=policy["max_observation_age_s"],
         "STALE_OBSERVATION",{"age_s":now-stamp if number(stamp) else None,"limit_s":policy["max_observation_age_s"]},
         motion_only=True)
    created=generated_at
    gate("proposal_freshness",number(created) and -policy["max_clock_skew_s"]<=now-created<=policy["max_proposal_age_s"],
         "STALE_OR_FUTURE_PROPOSAL",motion_only=True)
    gate("proposal_observation_order",number(created) and number(stamp) and
         created>=stamp-policy["max_clock_skew_s"], "PROPOSAL_PREDATES_OBSERVATION",motion_only=True)

    cameras=obs.get("cameras",[])
    if not isinstance(cameras,list): cameras=[]
    metrics=obs.get("camera_capture",{})
    if not isinstance(metrics,dict): metrics={}
    actual=[c.get("serial") for c in cameras if isinstance(c,dict)]
    expected=metrics.get("expected_serials",[])
    gate("observation_integrity",len(actual)==4 and len(set(actual))==4 and
         isinstance(expected,list) and set(actual)==set(expected) and not obs.get("capture_failures"),
         "CAMERA_SET_OR_CAPTURE_FAILURE",{"serials":actual,"failures":obs.get("capture_failures")})
    ct=[c.get("captured_at") for c in cameras if isinstance(c,dict)]
    span=(max(ct)-min(ct))*1000 if len(ct)==4 and all(number(t) for t in ct) else None
    gate("camera_freshness",len(ct)==4 and all(number(t) and
         -policy["max_clock_skew_s"]<=now-t<=policy["max_observation_age_s"] for t in ct),
         "CAMERA_FRAME_STALE_OR_FUTURE",{"timestamps":ct,"limit_s":policy["max_observation_age_s"]},
         motion_only=True)
    reported=obs.get("capture_span_ms")
    gate("camera_timing",number(span) and number(reported) and abs(span-reported)<=.001 and
         span<=policy["max_camera_skew_s"]*1000 and metrics.get("timestamp_semantics_confirmed") is True,
         "CAMERA_TIMING_UNCONFIRMED_OR_SKEW",{"capture_span_ms":span,"reported_ms":reported})

    identity=policy["arm_identities"].get(arm,{}) if isinstance(arm,str) else {}
    connection=target.get("connection") or {}
    mapping_ok=(_verified(identity.get("software_endpoint_mapping")) and
                connection.get("connection_verified") is True and connection.get("arm")==arm and
                connection.get("ip")==identity.get("host") and connection.get("port")==identity.get("port") and
                type(connection.get("sdk_handle_id")) is int and connection["sdk_handle_id"]>=0)
    gate("controller_connection_mapping",mapping_ok,"CONTROLLER_CONNECTION_MAPPING_UNCONFIRMED",
         {"expected_ip":identity.get("host"),"observed_ip":connection.get("ip"),
          "sdk_handle_id":connection.get("sdk_handle_id"),"handle_scope":"process-local only",
          "evidence":identity.get("software_endpoint_mapping")},motion_only=True,unknown=True)
    gate("physical_arm_identity",mapping_ok and _verified(identity.get("physical_side_identity")),
         "PHYSICAL_ARM_IDENTITY_UNCONFIRMED",identity.get("physical_side_identity"),motion_only=True,unknown=True)
    wf=target.get("work_frame",{})
    tf=target.get("tool_frame",{})
    if not isinstance(wf,dict): wf={}
    if not isinstance(tf,dict): tf={}
    def definition_valid(frame):
        pose=frame.get("pose",{})
        return (frame.get("read_status")=="VERIFIED" and frame.get("definition_status")=="DOCUMENTED" and
                isinstance(frame.get("definition_fingerprint"),str) and len(frame["definition_fingerprint"])==64 and
                isinstance(pose,dict) and pose.get("units")=={"xyz":"m","rpy":"rad"} and
                vector(pose.get("xyz_m"),3) and vector(pose.get("rpy_rad"),3))
    gate("active_work_definition",definition_valid(wf),"ACTIVE_WORK_DEFINITION_UNCONFIRMED",
         {"id":work,"name":wf.get("name"),"pose":wf.get("pose")},motion_only=True,unknown=True)
    gate("active_tool_definition",definition_valid(tf),"ACTIVE_TOOL_DEFINITION_UNCONFIRMED",
         {"id":tool,"name":tf.get("name"),"pose":tf.get("pose"),
          "note":"Active tool definition is distinct from calibrated grasp TCP/full gripper geometry."},
         motion_only=True,unknown=True)
    ee=target.get("ee_pose",{})
    if not isinstance(ee,dict): ee={}
    bound=(ee.get("frame_semantics_status")=="CONFIRMED" and
           ee.get("reference_frame_id")==work and ee.get("target_frame_id")==tool and
           bool(ee.get("binding_evidence")))
    gate("ee_pose_frame_binding",bound,"EE_POSE_FRAME_BINDING_UNCONFIRMED",
         {"reference_frame_id":ee.get("reference_frame_id"),"target_frame_id":ee.get("target_frame_id"),
          "status":ee.get("frame_semantics_status"),"evidence":ee.get("evidence"),
          "binding_evidence":ee.get("binding_evidence")},
         motion_only=True,unknown=True)
    preview=local_translation_preview(a,target) if not schema_errors else {"status":"UNAVAILABLE"}
    ws=policy["local_workspaces"].get(arm,{}) if isinstance(arm,str) else {}
    bounds=ws.get("bounds_m") or {}
    if not isinstance(bounds,dict): bounds={}
    ws_verified=(_verified(ws) and ws.get("human_confirmed") is True and
                 ws.get("swept_tool_clearance_verified") is True and
                 ws.get("scope")=="local_free_space_translation_only" and
                 ws.get("frame_id")==work and ws.get("tool_frame_id")==tool and
                 ws.get("frame_fingerprint")==wf.get("definition_fingerprint") and
                 ws.get("tool_fingerprint")==tf.get("definition_fingerprint") and
                 vector(bounds.get("min"),3) and vector(bounds.get("max"),3) and
                 all(lo<hi for lo,hi in zip(bounds["min"],bounds["max"])))
    gate("local_workspace_definition",ws_verified,"LOCAL_WORKSPACE_UNCONFIRMED",ws,motion_only=True,unknown=True)
    inside=(ws_verified and bound and preview.get("status")=="NUMERIC_PREVIEW_ONLY" and
            all(all(lo<=v<=hi for lo,v,hi in zip(bounds["min"],point,bounds["max"]))
                for point in (preview["start_xyz_m"],preview["target_xyz_m"])))
    gate("workspace_segment",inside,"WORKSPACE_SEGMENT_NOT_VERIFIED",
         {"preview":preview,"method":"Both endpoints in a certified convex AABB; fixed orientation and certified swept-tool clearance."},
         motion_only=True,unknown=not ws_verified or not bound)
    geometry=policy["full_gripper_geometry"]
    full_geometry=_verified(geometry)
    local_clearance=policy.get("phase")=="local_translation_shadow" and ws_verified
    gate("tool_geometry_for_phase",full_geometry,"FULL_GRIPPER_GEOMETRY_UNCONFIRMED",
         {"phase":policy.get("phase"),"full_geometry":geometry,
          "local_clearance_verified":local_clearance,"required_before":geometry.get("required_before")},
         motion_only=True,unknown=True,warning=local_clearance)
    # This declaration comes from the trusted adapter, never from model output.
    transform_used=TRANSFORM_CONTRACT["camera_to_robot_transform_used"]
    extrinsics=_verified(policy["camera_extrinsics"])
    gate("camera_transform_dependency",not transform_used or extrinsics,
         "CAMERA_TRANSFORM_REQUIRES_VERIFIED_EXTRINSICS",
         {"adapter":TRANSFORM_CONTRACT,"extrinsics_status":policy["camera_extrinsics"].get("status")})
    gate("perception_grounding",extrinsics,"CAMERA_EXTRINSICS_UNCONFIRMED_GROUNDING_WARNING",
         {"note":"No camera-to-robot numerical transform is used; visual intent/direction remains unverified."},
         warning=True,unknown=True)
    readiness=execution_readiness or {}
    for name,key in (("trajectory_validation","trajectory_validation"),
                     ("execution_authorization","operator_authorization"),("hardware_executor","hardware_executor")):
        gate(name,_verified(readiness.get(key)),key.upper()+"_NOT_VERIFIED",
             readiness.get(key) or policy.get("execution_readiness",{}).get(key),
             motion_only=True,unknown=True)

    errors=list(dict.fromkeys(errors)); warnings=list(dict.fromkeys(warnings))
    outcome="REJECT" if errors else ("PASS_NOOP" if is_noop else "PASS_EXECUTABLE")
    return {"decision":outcome,"outcome":outcome,"is_noop":is_noop,"non_zero":not is_noop and not schema_errors,
            "action_schema_valid":not schema_errors,"gates":gates,"errors":errors,"warnings":warnings,
            "transform_preview":preview,"frame_adapter":TRANSFORM_CONTRACT,
            "execution_permitted":False,"hardware_commands_sent":0,"motion_commands_sent":0,
            "execution_backend":"DryRunExecutor","numeric_limits":{"translation_axis_m":.002,
                "rotation_rpy_rad":[0,0,0],"gripper":"hold"},
            "outcome_semantics":"PASS_EXECUTABLE requires all gates including trusted execution readiness; shadow executor never actuates."}

def assess_decision(action, observation, policy, now, generated_at=None, execution_readiness=None):
    """Malformed trusted input must fail closed as well as malformed proposals."""
    try:
        return _assess_decision(action, observation, policy, now, generated_at, execution_readiness)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as exc:
        return rejected(["SAFETY_INPUT_MALFORMED:"+type(exc).__name__])
