"""One-run normal simulation proposal intent. Never converts a shadow result."""
from . import action_proposal as ap
from .contracts import clone
VERSION='astra.action_proposal.t1_sim.v1'
ROLE='t1_action_proposal'
INSTRUCTION=(
    'AUTHORIZED SIMULATION T1 CANDIDATE, not a shadow result or an execution ticket. '
    'Propose only noncontact pre-approach move_pose waypoints for the bound semantic target. '
    'The host will independently submit each unmodified candidate to the original Owner checks. '
    'Completion target: measured grasp-center XY within 20mm of the currently observed target bounds midpoint, '
    'grasp-center Z 60-100mm above the observed bounds maximum Z, initial orientation preserved within 0.05rad. '
    'Use the actual origin and current measured world; no contact, gripper, invented free space or physical safety claim. '
    'H maximum 4, m=1. Pose [x,y,z,qw,qx,qy,qz] is world metres, grasp-center position and flange wxyz orientation. '
    'Each step <=50mm and <=0.15rad, no noop or microstep padding; nominal time 2*i seconds and dependencies [1,...,i-1]. '
    'Use horizon_filled for four steps with boundary_after=none. Use stage_terminal for a meaningful final precontact_handoff '
    'or phase_end with 1-4 steps. Short final increments are allowed by the unchanged local contract. '
    'You need not prove IK/collision/clearance to propose, but they must pass before execution. '
    'The host owns origin, H/m, task/world/epoch/read_versions, source and all execution authority; do not output those fields. '
    'Return astra.action_proposal.t1_sim.v1. State necessary assumptions, unknowns and optional additional evidence claims. '
    'supported_by_input requires legitimate sent evidence refs, scope=current, for captured geometry/identity/visibility or '
    'recorded start only. Future joins/visibility and owner admission cannot be asserted as satisfied. '
    'Return refused or need_more_evidence with proposal=null if appropriate. No examples or scripted waypoint answer are supplied.')

def request(world,observation):
    h=ap.host_context(world,observation)
    return {'backend':'existing_codex_infer','role':ROLE,'world_id':world['world_id'],
        'evidence_ids':list(world['binding']['evidence_ids']),
        'images':[{'observation_id':observation['observation_id'],'camera':c,'roi':None} for c in ('assembly','fixed','wrist')],
        'instruction':INSTRUCTION,'output_schema':ap.proposal_schema(version=VERSION),'timeout_s':90}

def validate_request(req,w,o):
    if req!=request(w,o):raise ValueError('T1_VERSIONED_REQUEST_MISMATCH')

def validate_result(result,attachments,binding,world):
    return ap.validate_result(result,attachments,binding,world,version=VERSION)

def adapt(result,host,world,observation,attachments,binding,refs):
    derived=ap.adapt(result,host,world,observation,attachments,binding,refs,version=VERSION)
    derived['intent']=ROLE
    derived['admission']='CANDIDATE_ONLY_ORIGINAL_OWNER_MUST_ADMIT_EACH_ACTION'
    return derived
