"""Independent semantic checks; analytical fixtures, no renderer or model requests."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
import pilot02_contract as contract
from pilot02_specs import specs, policies, answer, yaw
from spatial_eval.data import geometry
from spatial_eval.inputs import FRAME, validate_task
from spatial_eval.scoring import evaluate


def snapshot(spec):
    """Dictionary-only unit fixture, never represented as a SAPIEN capture."""
    truth=geometry(copy.deepcopy(spec['objects']),copy.deepcopy(spec['regions']),
                   copy.deepcopy(spec['obstacles']),source='SYNTHETIC_FIXTURE_TRUTH')
    rgb=[{'camera_id':f'fixture_{i}','path':f'/offline_fixture_{i}.png','sha256':'0'*64} for i in range(3)]
    return {'version':'astra.scene_snapshot.v0','scene_id':spec['scene_id'],
            'provenance':'SYNTHETIC_ANALYTICAL_TEST_NOT_SIMULATION','coordinate_system':copy.deepcopy(FRAME),
            'observations':{'rgb':rgb,'depth':[],
                'calibration':{r['camera_id']:{'intrinsic':None,'resolution':[640,480],
                    'pose_base_xyz_wxyz':None,'axes':'UNIT_TEST_NO_PHYSICAL_CALIBRATION'} for r in rgb},
                'robot_state':{'joint_names':[],'qpos_rad':[],'flange_pose_base_xyz_wxyz':None},
                'synchronization':{'simulation_step':None,'capture_span_s':0,
                    'timestamp_semantics':'dictionary unit test; no rendering','same_step':True}},
            'ground_truth':truth,'geometry':{'reconstruction':None,'oracle':copy.deepcopy(truth)},
            'task':[copy.deepcopy(spec['task'])]}


class Pilot02Tests(unittest.TestCase):
    def setUp(self):
        self.specs=specs()
        self.popen=patch('subprocess.Popen',side_effect=AssertionError('NO_MODEL_OR_PROCESS_DISPATCH_ALLOWED'))
        self.popen.start();self.addCleanup(self.popen.stop)

    def score(self,s,p):
        return contract.score(snapshot(s),s['task'],p,contract.policy_for(s))

    def family(self,name):
        return [s for s in self.specs if s['family'].startswith(name)]

    def test_design_is_deterministic_ten_predeclared_scenes(self):
        self.assertEqual(self.specs,specs())
        self.assertEqual([len(self.family(x)) for x in ('A_','B_','C_')],[6,2,2])
        self.assertEqual(len({s['scene_id'] for s in self.specs}),10)
        self.assertEqual({s['design']['nominal_per_side_gap_m'] for s in self.family('A_')},{.003,.010,.030})

    def test_all_private_witnesses_and_alternates_are_geometrically_valid(self):
        for s in self.specs:
            for p in [s['witness'],*s['alternate_witnesses']]:
                with self.subTest(scene=s['scene_id'],prediction=p):
                    self.assertEqual(self.score(s,p)['score'],1)

    def test_every_predeclared_negative_control_fails(self):
        for s in self.specs:
            for name,p in s['negative_controls'].items():
                with self.subTest(scene=s['scene_id'],control=name):
                    result=self.score(s,p)
                    self.assertEqual(result['score'],0)
                    self.assertTrue(result['error_types'])

    def test_opposite_scene_witnesses_fail_all_five_pairs(self):
        groups={}
        for s in self.specs:groups.setdefault(s['pair_id'],[]).append(s)
        self.assertEqual(len(groups),5)
        for identity,pair in groups.items():
            self.assertEqual(len(pair),2)
            for own,other in (pair,pair[::-1]):
                with self.subTest(pair=identity,scene=own['scene_id']):
                    self.assertEqual(self.score(own,other['witness'])['score'],0)

    def test_no_scene_blind_policy_passes_both_members_of_any_pair(self):
        groups={}
        for s in self.specs:groups.setdefault(s['pair_id'],[]).append(s)
        for identity,pair in groups.items():
            policy_sets=[policies(s) for s in pair]
            self.assertEqual(set(policy_sets[0]),set(policy_sets[1]))
            for name in policy_sets[0]:
                with self.subTest(pair=identity,policy=name):
                    successes=[self.score(s,p[name])['success'] for s,p in zip(pair,policy_sets)]
                    self.assertFalse(all(successes))

    def test_tight_3mm_pockets_have_positive_clearance_reserve(self):
        for s in self.family('A_'):
            if s['design']['nominal_per_side_gap_m']!=.003:continue
            self.assertTrue(self.score(s,s['witness'])['constraints']['placement_collision_free'])
            # Move far enough along either transverse axis to consume the 1 mm
            # reserve remaining after the predeclared 2 mm SAT clearance.
            for axis in (0,1):
                p=copy.deepcopy(s['witness']);p['position_m'][axis]+=.0011
                self.assertFalse(self.score(s,p)['constraints']['placement_collision_free'])

    def test_detours_cannot_escape_above_public_workspace(self):
        for s in self.family('B_'):
            high=policies(s)['high_overfly'];result=self.score(s,high)
            self.assertFalse(result['constraints']['path_in_workspace'])
            self.assertEqual(result['score'],0)
            self.assertFalse(self.score(s,s['negative_controls']['straight'])['constraints']['continuous_path_collision_free'])

    def test_free_yaw_accepts_sign_symmetry_half_turn_and_nearby_yaws(self):
        for s in self.family('C_'):
            angle=s['design']['private_slot_angle_deg']
            for a in (angle-1,angle,angle+1,angle+180):
                for sign in (-1,1):
                    p=answer(s['witness']['position_m'],[sign*v for v in yaw(a)])
                    self.assertTrue(self.score(s,p)['success'])

    def test_free_yaw_rejects_upside_down_even_if_box_geometry_identical(self):
        for s in self.family('C_'):
            # q_yaw * q_x(pi): same occupied cuboid, local +z points downward.
            q=s['witness']['quaternion_wxyz'];flipped=[0,q[0],q[3],0]
            p=answer(s['witness']['position_m'],flipped)
            base=evaluate(snapshot(s),s['task'],p)
            self.assertTrue(base['success'])
            result=self.score(s,p)
            self.assertFalse(result['constraints']['upright_local_positive_z'])
            self.assertAlmostEqual(result['upright_tilt_rad'],math.pi)

    def test_free_yaw_upright_rule_is_directional_and_numerically_finite(self):
        for s in self.family('C_'):
            p=copy.deepcopy(s['witness'])
            p['quaternion_wxyz']=[v*(1+1e-6) for v in p['quaternion_wxyz']]
            result=self.score(s,p)
            self.assertTrue(math.isfinite(result['upright_tilt_rad']))
            self.assertEqual(result['upright_tilt_rad'],0)

    def test_policy_cannot_prescribe_free_yaw_reference_quaternion(self):
        s=self.family('C_')[0];task=copy.deepcopy(s['task'])
        task['constraints']['required_quaternion_wxyz']=s['witness']['quaternion_wxyz']
        with self.assertRaisesRegex(ValueError,'FREE_YAW_WITH_TARGET_QUATERNION'):
            contract.build(snapshot(s),task,'RGB_MULTI_VIEW',contract.policy_for(s))
        with self.assertRaisesRegex(ValueError,'FREE_YAW_WITH_TARGET_QUATERNION'):
            contract.score(snapshot(s),task,s['witness'],contract.policy_for(s))

    def test_fixed_policy_mismatch_is_rejected_before_build_or_score(self):
        s=self.family('A_')[0]
        for key,value in [('required_quaternion_wxyz',yaw(90)),('orientation_tolerance_rad',.04)]:
            task=copy.deepcopy(s['task']);task['constraints'][key]=value
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError,'PILOT02_FIXED_RULE_MISMATCH'):
                    contract.build(snapshot(s),task,'RGB_MULTI_VIEW',contract.policy_for(s))
                with self.assertRaisesRegex(ValueError,'PILOT02_FIXED_RULE_MISMATCH'):
                    contract.score(snapshot(s),task,s['witness'],contract.policy_for(s))

    def test_task_id_mismatch_is_rejected_before_build_or_score(self):
        for s in (self.family('A_')[0],self.family('C_')[0]):
            task=copy.deepcopy(s['task']);task['task_id']='different_task'
            with self.assertRaisesRegex(ValueError,'PILOT02_TASK_POLICY_ID_MISMATCH'):
                contract.build(snapshot(s),task,'RGB_MULTI_VIEW',contract.policy_for(s))
            with self.assertRaisesRegex(ValueError,'PILOT02_TASK_POLICY_ID_MISMATCH'):
                contract.score(snapshot(s),task,s['witness'],contract.policy_for(s))

    def test_ac_contexts_differ_only_by_geometry_and_private_canaries_stay_out(self):
        for s in self.specs:
            snap=snapshot(s);snap['ground_truth']['PRIVATE_CANARY']='PRIVATE_GT_CANARY'
            snap['private_witness_canary']='PRIVATE_WITNESS_CANARY'
            policy=contract.policy_for(s)
            a,ma,ia=contract.build(snap,s['task'],'RGB_MULTI_VIEW',policy)
            c,mc,ic=contract.build(snap,s['task'],'RGB_ORACLE_3D',policy)
            c0=copy.deepcopy(c);c0['geometry']=None
            self.assertEqual(a,c0);self.assertEqual(ia,ic)
            self.assertEqual(ma['task_policy_sha256'],mc['task_policy_sha256'])
            self.assertEqual(ma['full_public_task_sha256'],mc['full_public_task_sha256'])
            self.assertEqual(ma['task_prompt_sha256'],mc['task_prompt_sha256'])
            self.assertNotIn('PRIVATE_',json.dumps(c))
            self.assertNotIn('ground_truth',c)
            self.assertNotIn('scene_id',c)
            self.assertNotIn('design',c)
            self.assertNotIn('witness',json.dumps(c))

    def test_pilot02_instruction_and_prompt_hash_include_public_policy(self):
        for s in self.specs:
            policy=contract.policy_for(s)
            context,manifest,_=contract.build(snapshot(s),s['task'],'RGB_MULTI_VIEW',policy)
            self.assertIn(contract.POLICY_INSTRUCTION,context['instruction'])
            prompt={k:context[k] for k in ('instruction','task','task_policy')}
            expected=hashlib.sha256(json.dumps(prompt,sort_keys=True).encode()).hexdigest()
            self.assertEqual(manifest['task_prompt_sha256'],expected)
            self.assertEqual(manifest['full_public_task_sha256'],expected)
            self.assertNotEqual(manifest['v0_base_task_prompt_sha256'],expected)

    def test_public_task_and_policy_are_identical_within_each_geometry_pair(self):
        groups={}
        for s in self.specs:groups.setdefault(s['pair_id'],[]).append(s)
        for identity,(a,b) in groups.items():
            with self.subTest(pair=identity):
                self.assertEqual(a['task'],b['task'])
                self.assertEqual(contract.policy_for(a),contract.policy_for(b))

    def test_v0_contract_retains_strict_fields_and_no_implicit_upright_rule(self):
        for s in self.specs:validate_task(s['task'])
        s=self.family('C_')[0];task=copy.deepcopy(s['task'])
        task['constraints']['upright']=True
        with self.assertRaisesRegex(ValueError,'SCHEMA_FIELDS'):validate_task(task)
        policy=contract.policy_for(s);policy['private_witness']=s['witness']
        with self.assertRaisesRegex(ValueError,'PILOT02_POLICY_CONTRACT'):contract.validate_policy(policy)


if __name__=='__main__':unittest.main()
