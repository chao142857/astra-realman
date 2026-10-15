"""Private left pickup only. No expert receiving, handoff or exit action."""
from initial_v1 import expert_move


def prepare_left(world):
    from dual_scene import LAYOUT
    xy = LAYOUT['cube_initial_xyz'][:2]
    for z in (.20, .08, .04):
        expert_move(world, 'left', [*xy, z], [0, 1, 0, 0])
    world.phase_name = 'transfer_initial_left_close'
    world.arms['left'].gripper(.45)
    world.tick(100)
    p = world.arms['left'].state()['actual_grasp_center_world']
    expert_move(world, 'left', [p[0], p[1], p[2]+.14], [0, 1, 0, 0])
    world.phase_name = 'transfer_initial_left_hold'
    world.tick(750)
    if not world.arms['left'].bilateral_pad_contact():
        raise RuntimeError('LEFT_INITIAL_HOLD_FAILED')
    return world.observe(world.output / 'handoff_initial')
