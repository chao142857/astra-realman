"""Model-owned proposal -> host-bound v2 plan, for permanent shadow only.

No client, controller or alternate execution path. Waypoints are copied exactly;
only fixed requirements and trusted runtime fields are added. Current-fact
receipts never satisfy future waypoint prerequisites or physical admission.
"""
import hashlib
import jsonschema
from sim_skills.full_pnp.wire import obj
from .contracts import clone, digest
from . import chunk_plan

VERSION = 'astra.action_proposal.v1'
INSTRUCTION = (
    'NONEXECUTABLE HYPOTHESIS GENERATION. Read the frozen task, compact world, RGB and measured robot state. '
    'Return only an astra.action_proposal.v1: decision, proposal, reason, assumptions, unknowns and optional additional claims. '
    'Host owns origin, task/world/epoch/read versions, H=4 maximum, m=1, K=0, provenance and permissions; do not echo or override them. '
    'Pose is [x,y,z,qw,qx,qy,qz], world frame, metres, unit quaternion wxyz, pad/grasp-center position with flange orientation; '
    'nominal_end_offset_s is seconds, not measured completion. No gripper/contact. '
    'First step is checked against the supplied MEASURED origin; subsequent steps against the previous proposed pose. '
    'Use meaningful coarse increments: 20-50mm translation or meaningful rotation, <=0.15rad rotation per step, '
    'nominal offsets 2*i seconds and prediction_dependencies=[1,...,i-1]. No noop or microstep padding. '
    'Four waypoints with horizon_filled require boundary_after=none throughout. A justified stage_terminal may have 1-4 waypoints '
    'with precontact_handoff or phase_end only at the final waypoint. Do not change coordinates to fill the horizon. '
    'Every waypoint is a hypothesis. You need not prove IK, collision or clearance before proposing; these remain NOT_TESTED. '
    'Never infer hidden free space. Bounds are observed surfaces, not exact grasp centers. State necessary assumptions explicitly. '
    'Fixed prerequisites are created by the host, not fulfilled by listing them. Additional claims are optional. '
    'supported_by_input claims require genuine sent evidence refs, scope=current, and describe only captured coarse geometry, '
    'identity hypothesis, captured visibility or recorded robot state. Their free-text basis remains subject to independent review. '
    'Future joins/visibility and owner admission cannot be supported_by_input. Do not invent citations. '
    'Use refused for conflicts or need_more_evidence when no meaningful candidate exists; proposal=null for both. '
    'No output can grant execution.')

def proposal_schema():
    base=chunk_plan.plan_schema()['properties']
    wp=clone(base['waypoints']['items'])
    del wp['properties']['preconditions'];wp['required'].remove('preconditions')
    wp['properties']['index']['maximum']=4
    text={'type':'string','minLength':1}
    claim=obj({'waypoint_index':{'type':'integer','minimum':1,'maximum':4},
        'precondition':{'type':'string','enum':chunk_plan.PRECONDITIONS},
        'scope':{'type':'string','enum':['current','future']},
        'status':{'type':'string','enum':['supported_by_input','unverified','conflict']},
        'basis':text,'evidence_refs':{'type':'array','items':text,'uniqueItems':True}})
    proposal=obj({'waypoints':{'type':'array','items':wp,'minItems':1,'maxItems':4},'termination':clone(base['termination'])})
    return obj({'version':{'type':'string','const':VERSION},
        'decision':{'type':'string','enum':['planned','refused','need_more_evidence']},
        'proposal':{'anyOf':[proposal,{'type':'null'}]},'reason':text,
        'assumptions':{'type':'array','items':text,'maxItems':16},
        'unknowns':{'type':'array','items':text},
        'additional_claims':{'type':'array','items':claim,'maxItems':20}})

