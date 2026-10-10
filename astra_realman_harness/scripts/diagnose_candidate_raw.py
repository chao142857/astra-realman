"""Read-only layered analysis; never constructs a repaired or executable plan."""
import argparse, hashlib, json, math
from pathlib import Path
import jsonschema
from platform_v1.research.chunk_plan import pose_error

def diagnose(source):
    read=lambda name:json.loads((source/name).read_text())
    raw=read('RAW_RESPONSE.json')['raw'];answer=json.loads(raw);r=answer['result'];p=r['plan']
    o=read('OBSERVATION.json');world=read('WORLD.json')
    measured=[*o['state']['actual_grasp_center_world'],*o['state']['flange_pose_world'][3:]]
    rows=[];last=p['origin_pose_world']
    for w in p['waypoints']:
        d,a=pose_error(last,w['pose']); rows.append({'original_waypoint':w,'distance_from_original_predecessor_m':d,'rotation_rad':a});last=w['pose']
    e=world['state']['entities'][p['task_binding']['object_id']]
    bounds=e.get('bounds_world_m') or e['coarse_observed_bounds_world_m'];end=last[:3]
    outside=[max(lo-v,0.,v-hi) for v,lo,hi in zip(end,*bounds)]
    claims=r['precondition_assessments']
    def leaves(error):
        if error.context:
            for child in error.context:yield from leaves(child)
        else:yield error
    errors=[{'path':list(x.absolute_path),'validator':x.validator,'message':x.message}
        for error in jsonschema.Draft202012Validator(read('AUTHORITATIVE_SCHEMA.json')).iter_errors(answer) for x in leaves(error)]
    from platform_v1.research.chunk_plan import validate
    from platform_v1.research.review_contracts import validate_candidate_result
    wire=read('EXPECTED_WIRE.json');local_checks={}
    for name,call in [('unchanged_chunk_plan_v2',lambda:validate(p)),
            ('unchanged_candidate_claim_validator',lambda:validate_candidate_result(r,wire['attachments'],wire['binding'],world))]:
        try:call();local_checks[name]='PASS'
        except Exception as exc:local_checks[name]=type(exc).__name__+': '+str(exc)

    return {'version':'astra.candidate_raw_layered_diagnosis.v1','frozen_result':'FAIL_STOP_LOCAL_OUTPUT_CONTRACT',
        'raw_utf8_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'input_files_sha256':{n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ('RAW_RESPONSE.json','WORLD.json','OBSERVATION.json','AUTHORITATIVE_SCHEMA.json')},
        'original_result_verbatim_values':r,'waypoint_table':rows,'original_origin':p['origin_pose_world'],'frozen_measured_origin':measured,
        'original_origin_to_first_m':pose_error(p['origin_pose_world'],p['waypoints'][0]['pose'])[0],
        'measured_origin_to_first_DIAGNOSTIC_ONLY_m':pose_error(measured,p['waypoints'][0]['pose'])[0],
        'origin_translation_echo_error_m':math.dist(measured[:3],p['origin_pose_world'][:3]),
        'origin_orientation_echo_error_rad':pose_error(measured,p['origin_pose_world'])[1],
        'target':{'id':p['task_binding']['object_id'],'status':e['status'],'point_world_m':e['point_world_m'],'observed_bounds_world_m':bounds,
            'endpoint_world_m':end,'endpoint_minus_support_point_m':[a-b for a,b in zip(end,e['point_world_m'])],
            'endpoint_distance_to_observed_AABB_m':math.sqrt(sum(v*v for v in outside)),
            'endpoint_xy_within_observed_bounds':all(bounds[0][i]<=end[i]<=bounds[1][i] for i in (0,1)),
            'endpoint_z_above_observed_bounds_max_m':end[2]-bounds[1][2],
            'clearance_interpretation':'Surface bounds only; NOT a collision/clearance certificate'},
        'runtime_echo_errors':errors,'unchanged_local_validators':local_checks,
        'action_geometry':{'raw_origin_first_step_violates_50mm':rows[0]['distance_from_original_predecessor_m']>.05,
            'measured_origin_alternative_not_plan_repair':True,'subsequent_steps_within_50mm':all(x['distance_from_original_predecessor_m']<=.05 for x in rows[1:]),
            'termination_boundary_conflict':p['termination']['kind']=='horizon_filled' and any(w['boundary_after']!='none' for w in p['waypoints']),
            'all_orientation_changes_rad':[x['rotation_rad'] for x in rows]},
        'evidence_declaration_errors':[x for x in claims if x['status']=='supported_by_input' and not x['evidence_refs']],
        'assumptions_original':r['assumptions'],'precondition_assessments_original':claims,'unknowns_original':r['unknowns'],
        'IK':'NOT_TESTED','collision':'NOT_TESTED','clearance':'NOT_TESTED','K':0,'grants_execution':False,
        'no_modified_answer_or_new_contract_real_success':True}

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--source',type=Path,required=True);a.add_argument('--out',type=Path,required=True);x=a.parse_args()
    result=diagnose(x.source);x.out.mkdir(parents=True,exist_ok=False)
    (x.out/'DIAGNOSIS.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (x.out/'ORIGINAL_MODEL_RAW.txt').write_text(json.loads((x.source/'RAW_RESPONSE.json').read_text())['raw'])
    print(json.dumps({k:result[k] for k in ('original_origin_to_first_m','measured_origin_to_first_DIAGNOSTIC_ONLY_m','target','action_geometry')},indent=2))
