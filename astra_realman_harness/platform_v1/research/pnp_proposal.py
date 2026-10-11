"""Single-run normal PnP intent. Existing coarse plan and existing fine actions."""
import json,jsonschema
from . import action_proposal as ap,chunk_plan
from .contracts import clone,digest
from sim_skills.full_pnp.wire import obj
from sim_skills.full_pnp.protocol import validate_actions
VERSION='astra.action_proposal.full_pnp_sim.v1'
ROLE='pnp_action_proposal'
PHASES=['approach','grasp','trial_lift','transport','place','release','retreat','finish']
INSTRUCTION=(
 'AUTHORIZED FULL PICK AND PLACE SIMULATION, beginning empty handed. Pick the actual red cuboid, '
 'transport it to the visible green planar region, stably release and withdraw the open gripper. '
 'You decide spatial waypoints and grasp/release requests from current WorldQuery, RGB and measured robot state. '
 'Do not request approval of a host-scripted path. Poses are dynamic pad/grasp-center world XYZ metres and flange wxyz unit quaternion. '
 'Use mode=coarse for approach/transport chunks: original 1-4 move_pose waypoints, <=50mm and <=0.15rad each, '
 'nominal_end_offset_s=2*i, prediction_dependencies=[1,...,i-1]. Original meaningful coarse increments >=20mm or >=0.05rad; '
 'a shorter final step is allowed for justified stage_terminal, ending precontact_handoff or phase_end. '
 'Use mode=fine near contact: 1-3 existing move_pose/gripper/hold actions, no coarse lower step limit; '
 'fine move <=50mm/0.15rad. Gripper opening 1=open, 0=close; gripper must be LAST, always a measured observation barrier. '
 'Do not plan a lift as if closing has already succeeded; trial lift is a later request. Do not plan retreat as if release happened. '
 'hold seconds in (0,2]. Coarse proposal is null in fine mode, fine_actions empty in coarse mode. '
 'No coordinate repairs, clipping, interpolation or hidden-space assumptions by host. Original Owner, IK, collisions and STOP must admit actions. '
 'Existing contact holding/expected pad contact is available, not general collision disabling. '
 'Use actual observed surfaces/uncertainty, not an exact object-size prior. Align fingers and descend sufficiently for opposed side contact, without table penetration. '
 'Close command success only establishes a candidate; current visual lift and object-to-tool stability support carrying. '
 'The task requires actual >=50mm lift and stable carrying, then stable release inside the observed region and withdrawal >=30mm from object, '
 'open gap >70mm and grasp center Z>=80mm. A 1.2s measured hold can provide stability evidence. '
 'Budget <=8 Action requests, <=40 low-level actions including the local skill. '
 'Every action in this run is separately checked and submitted; choose meaningful phases without padding. '
 'The host owns origin/world/revision/epoch/read_versions/provenance and permissions. '
 'Verified Semantic source and task-target binding are host-owned; do not repeat their IDs merely to authorize a plan. '
 'Your evidence_refs remain your own citations. Any additional supported_by_input claim still needs its actual evidence refs, '
 'including the Semantic evidence ID if you explicitly claim target identity support. '
 'All untested IK, collisions, future joins and holding remain unknown; no unsupported claims. '
 'decision=planned requires proposal or fine_actions. decision=finished, refused or need_more_evidence requires proposal=null and fine_actions=[]. '
 'finished is only your verdict, independently scored. Do not retry failed control or failed model requests. '
 'Return the exact requested version and fields; use assumptions/unknowns for risks. Additional supported_by_input claims require actual evidence refs.')

PAIR_SKILL_INSTRUCTION=(
 '\nPAIRED ROLLOUT TOOL CONTRACT calibrated_grasp_request.v1: '
 'For phase=grasp, request the shared calibrated local grasp skill using mode=fine, proposal=null, '
 'fine_actions=[{"type":"gripper","opening":0.45}]. This is explicitly a TOOL REQUEST, not a raw actuator-only command. '
 'Do not guess the low-level closing height. The skill measures current target RGB-D XY, aligns at current height, '
 'descends in bounded local steps to public-table +40mm pad-center, and closes to opening 0.45 using the existing guarded contact controller. '
 'The tool needs a supported stationary tabletop target, open-empty initialization/history, downward orientation within 0.05rad, '
 'tool XY within 50mm of current target and height 40..150mm. Use your own approach chunk to reach that domain if needed. '
 'All generated tool primitives are labeled ENGINEERING_LOCAL_SKILL, independently Owner-admitted and counted. '
 'No model move_pose is changed. Other close requests are rejected for this pair. '
 'The skill ends after close and fresh measurement; it does not claim held or automatically transport. '
 'You decide subsequent trial lift, stability hold, transport, placement, release and retreat using new observations. '
 'The calibrated skill is shared by both comparison conditions and is not learned-policy grasp credit. '
 'A geometry-invalidated suffix is canceled; a new action request may use the latest observed state within the original budget. '
 'Unknown sensing does not authorize motion. No extra call is a retry of a failed model request. ')