def host_context(world, observation):
    from .review_contracts import planning_review_eligibility, shadow_schema
    planning_review_eligibility(world,observation)
    selection=world['state'].get('task_selection')
    if not selection:raise ValueError('PROPOSAL_SEMANTIC_TASK_REQUIRED')
    task=selection['task'];tb={'profile':'generic_semantic_v1','object_id':selection['task_target_geometry_id'],'goal_id':''}
    # Retain legacy real-semantic task/source requirements; this does NOT lower task_usable.
    shadow_schema(world,observation,task,tb)
    constants=chunk_plan.request_schema(world,observation,task,tb,4,list(world['binding']['evidence_ids']))['properties']
    return {'version':'astra.action_proposal_host.v1','plan_fields':{k:clone(v['const']) for k,v in constants.items() if 'const' in v},
        'observation_sha256':digest(observation),'world_sha256':digest(world),
        'pose_convention':'world metres xyz + unit quaternion wxyz; pad/grasp-center position and flange orientation',
        'time_convention':'nominal seconds, not completion time',
        'K':0,'grants_execution':False,'planning_level':'HYPOTHESIS_GENERATION',
        'physical_checks':{'IK':'NOT_TESTED','collision':'NOT_TESTED','clearance':'NOT_TESTED','owner_admission':'NOT_GRANTED','hidden_space':'UNKNOWN_NOT_FREE'}}

def proposal_request(world, observation):
    from .review_contracts import shadow_request
    h=host_context(world,observation);p=h['plan_fields']
    r=shadow_request(world,observation,p['task'],p['task_binding'])
    r.update(instruction=INSTRUCTION,output_schema=proposal_schema())
    return r

def is_proposal(schema):
    return schema.get('properties',{}).get('version',{}).get('const')==VERSION

def validate_result(result, attachments, binding, world):
    """References and current-fact claims; adaptation additionally validates actual origin."""
    jsonschema.validate(result,proposal_schema());clone(result)
    p=result['proposal'];planned=result['decision']=='planned'
    if planned != (p is not None):raise ValueError('PROPOSAL_DECISION')
    if planned and not result['assumptions']:raise ValueError('PROPOSAL_ASSUMPTIONS_REQUIRED')
    target=world['state']['entities'][world['state']['task_selection']['task_target_geometry_id']]
    if planned and (target.get('status')!='coarse' or target.get('point_world_m') is None):
        raise ValueError('PROPOSAL_CURRENT_TARGET_REQUIRED')
    allowed={a['id']:a for a in attachments};eids=set(binding['evidence_ids'])
    seen=set()
    for c in result['additional_claims']:
        key=(c['waypoint_index'],c['precondition'],c['scope'])
        if key in seen:raise ValueError('DUPLICATE_ADDITIONAL_CLAIM')
        seen.add(key)
        if p is not None and c['waypoint_index']>len(p['waypoints']):raise ValueError('CLAIM_WAYPOINT')
        refs=set(c['evidence_refs'])
        if not refs <= set(allowed)|eids:raise ValueError('PROPOSAL_UNSENT_EVIDENCE')
        if planned and c['status']=='conflict':raise ValueError('PLANNED_WITH_EXPLICIT_CONFLICT')
        if c['status']!='supported_by_input':continue
        if not refs:raise ValueError('PROPOSAL_SUPPORT_WITHOUT_EVIDENCE')
        if c['scope']!='current' or c['precondition']=='owner_admission':raise ValueError('FUTURE_OR_OWNER_NOT_VERIFIED')
        name=c['precondition']
        if name=='target_identity_hypothesis':
            if target.get('semantic_status')!='hypothesis' or target.get('semantic_evidence_id') not in refs:
                raise ValueError('PROPOSAL_IDENTITY_EVIDENCE')
        else:
            cameras={allowed[x]['camera'] for x in refs & set(allowed) if allowed[x]['observation_id']==world['state']['observation_id']}
            if not cameras:raise ValueError('PROPOSAL_CURRENT_OBSERVATION_REF')
            if name in ('current_geometry','visibility'):
                rows=[v for v in target.get('current_evidence',[]) if v.get('camera') in cameras and v.get('observation_id')==world['state']['observation_id'] and v.get('current_points',v.get('valid_depth_pixels',0))>0]
                if not rows or target.get('status')!='coarse':raise ValueError('PROPOSAL_CURRENT_GEOMETRY_REF')
            # measured_join scope=current means recorded start only, not a future join.
            if name=='measured_join' and c['waypoint_index']!=1:raise ValueError('FUTURE_JOIN_NOT_VERIFIED')

