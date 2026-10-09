"""Small role request builders over the existing Broker; no calls at import time."""
from . import chunk_plan, fusion

def semantic_request(observation_id):
    return {'backend':'existing_codex_infer','role':'semantic_e0',
        'instruction':('Build an initial multi-entity semantic scene from these three frozen RGB images. '
            'The frozen T1 demo task is: approach the red block to a pregrasp ready pose without contact. '
            'Select its instance ID as task_target_id only if unambiguous; otherwise null. This does not restrict other scene entities. '
            'Use stable instance IDs shared only when cross-view identity is supported. Include objects and task regions, '
            'spatial relation hypotheses and unknowns. Each bbox is in its actual attachment normalized coordinates. '
            'Bbox centers are not cross-view 3D correspondences. Do not invent depths, held state or hidden identities. '
            'Return the requested schema with actual evidence references.'),
        'images':[{'observation_id':observation_id,'camera':c,'roi':None} for c in ('assembly','fixed','wrist')],
        'evidence_ids':[],'world_id':None,'output_schema':fusion.semantic_schema(),'timeout_s':90}

def action_request(world,observation,task,task_binding,H=4):
    from .geometry_quality import require_task_usable
    require_task_usable(world,task_binding)
    if world['state']['backend']!='semantic_lwh_v1':raise ValueError('FUSED_LWH_WORLD_REQUIRED')
    if H not in (1,4,6,8):raise ValueError('HORIZON')
    eid=world['state']['semantic_evidence_id']
    return {'backend':'existing_codex_infer','role':'action',
        'instruction':('Produce bounded coarse PRECONTACT move_pose waypoints only, pad center world xyz and wxyz quaternion. '
            'Each waypoint uses the same 20-50mm translation domain, rotation <=0.15rad, nominal 2s spacing; '
            '2s is a forecast coordinate, not a duration guarantee. Rotation-only >=0.05rad allowed. '
            'No gripper, fine contact, padded noop or fabricated measured states. Use H requested or a justified stage_terminal '
            'ending in precontact_handoff/phase_end, with a shorter terminal step allowed. Read the supplied WorldSnapshot; '
            'uncertain region support is not an object center or grasp pose. If no defensible plan exists, fail rather than invent one. '
            'Predict dependencies on the entire preceding waypoint prefix; all original source bindings must remain exact.'),
        'images':[{'observation_id':observation['observation_id'],'camera':c,'roi':None} for c in ('assembly','fixed','wrist')],
        'evidence_ids':[eid],'world_id':world['world_id'],
        'output_schema':chunk_plan.request_schema(world,observation,task,task_binding,H,[eid]),'timeout_s':90}
