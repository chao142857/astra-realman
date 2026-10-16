"""Render a versioned layout on yanglab; never imports a model or hardware client."""
import argparse
import json
import math
import os
from pathlib import Path


def angle_below_horizontal(direction):
    return math.degrees(math.atan2(-direction[2], math.hypot(*direction[:2])))


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', type=Path, default=root / 'scene_v2_wide180.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-only', action='store_true', help='Configuration math only; no simulation')
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text())
    left, right = layout['left_base'], layout['right_base']
    overhead = layout['cameras']['overhead']
    separation = math.dist(left[:3], right[:3])
    requested_distance = layout['change_from_v1']['base_separation_m']
    angle = angle_below_horizontal([b-a for a, b in zip(overhead['position'], overhead['look_at'])])
    checks = {
        'requested_base_distance': math.isclose(separation, requested_distance, abs_tol=1e-9),
        'unchanged_midpoint': math.isclose((left[0]+right[0])/2, .36, abs_tol=1e-9),
        'requested_camera_angle': math.isclose(angle, 75, abs_tol=1e-9),
        'four_roles': set(layout['cameras']) == {'overhead', 'tabletop_front', 'left_wrist', 'right_wrist'},
        'stands_supported': all(abs(base[i]-layout['table_center'][i]) + .06 <= layout['table_half_size'][i]
                                for base in (left, right) for i in (0, 1)),
    }
    report = {'layout': layout['version'], 'base_distance_m': separation,
              'camera_degrees_below_horizontal': angle, 'checks': checks,
              'real_astra_requests': 0, 'handoff_reachability': 'NOT_REVALIDATED',
              'simulation_rendered': False}
    if not all(checks.values()):
        raise ValueError(report)
    if not args.check_only:
        if args.output is None:
            parser.error('--output is required for rendering (must not exist)')
        os.environ['RM65_LAYOUT'] = str(args.layout.resolve())
        from dual_scene import DualScene
        world = DualScene(args.output)
        try:
            world.observe(world.output / 'observation')
            actual = {s: a.robot.get_root_pose().p.tolist() for s, a in world.arms.items()}
            extrinsic = world.cameras['overhead'].get_extrinsic_matrix()
            actual_angle = angle_below_horizontal(extrinsic[2, :3])
            checks['actual_base_positions'] = all(math.dist(actual[s], layout[s+'_base'][:3]) < 1e-6
                                                  for s in ('left', 'right'))
            checks['actual_camera_angle'] = math.isclose(actual_angle, 75, abs_tol=1e-4)
            checks['one_scene_two_articulations'] = len(world.scene.get_all_articulations()) == 2
            report.update(simulation_rendered=True, actual_base_positions=actual,
                          actual_base_distance_m=math.dist(actual['left'], actual['right']),
                          actual_camera_degrees_below_horizontal=actual_angle,
                          physics_steps=world.steps, simulation_time_s=world.steps*world.dt,
                          action_groups=world.group_count)
            (world.output / 'layout_verification.json').write_text(json.dumps(report, indent=2)+'\n')
        finally:
            world.close()
        if not all(checks.values()):
            raise ValueError(report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