def adapt(result, host, world, observation, attachments, binding, envelope_refs):
    """Pure deterministic wrapping; no numerical modification or synthetic references."""
    if host!=host_context(world,observation):raise ValueError('STALE_OR_MODIFIED_PROPOSAL_HOST')
    for key in ('world_id','world_revision','execution_epoch'):
        if binding[key]!=host['plan_fields'][key]:raise ValueError('PROPOSAL_HOST_BINDING:'+key)
    if binding['observation_ids']!=[observation['observation_id']] or binding['evidence_ids']!=host['plan_fields']['evidence_refs']:
        raise ValueError('PROPOSAL_HOST_EVIDENCE_BINDING')
    validate_result(result,attachments,binding,world)
    if any(not set(c['evidence_refs'])<=set(envelope_refs) for c in result['additional_claims']):
        raise ValueError('UNBOUND_PROPOSAL_CLAIM')
    if not set(host['plan_fields']['evidence_refs'])<=set(envelope_refs):raise ValueError('UNBOUND_HOST_PLAN_EVIDENCE')
    plan=None;requirements=[]
    if result['proposal'] is not None:
        plan=clone(host['plan_fields']);plan.update(clone(result['proposal']))
        for w in plan['waypoints']:
            w['preconditions']=clone(chunk_plan.PRECONDITIONS)
            requirements.extend({'waypoint_index':w['index'],'precondition':p,'status':'unverified','source':'HOST_REQUIREMENT_NOT_EVIDENCE'} for p in chunk_plan.PRECONDITIONS)
        # Both exact host-bound local schema and unchanged internal action validation.
        ps=chunk_plan.request_schema(world,observation,plan['task'],plan['task_binding'],4,plan['evidence_refs'])
        jsonschema.validate(plan,ps)
        from .output_validation import validate_role
        validate_role('action',plan,attachments,binding,world)
        if [{k:v for k,v in w.items() if k!='preconditions'} for w in plan['waypoints']] != result['proposal']['waypoints']:
            raise ValueError('ADAPTER_WAYPOINT_MUTATION')
    # Current evidence receipts attest only the narrow fact kind and captured sources.
    facts=[{'claim_index':i,'fact_kind':c['precondition'],'scope':'CAPTURED_CURRENT_FACT_ONLY',
        'verifier':'action_proposal.validate_result.v1','world_sha256':host['world_sha256'],
        'observation_sha256':host['observation_sha256'],'evidence_refs':clone(c['evidence_refs']),
        'satisfies_future_waypoint':False,'free_text_basis':'INDEPENDENT_REVIEW_REQUIRED'}
        for i,c in enumerate(result['additional_claims']) if c['status']=='supported_by_input']
    return {'version':'astra.action_proposal_derivation.v1','proposal_sha256':digest(result),
        'internal_plan_sha256':digest(plan),'host_context_sha256':digest(host),'plan':plan,
        'requirements':requirements,'current_fact_receipts':facts,'K':0,'grants_execution':False,
        'physical_checks':clone(host['physical_checks']),'all_waypoints_are_hypotheses':True}

def source_stamp(row, derived):
    return {'producer':row['provenance'],'request_id':row['request_id'],
        'raw_sha256':hashlib.sha256(row['raw'].encode()).hexdigest(),'wire_sha256':row['wire_sha256'],
        'binding':clone(row['binding']),'proposal_sha256':derived['proposal_sha256'],
        'internal_plan_sha256':derived['internal_plan_sha256'],'execution_class':'REVIEW_ONLY','grants_execution':False}
