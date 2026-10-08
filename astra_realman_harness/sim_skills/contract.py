"""Public, prospective action descriptions from the existing shared generator."""
import copy
import json
from bimanual_demo.primitives import placement_primitives

TARGET_FIELDS = ('backend', 'arm', 'frame', 'tool', 'revision', 'pose_source', 'scope',
                 'validation_status', 'approach', 'release_pose', 'retract', 'release_opening')
SKILL_ID = 'fixed_green_marker_place_v1'


def action_catalog(targets):
    # No scene, observer, contacts, evaluator or history is consulted here.
    public_targets = {key: copy.deepcopy(targets[key]) for key in TARGET_FIELDS}
    expanded = placement_primitives(public_targets['approach'], public_targets['release_pose'],
                                    public_targets['retract'], public_targets['release_opening'])
    return {
        'version': 'placement_action_catalog_v1',
        'targets': public_targets,
        'units': {'position': 'metres', 'orientation': 'unit quaternion wxyz; dimensionless',
                  'gripper_opening': 'dimensionless [0,1]; 0=close, 1=open'},
        'pose_semantics': 'Target xyz is the dynamic pad centre in the named frame; '
                          'orientation is Link6 flange wxyz. Not a RealMan work/tool RPY pose.',
        'primitive_catalog': [
            {'name': 'approach', 'kind': 'move', 'target_ref': 'targets.approach',
             'description': 'Move the pad centre to the existing approach pose.'},
            {'name': 'release_pose', 'kind': 'move', 'target_ref': 'targets.release_pose',
             'description': 'Move the pad centre to the existing release pose.'},
            {'name': 'release', 'kind': 'set_gripper', 'target_ref': 'targets.release_opening',
             'description': 'Command the existing gripper opening, then perform the existing settling steps.'},
            {'name': 'retract', 'kind': 'move', 'target_ref': 'targets.retract',
             'description': 'Move the pad centre to the existing retract pose.'}],
        'skill': {'id': SKILL_ID, 'name': 'fixed target four-primitive placement',
                  'primitive_order': [p['name'] for p in expanded],
                  'semantics': 'Prospective commands, not predicted or measured outcomes. '
                               'Existing controller and common checks apply at every primitive. '
                               'Failed or missing checks stop the sequence without automatic retry.'},
        'expanded_sequence': expanded,
    }


def approval_request(catalog, condition, index):
    if type(index) is not int or not 0 <= index < len(catalog['expanded_sequence']):
        raise ValueError('OFFER_PRIMITIVE_INDEX')
    if condition == 'M':
        return {'scope': 'one_primitive', 'skill_id': SKILL_ID, 'primitive_index': index,
                'primitive': copy.deepcopy(catalog['expanded_sequence'][index]),
                'continue_means': 'Approve only this primitive, subject to existing common checks.',
                'stop_means': 'Approve no new primitive.'}
    if condition == 'S' and index == 0:
        return {'scope': 'complete_skill', 'skill_id': SKILL_ID,
                'primitive_indices': list(range(len(catalog['expanded_sequence']))),
                'continue_means': 'Approve the entire expanded_sequence in the listed order, '
                                  'subject to the same existing checks before every primitive.',
                'stop_means': 'Approve no new primitive.'}
    raise ValueError('OFFER_CONDITION_OR_SKILL_BOUNDARY')


def projected_offer(context):
    """Validate what will actually be sent, rejecting injected fields or stale offers."""
    catalog = context['action_catalog']
    expected = action_catalog(catalog['targets'])
    wire = lambda value: json.dumps(value, sort_keys=True, allow_nan=False)
    if wire(catalog) != wire(expected):
        raise ValueError('ACTION_CATALOG_MISMATCH')
    binding = context['binding']
    if catalog['targets']['revision'] != binding['revision']:
        raise ValueError('OFFER_REVISION_MISMATCH')
    offer = approval_request(catalog, binding['condition'], binding['primitive_index'])
    if wire(context['approval_request']) != wire(offer):
        raise ValueError('APPROVAL_REQUEST_MISMATCH')
    return copy.deepcopy(catalog), offer
