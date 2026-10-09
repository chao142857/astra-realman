"""Referential checks of model data, before evidence publication. No geometry/owner."""
from .contracts import validate_plan

def validate_role(role, result, attachments, binding, world):
    allowed = {a['id']: a for a in attachments}
    if role == 'action_shadow':
        if result['grants_execution'] is not False or result['K'] != 0: raise ValueError('SHADOW_AUTHORITY')
        if result['decision'] == 'planned':
            if result['plan'] is None: raise ValueError('SHADOW_PLAN_REQUIRED')
            if result['plan']['version'] != 'astra.action_chunk_plan.v2' or result['plan']['H'] != 4 or result['plan']['m'] != 1: raise ValueError('SHADOW_H4_M1')
            validate_role('action', result['plan'], attachments, binding, world)
        elif result['plan'] is not None: raise ValueError('SHADOW_REFUSAL_HAS_PLAN')
        return
    if role == 'semantic_grounding':
        ids = [x['geometry_instance_id'] for x in result['objects']]
        if len(ids) != len(set(ids)) or set(ids) != set(world['state']['entities']): raise ValueError('GROUNDING_IDS')
        if result['task_target_geometry_id'] is not None and (result['task_target_geometry_id'] not in ids or result['target_status'] != 'hypothesis'): raise ValueError('GROUNDING_TARGET')
        if result['target_status'] == 'hypothesis' and result['task_target_geometry_id'] is None: raise ValueError('GROUNDING_TARGET_MISSING')
        target = next((x for x in result['objects'] if x['geometry_instance_id']==result['task_target_geometry_id']), None)
        if target and (target['semantic_status']!='hypothesis' or target['disposition'] not in ('object','region')): raise ValueError('GROUNDING_TARGET_UNKNOWN')
        for x in result['objects'] + result['requests']:
            if not x['evidence_refs'] or not set(x['evidence_refs']) <= set(allowed): raise ValueError('GROUNDING_IMAGE_REF')
        for x in result['requests']:
            if not set(x['geometry_instance_ids']) <= set(ids): raise ValueError('GROUNDING_REQUEST_IDS')
            if x['bbox'] is not None:
                x0,y0,x1,y1 = x['bbox']
                if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1: raise ValueError('GROUNDING_REQUEST_BBOX')
                if not any(allowed[ref]['camera'] == x['camera'] for ref in x['evidence_refs']):
                    raise ValueError('GROUNDING_BBOX_CAMERA_EVIDENCE')
        return
    if role == 'action':
        validate_plan(result)
        for key in ('world_id', 'world_revision', 'execution_epoch'):
            if result[key] != binding[key]: raise ValueError('ACTION_BINDING:' + key)
        if result['source_observation_id'] not in binding['observation_ids']:
            raise ValueError('ACTION_OBSERVATION')
        if result['version'] == 'astra.action_chunk_plan.v2':
            if world is None or result['read_versions'] != world['read_versions']: raise ValueError('READ_VERSIONS')
            if not set(result['evidence_refs']) <= set(binding['evidence_ids']): raise ValueError('ACTION_EVIDENCE')
            entities = world['state']['entities']
            for k in ('object_id', 'goal_id'):
                identity = result['task_binding'][k]
                if identity and identity not in entities: raise ValueError('ACTION_INSTANCE_ID')
        return
    if result.get('version') == 'astra.semantic_scene.v2':
        ids = [e['entity_id'] for e in result['entities']]
        if len(set(ids)) != len(ids): raise ValueError('DUPLICATE_INSTANCE_ID')
        if result['task_target_id'] is not None and result['task_target_id'] not in ids:
            raise ValueError('TASK_TARGET_NOT_AN_ENTITY')
        for entity in result['entities']:
            cameras = []
            for view in entity['views']:
                _view(view, allowed)
                camera = allowed[view['attachment_id']]['camera']
                if camera in cameras: raise ValueError('DUPLICATE_ENTITY_VIEW')
                cameras.append(camera)
        for relation in result['relations']:
            if relation['subject'] not in ids or relation['object'] not in ids or not set(relation['evidence_refs']) <= set(allowed):
                raise ValueError('UNBOUND_SEMANTIC_RELATION')
    elif 'regions' in result:
        for region in result['regions']: _view(region, allowed)

def _view(view, allowed):
    if view['attachment_id'] not in allowed: raise ValueError('UNSEEN_SEMANTIC_VIEW')
    x0,y0,x1,y1 = view['bbox']
    if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1: raise ValueError('REGION_BBOX')
