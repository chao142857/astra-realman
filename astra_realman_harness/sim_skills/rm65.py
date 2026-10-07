"""Thin adapter over a hash-checked copy of the user's existing PhysX scene."""
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path


ASSISTANCE = [
    'ENGINEERING_ORACLE: setup grasp uses simulator object geometry',
    'ENGINEERING_ORACLE: holding gates use bilateral contacts and object motion',
    'mplib/OMPL/FCL uses simulator collision geometry; payload is planning geometry only',
    'inherited finite bilateral contact preload .005 rad and .1 Nm drive limit',
    'no physical weld, mid-episode pose write, or object teleport',
]


class RM65Backend:
    source = 'SAPIEN_PHYSX'
    backend_id = 'rm65_sapien'
    decision_wait_mode = 'physics_paused'

    def __init__(self, assets, output, seed=2, video=False):
        import numpy as np
        assets = Path(assets).resolve()
        manifest = json.loads((assets / 'asset_manifest.json').read_text())
        for name, record in manifest['files'].items():
            if hashlib.sha256((assets / name).read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('ASSET_HASH_MISMATCH:' + name)
        sys.path.insert(0, str(assets / 'scripts'))
        module = importlib.import_module('rm65_scene')
        if Path(module.__file__).resolve() != assets / 'scripts/rm65_scene.py':
            raise ValueError('DIFFERENT_SCENE_ALREADY_IMPORTED')
        np.random.seed(seed)
        import mplib
        mplib.set_global_seed(seed)
        self.s = module.RM65Scene(output)
        self.calls = []
        self.holding_reference = None
        self.hold_min_z = None
        self.payload = False
        if video:
            self.s.start_video()

    @property
    def steps(self):
        return self.s.step

    @property
    def stopped(self):
        return self.s.stopped.is_set()

    @property
    def dt(self):
        return self.s.cfg['scene']['dt']

    def observe(self):
        r = self.s.observe(assembly=True)
        # Allowlist only current RGB and proprioception. No private scene/score paths.
        return {'observation_id': r['observation_id'], 'images': r['images'],
                'state': r['state'], 'captured_at': time.time(),
                'frame': 'sapien:world', 'pose_convention': 'pad centre xyz metres; Link6 wxyz',
                'observation_source': self.source, 'decision_wait_mode': self.decision_wait_mode}

    def setup_held(self):
        """Reinitialize then physically grasp, explicitly excluded from policy credit."""
        s = self.s
        x, y, _ = s.object_pose()[:3]
        for z in (.18, .08, .04):
            result = s.move_tcp([x, y, z, 0, 1, 0, 0])
            if not result['ok']:
                raise RuntimeError('SETUP_MOVE_FAILED:' + str(result))
        result = s.gripper(.45)
        if not result['ok']:
            raise RuntimeError('SETUP_GRIPPER_FAILED')
        s.tick(100)
        p = s.state()['actual_grasp_center_world']
        result = s.move_tcp([p[0], p[1], p[2] + .08, 0, 1, 0, 0])
        if not result['ok']:
            raise RuntimeError('SETUP_LIFT_FAILED')
        held = []
        for _ in range(300):
            s.tick(1)
            held.append(s.object_pose()[2] - s.initial_object[2])
        self.hold_min_z = min(held)
        if self.hold_min_z < .05 or not s.bilateral_pad_contact():
            raise RuntimeError('SETUP_NOT_RELIABLY_HELD')
        import numpy as np
        self.holding_reference = np.array(s.object_pose()[:3]) - s.state()['actual_grasp_center_world']
        s.set_planning_payload(True)
        self.payload = True
        return {'source': 'ENGINEERING_ORACLE', 'policy_grasp_credit': False,
                'method': 'recorded_reinitialization_then_physical_script', 'exact_clone': False,
                'hold_steps': 300, 'minimum_lift_m': self.hold_min_z, 'steps': s.step}

    def check(self, primitive):
        if self.s.stopped.is_set():
            return {'ok': False, 'reason': 'STOPPED', 'source': 'ENGINEERING_ORACLE'}
        if primitive['name'] != 'retract':
            import numpy as np
            offset = np.array(self.s.object_pose()[:3]) - self.s.state()['actual_grasp_center_world']
            held = (self.holding_reference is not None and self.s.bilateral_pad_contact()
                    and np.linalg.norm(offset - self.holding_reference) < .03)
            return {'ok': bool(held), 'reason': 'holding_contact_and_slip_check',
                    'source': 'ENGINEERING_ORACLE', 'physics_step': self.steps}
        return {'ok': True, 'reason': 'controller_not_stopped', 'source': 'controller'}

    def execute(self, primitive):
        if self.s.stopped.is_set():
            raise RuntimeError('STOP_NO_NEW_COMMANDS')
        if primitive['kind'] == 'move':
            result = self.s.move_tcp(primitive['target'])
        elif primitive['kind'] == 'set_gripper':
            result = self.s.gripper(primitive['opening'])
            result = {k: v for k, v in result.items() if k != 'contact_latch'}
            self.s.tick(300)
            self.s.set_planning_payload(False)
            self.payload = False
        else:
            raise ValueError('UNSUPPORTED_PRIMITIVE')
        self.calls.append({'primitive': primitive, 'result': result, 'physics_step': self.steps})
        return result

    def evaluate(self):
        import numpy as np
        positions = []
        for _ in range(300):
            self.s.tick(1)
            positions.append(self.s.object_pose()[:3])
        final = self.s.object_pose()
        error = float(np.linalg.norm(np.array(final[:2]) - self.s.cfg['scene']['place_zone_xy']))
        speed = float(np.linalg.norm(self.s.cube_body.get_linear_velocity()))
        spread = float(np.max(np.ptp(positions, axis=0)))
        released = self.s.state()['actual_pad_gap_m'] > .07
        ok = (error < .07 and abs(final[2] - .025) < .005 and speed < .01
              and spread < .002 and released and not self.s.stopped.is_set())
        return {'status': 'PASS' if ok else 'FAIL', 'source': 'SIMULATOR_TRUTH_EVALUATOR',
                'final_object_pose': final, 'xy_error_m': error, 'speed_m_s': speed,
                'position_range_m': spread, 'released': released, 'settle_steps': 300}

    def stop(self):
        self.s.stopped.set()

    def close(self):
        self.s.close()
