"""One placement expansion, shared by primitive and skill scheduling/backends."""
from copy import deepcopy


def placement_primitives(approach, release_pose, retract, opening=1.0):
    return deepcopy([
        {'name': 'approach', 'kind': 'move', 'target': approach},
        {'name': 'release_pose', 'kind': 'move', 'target': release_pose},
        {'name': 'release', 'kind': 'set_gripper', 'opening': opening},
        {'name': 'retract', 'kind': 'move', 'target': retract},
    ])