def schema():
 s=ap.proposal_schema(version=VERSION);p=s['properties']
 p['decision']['enum'].append('finished')
 pose=clone(chunk_plan.plan_schema()['properties']['origin_pose_world'])
 action={'anyOf':[obj({'type':{'type':'string','const':'move_pose'},'pose':pose}),
   obj({'type':{'type':'string','const':'gripper'},'opening':{'type':'number','minimum':0,'maximum':1}}),
   obj({'type':{'type':'string','const':'hold'},'seconds':{'type':'number','exclusiveMinimum':0,'maximum':2}})]}
 p.update(mode={'type':'string','enum':['coarse','fine']},phase={'type':'string','enum':PHASES},fine_actions={'type':'array','items':action,'maxItems':3})
 s['required']+=['mode','phase','fine_actions'];return s

def transport_instruction(*, vanilla=False):
 # Shared task/tool text; only the available perception source differs.
 text=INSTRUCTION.replace(
  'AUTHORIZED FULL PICK AND PLACE SIMULATION, beginning empty handed. Pick the actual red cuboid, ',
  'AUTHORIZED TRANSPORT AND PLACE SUBTASK SIMULATION. Starting from the current observable post-initialization holding state, ')
 text=text.replace('transport it to the visible green planar region','transport the observed red cuboid to the visible green planar region')
 text=text.replace('grasp/release requests','release requests')
 text=text.replace('Do not plan a lift as if closing has already succeeded; trial lift is a later request. ', '')
 text=text.replace('Align fingers and descend sufficiently for opposed side contact, without table penetration. ', '')
 text=text.replace('Close command success only establishes a candidate; current visual lift and object-to-tool stability support carrying. ',
  'Current visual object-to-tool stability and measured feedback support continued carrying; closing alone is not holding evidence. ')
 text=text.replace('The task requires actual >=50mm lift and stable carrying, then stable release inside the observed region and withdrawal >=30mm from object, ',
  'This subtask requires transport with continued holding, stable release inside the observed region and withdrawal >=30mm from object, ')
 text=text.replace('Budget <=8 Action requests, <=40 low-level actions including the local skill. ',
  'Shared resources: <=1800s wall, <=80 low-level actions including initialization. No small model-call cap. Choose 1..4 coarse actions or fine actions; request new observation with need_more_evidence when needed. ')
 text+=(' Engineering grasp occurred before this subtask and earns no policy grasp credit. Do not request approach/grasp or another close. '
  'You need not prove the earlier engineering grasp or its lift height. Assess continued holding from your supplied public start/current observations and your own action feedback. '
  'You choose transport, placement, release and withdrawal; no route is prescribed. '
  'Your own subtask history retains all actions and measured states, with anchored historical images. Historical measurements are not current geometry. '
  'Return finished when this transport/place/release/withdrawal subtask is supported; physical_success and model_finished are recorded separately. '
  'Private initialization coordinates, contact truth and independent scores are not available as planning evidence.')
 if vanilla:
  text=text.replace('current WorldQuery, RGB','current RGB-D, camera calibration')
  text=text.replace('Verified Semantic source and task-target binding are host-owned; do not repeat their IDs merely to authorize a plan. ',
   'Identify target and destination using your own public sensors; there is no Semantic agent or WorldHead. ')
  text=text.replace('including the Semantic evidence ID if you explicitly claim target identity support. ', '')
 return text

def request(w,o):
 ap.host_context(w,o)
 instruction=INSTRUCTION+PAIR_SKILL_INSTRUCTION
 if w['state']['task_selection']['task']['id']=='RUN_TRANSPORT_PLACE_FROM_HELD':
  instruction=transport_instruction()
 if globals().get('AB_RESOURCE_CONTRACT',False):
  instruction=instruction.replace('Budget <=8 Action requests, <=40 low-level actions including the local skill. ', 'Shared resources: <=1800s wall, <=80 low-level actions including initialization. No small model-call cap. Choose 1..4 coarse actions or fine actions; request new observation with need_more_evidence when needed. ')
 return {'backend':'existing_codex_infer','role':ROLE,'world_id':w['world_id'],
  'evidence_ids':list(w['binding']['evidence_ids']),
  'images':[{'observation_id':o['observation_id'],'camera':c,'roi':None} for c in ('assembly','fixed','wrist')],
  'instruction':instruction,'output_schema':schema(),'timeout_s':90}

def validate_request(r,w,o):
 if r!=request(w,o):raise ValueError('PNP_VERSIONED_REQUEST')

