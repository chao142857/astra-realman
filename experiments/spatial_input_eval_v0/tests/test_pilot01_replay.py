import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'lab'))
import replay_pilot01 as replay
from spatial_eval.geometry import box


class Pilot01ReplayTests(unittest.TestCase):
    def test_oriented_containment_margin_is_signed_face_distance(self):
        q = [math.sqrt(.5), 0, 0, math.sqrt(.5)]
        region = box('region', [0, 0, 0], [2, 4, 6], q)
        held = box('held', [0, .2, 0], [1, 1, 1])
        self.assertAlmostEqual(replay.face_margins(region, held)['minimum_m'], .3)
        held['center_m'] = [0, .8, 0]
        self.assertAlmostEqual(replay.face_margins(region, held)['minimum_m'], -.3)

    def test_projection_clearance_is_not_euclidean_distance(self):
        held = box('held', [0, 0, 0], [1, 1, 1])
        obstacle = box('obstacle', [2, 2, 0], [1, 1, 1])
        result = replay.sat_threshold(held, [[0, 0, 0]], obstacle)
        self.assertAlmostEqual(result['noncollision_lower_m'], 1., places=9)
        self.assertNotAlmostEqual(result['noncollision_lower_m'], math.sqrt(2), places=3)
        self.assertGreaterEqual(result['collision_upper_m'], result['noncollision_lower_m'])

    def test_continuous_segment_finds_collision_between_waypoints(self):
        held = box('held', [-2, 0, 0], [.1, .1, .1])
        obstacle = box('obstacle', [0, 0, 0], [.01, 1, 1])
        result = replay.sat_threshold(held, [[-2, 0, 0], [2, 0, 0]], obstacle)
        self.assertTrue(result['collision_at_zero'])
        self.assertIsNone(result['noncollision_lower_m'])

    def test_calibrated_projection_front_and_behind_camera(self):
        cal = {'intrinsic': [[100, 0, 320], [0, 100, 240], [0, 0, 1]]}
        transform = [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]
        self.assertEqual(replay.project([2, 4, 5], cal, transform), (370., 340.))
        self.assertIsNone(replay.project([1, 2, 2], cal, transform))


if __name__ == '__main__':
    unittest.main()