def coarse_part(r):
 return {k:clone(r[k]) for k in ap.proposal_schema(version=VERSION)['properties']}

def validate_result(r,attachments,binding,w):
 jsonschema.validate(r,schema());clone(r)
 if r['decision']!='planned':
  if r['proposal'] is not None or r['fine_actions']:raise ValueError('PNP_NONPLAN_ACTIONS')
  rr=coarse_part(r);rr['decision']='refused';ap.validate_result(rr,attachments,binding,w,version=VERSION);return
 if r['mode']=='coarse':
  if r['fine_actions']:raise ValueError('PNP_COARSE_FINE_MIX')
  rr=coarse_part(r);rr.update(decision='refused',proposal=None)
  ap.validate_result(rr,attachments,binding,w,version=VERSION)
  if r['proposal'] is None or not r['assumptions']:raise ValueError('PNP_COARSE_PROPOSAL_REQUIRED')
 else:
  if r['phase'] not in ('grasp','trial_lift','place','release','retreat'):raise ValueError('PNP_FINE_PHASE')
  if r['proposal'] is not None or not r['fine_actions'] or not r['assumptions']:raise ValueError('PNP_FINE_CONTRACT')
  validate_actions(r['fine_actions'])
  # Reuse evidence-claim validation without inventing a coarse waypoint.
  rr=coarse_part(r);rr['decision']='refused';ap.validate_result(rr,attachments,binding,w,version=VERSION)
  pose=[*w['state']['robot_state']['actual_grasp_center_world'],*w['state']['robot_state']['flange_pose_world'][3:]]
  for a in r['fine_actions']:
   if a['type']=='move_pose':
    d,rot=chunk_plan.pose_error(pose,a['pose'])
    if d>.05+1e-9 or rot>.15+1e-9:raise ValueError('PNP_FINE_STEP_TOO_LARGE')
    pose=a['pose']

def adapt(r,host,w,o,attachments,binding,refs):
 if host!=ap.host_context(w,o):raise ValueError('PNP_HOST_CHANGED')
 if binding['episode_id']!=o['episode_id']:raise ValueError('PNP_HOST_EPISODE_BINDING')
 for key in ('world_id','world_revision','execution_epoch'):
  if binding[key]!=host['plan_fields'][key]:raise ValueError('PNP_STALE_BINDING')
 if binding['observation_ids']!=[o['observation_id']] or binding['evidence_ids']!=host['plan_fields']['evidence_refs']:
  raise ValueError('PNP_HOST_EVIDENCE_BINDING')
 validate_result(r,attachments,binding,w)
 recovery_only=r['decision'] in ('refused','need_more_evidence') and r['proposal'] is None and r['fine_actions']==[]
 # Broker independently verifies the immutable world's Semantic ancestry before
 # and after inference. These are host dependencies, not model-authored claims.
 # Never add them to raw/parsed model evidence_refs to satisfy the local plan.
 if not set(refs)<={a['id'] for a in attachments}|set(binding['evidence_ids']):raise ValueError('PNP_UNSENT_EVIDENCE')
 if any(not set(c['evidence_refs'])<=set(refs) for c in r['additional_claims']):raise ValueError('PNP_UNBOUND_CLAIM')
 derived={'plan':None,'actions':[],'proposal_sha256':digest(r),'host_sha256':digest(host),'grants_execution':False,'intent':ROLE,'recovery_only':recovery_only,'K':0,'execution_class':'RECOVERY_ONLY' if recovery_only else 'OWNER_ADMISSION_REQUIRED','trusted_request_evidence_ids':clone(binding['evidence_ids']),'model_evidence_refs':clone(refs)}
 derived['trusted_semantic_binding']={'version':'astra.pnp_host_semantic_binding.v1',
  'source':'HOST_VERIFIED_WORLD_DEPENDENCY_NOT_MODEL_CITATION',
  'binding':clone(binding),'task':clone(host['plan_fields']['task']),
  'task_binding':clone(host['plan_fields']['task_binding']),
  'read_versions':clone(host['plan_fields']['read_versions']),
  'world_sha256':host['world_sha256'],'observation_sha256':host['observation_sha256'],
  'grants_execution':False}
 if r['decision']=='planned':
  if r['mode']=='coarse':
   plan=clone(host['plan_fields']);plan.update(clone(r['proposal']))
   for wp in plan['waypoints']:wp['preconditions']=clone(chunk_plan.PRECONDITIONS)
   jsonschema.validate(plan,chunk_plan.request_schema(w,o,plan['task'],plan['task_binding'],4,plan['evidence_refs']))
   chunk_plan.validate(plan)
   derived.update(plan=plan,actions=chunk_plan.actions(plan))
  else:derived['actions']=clone(r['fine_actions'])
 derived['actions_sha256']=digest(derived['actions']);return derived
