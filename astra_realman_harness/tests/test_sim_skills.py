"""Safety/equivalence/geometry tests; fake backend tests are not physics evidence."""
import copy
import json
import math
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sim_skills.runtime import PlacementRuntime, ScriptedPolicy
from sim_skills.poses import pad_pose_to_tool_rpy
from sim_skills.model import LocalPolicy, input_payload
from bimanual_demo.runtime import Runtime
from bimanual_demo.evidence import SyntheticObserver, PNG
from bimanual_demo.executors import MockArmExecutor
from scripts.codex_astra_mac_bridge import command, infer
from sim_skills.projection import pack_history, unpack_history, history_projection, image_projection
ROOT = Path(__file__).resolve().parents[1]


class Backend:
    backend_id = 'rm65_sapien'
    source = 'TEST_DOUBLE'
    steps = 0
    dt = .004
    decision_wait_mode = 'physics_paused'
    def __init__(self):
        self.actions = []
        self.checks = []
        self.stopped = False
        self.fail_check = False
        self.fail_execute = False
    def observe(self):
        return {'observation_id': str(self.steps), 'state': {}, 'images': {}}
    def check(self, p):
        self.checks.append(copy.deepcopy(p))
        return {'ok': not self.fail_check and not self.stopped}
    def execute(self, p):
        self.actions.append(copy.deepcopy(p)); self.steps += 1
        return {'ok': not self.fail_execute}
    def evaluate(self):return {'status': 'PASS', 'source': 'TEST_ONLY'}
    def stop(self):self.stopped = True


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.targets = json.loads((ROOT / 'config/sim_rm65_targets.json').read_text())
    def tearDown(self):self.tmp.cleanup()
    def runtime(self, backend=None, policy=None, condition='S', **kw):
        return PlacementRuntime(backend or Backend(), self.targets, self.root / condition,
                                condition=condition, policy=policy or ScriptedPolicy(), **kw)
    def test_same_commands_checks_and_different_request_boundaries(self):
        m, s = self.runtime(condition='M'), self.runtime(condition='S')
        mr, sr = m.run(), s.run()
        self.assertEqual(m.backend.actions, s.backend.actions)
        self.assertEqual(m.backend.checks, s.backend.checks)
        self.assertEqual((mr['model_attempts'], sr['model_attempts']), (4, 1))
        self.assertEqual(mr['real_model_calls'] + sr['real_model_calls'], 0)
    def test_unknown_check_stops_before_first_action(self):
        b = Backend(); b.fail_check = True
        self.assertEqual(self.runtime(b).run()['status'], 'FAIL')
        self.assertFalse(b.actions)
    def test_backend_failure_stops_without_retry(self):
        b = Backend(); b.fail_execute = True
        self.assertEqual(self.runtime(b).run()['status'], 'FAIL')
        self.assertEqual(len(b.actions), 1)
    def test_stop_during_decision_discards_result(self):
        r = self.runtime()
        def decide(c, _, **kw):r.stop();return {'binding': c['binding'], 'action': 'continue'}
        r.policy.decide = decide
        self.assertIn('STOP', r.run()['error']); self.assertFalse(r.backend.actions)
    def test_late_result_cannot_dispatch(self):
        now = [0.]
        r = self.runtime(clock=lambda: now[0], budget_s=1)
        def decide(c, _, **kw):now[0] = 2.;return {'binding': c['binding'], 'action': 'continue'}
        r.policy.decide = decide
        self.assertIn('BUDGET', r.run()['error']); self.assertFalse(r.backend.actions)
        self.assertTrue(any(x['kind'] == 'MODEL_RESULT' for x in r.rows))
    def test_budget_expiry_between_primitives(self):
        now = [0.]; b = Backend(); original = b.execute
        def execute(p):now[0] = 2.;return original(p)
        b.execute = execute
        r = self.runtime(b, clock=lambda: now[0], budget_s=1)
        self.assertIn('BUDGET', r.run()['error']); self.assertEqual(len(b.actions), 1)
    def test_stale_binding_rejected(self):
        p = ScriptedPolicy(); p.decide = lambda *a, **k: {'binding': {}, 'action': 'continue'}
        r = self.runtime(policy=p)
        self.assertIn('STALE', r.run()['error']); self.assertFalse(r.backend.actions)
    def test_failed_attempt_consumes_budget_and_does_not_retry(self):
        p = ScriptedPolicy()
        def fail(*a, **kw):raise RuntimeError('REQUEST_FAILED')
        p.decide = fail
        r = self.runtime(policy=p)
        self.assertEqual(r.run()['model_attempts'], 1)
        self.assertFalse(r.backend.actions)
    def test_no_second_run_or_implicit_recovery(self):
        r = self.runtime(); r.run()
        with self.assertRaisesRegex(RuntimeError, 'ALREADY_CONSUMED'):r.run()
    def test_target_backend_rejected_before_dispatch(self):
        self.targets['backend'] = 'realman'
        with self.assertRaisesRegex(ValueError, 'MISMATCH'):self.runtime()


class PoseTests(unittest.TestCase):
    def test_dynamic_pad_offset_and_work_transform(self):
        # 90 deg about Z rotates a local +X pad offset into world +Y.
        out = pad_pose_to_tool_rpy([1, 2, 3, math.sqrt(.5), 0, 0, math.sqrt(.5)],
                                   [.2, 0, 0], [.1, 0, 0], [10, 0, 0, 0, 0, 0])
        for actual, expected in zip(out, [11, 1.9, 3, 0, 0, math.pi/2]):
            self.assertAlmostEqual(actual, expected)
    def test_wrong_array_semantics_rejected(self):
        for pose in ([0]*6, [0]*7, [0, 0, 0, float('nan'), 0, 0, 1]):
            with self.assertRaises(ValueError):pad_pose_to_tool_rpy(pose, [0]*3, [0]*3, [0]*6)


class InjectionTests(unittest.TestCase):
    def test_explicit_dependencies_bypass_factories(self):
        with tempfile.TemporaryDirectory() as d:
            site = json.loads((ROOT/'config/bimanual_synthetic.json').read_text())
            arms = {arm: MockArmExecutor(arm, site) for arm in ('left','right')}
            observer = SyntheticObserver(d, arms, {}, site['revision'])
            with patch('bimanual_demo.runtime.make_arms', side_effect=AssertionError('factory reached')):
                runtime = Runtime(site, d, {}, {}, arms=arms, observer=observer)
                self.assertIs(runtime.arms, arms); self.assertIs(runtime.observer, observer)
    def test_simulate_never_falls_back_to_mock_or_real_factory(self):
        with tempfile.TemporaryDirectory() as d:
            site = json.loads((ROOT/'config/bimanual_synthetic.json').read_text())
            with patch('bimanual_demo.runtime.make_arms', side_effect=AssertionError('factory reached')):
                with self.assertRaisesRegex(Exception, 'SIMULATION_DEPENDENCIES_REQUIRED'):
                    Runtime(site, d, {}, {}, mode='simulate')
    def test_sim_entry_imports_no_hardware_modules(self):
        code = '''
import builtins, runpy, sys
original=builtins.__import__
def guarded(name,*a,**k):
 if name.split('.')[0] in {'arm_stack','realman_state','lab_gripper_adapter','supervised_live','Robotic_Arm'}:
  raise AssertionError('HARDWARE_IMPORT:'+name)
 return original(name,*a,**k)
builtins.__import__=guarded
sys.argv=['run_sim_placement.py','--help']
runpy.run_path(sys.argv[0],run_name='__main__')
'''
        # Explicit import guard is a tripwire, not a claim of physical acceptance.
        code = code.replace("'run_sim_placement.py'", repr(str(ROOT/'scripts/run_sim_placement.py')))
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        p = self.root/'safe.png'; p.write_bytes(PNG)
        self.context = {'binding': {'request': 1, 'condition': 'S'}, 'task': 'place', 'target_id': 'fixed',
            'allowed_actions': ['continue','stop'], 'previous_feedback': [],
            'observation': {'observation_id':'o1', 'state': {}, 'captured_at':1., 'frame':'sapien:world',
                'pose_convention':'xyz wxyz', 'observation_source':'SAPIEN_PHYSX',
                'decision_wait_mode':'physics_paused', 'images': {n:str(p) for n in ('assembly','fixed','wrist')},
                'object_pose_gt':[999], 'reward':1, 'future_trajectory':'SECRET'}}
    def tearDown(self):self.tmp.cleanup()
    def worker(self, payload, stop, **kw):
        raw = json.dumps({'binding': payload['context']['binding'], 'action':'continue'})
        events = [{'type':'turn.started'}, {'type':'item.completed','item':{'type':'agent_message','text':raw}},
                  {'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2}}]
        return {'raw':raw,'events':'\n'.join(map(json.dumps,events)),'return_code':0,'error':None,
                'command':command(self.root, [], kw['executable'])}
    def test_projection_excludes_truth_and_paths(self):
        self.context['observation']['state']['hidden_object_gt'] = 'SECRET'
        self.context['previous_feedback'] = [{'ok':True,'contact_latch':'SECRET','after':{'reward':999}}]
        payload = input_payload(self.context); raw = json.dumps(payload['context'])
        for marker in ('SECRET','999','object_pose_gt','reward',str(self.root)):
            self.assertNotIn(marker, raw)
        self.assertEqual([r['camera'] for r in payload['context']['images_in_attachment_order']], ['assembly','fixed','wrist'])
    def test_authorization_and_request_cap(self):
        with self.assertRaises(ValueError):LocalPolicy('/bin/false',self.root)
        p = LocalPolicy('/bin/false', self.root, authorized=True,max_requests=1,worker=self.worker)
        p.decide(self.context, self.root/'request')
        with self.assertRaisesRegex(RuntimeError,'REQUEST_LIMIT'):p.decide(self.context,self.root/'again')
        self.assertEqual(json.loads((self.root/'request/metadata.json').read_text())['usage']['input_tokens'],10)
    def test_tool_result_is_rejected_without_repair(self):
        def worker(*a,**kw):
            r=self.worker(*a,**kw);r['events']+='\n'+json.dumps({'type':'item.completed','item':{'type':'command_execution'}});return r
        p=LocalPolicy('/bin/false', self.root, authorized=True,max_requests=1,worker=worker)
        with self.assertRaises(Exception):p.decide(self.context,self.root/'request')
        self.assertEqual(p.calls,1)
    def test_infer_cancelled_before_subprocess(self):
        event=threading.Event();event.set()
        with patch('scripts.codex_astra_mac_bridge.subprocess.Popen',side_effect=AssertionError('spawn')):
            with self.assertRaisesRegex(RuntimeError,'CANCELLED'):infer({},event,run_root=self.root)
    def test_command_uses_medium_and_input_only(self):
        cmd=command(self.root,[self.root/'input_only/image-0.png'],'/bin/codex')
        self.assertIn('model_reasoning_effort="medium"',cmd)
        self.assertIn('--ignore-user-config',cmd)
        self.assertEqual(cmd[cmd.index('--cd')+1],str(self.root/'input_only'))
    def test_worker_spawns_only_cli_stub_and_retains_artifacts(self):
        stub=self.root/'cli-stub'
        stub.write_text('#!'+sys.executable+'\n'+'''import sys,json
from pathlib import Path
a=sys.argv; context=json.loads(sys.stdin.read()); root=Path.cwd()
assert root.name=='input_only'
assert sorted(p.name for p in root.iterdir())==['context.json','image-0.png','image-1.png','image-2.png']
assert 'model_reasoning_effort="medium"' in a
raw=json.dumps({'binding':context['binding'],'action':'continue'})
Path(a[a.index('--output-last-message')+1]).write_text(raw)
for e in [{'type':'turn.started'},{'type':'item.completed','item':{'type':'agent_message','text':raw}},{'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}]:print(json.dumps(e))
''')
        stub.chmod(0o700)
        p=LocalPolicy(stub,self.root/'workers',authorized=True,max_requests=1)
        result=p.decide(self.context,self.root/'request',timeout_s=5)
        self.assertEqual(result['action'],'continue')
        response=json.loads((self.root/'request/response.json').read_text())
        run=Path(response['local_log'])
        self.assertTrue((run/'attachments.json').exists())
        self.assertEqual(len(list((run/'input_only').glob('*.png'))),3)


class ProjectionTests(unittest.TestCase):
    def test_lossless_preserves_numbers_units_null_negation_and_order(self):
        history=[{'pose_m':[.0000315,-0.,None], 'holding':False, 'error':'not executed',
                  'unit':'rad','nested':{'array':['value','object',{'x':2}]}}, {'pose_m':[],'holding':None}]
        self.assertEqual(json.dumps(unpack_history(pack_history(history))),json.dumps(history))
        _,meta=history_projection(history,mode='lossless')
        self.assertTrue(meta['round_trip_exact']);self.assertEqual(meta['deleted_pointers'],[])
    def test_budget_failure_preserves_raw_and_marks_ineligible(self):
        raw=[{'important':'not held','value':None}]
        selected,meta=history_projection(raw,mode='lossless',budget_bytes=1)
        self.assertEqual(selected,raw);self.assertFalse(meta['eligible'])
    def test_real_png_derivative_hash_and_order(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'parent.png';Image.new('RGB',(20,10),(255,0,0)).save(p)
            records,meta=image_projection({'wrist':p,'fixed':p},Path(d)/'out',cameras=['fixed','wrist'],resize=[10,5])
            self.assertEqual([r['camera'] for r in records],['fixed','wrist'])
            self.assertEqual(records[0]['size'],[10,5])
            self.assertNotEqual(records[0]['sha256'],records[0]['parent_sha256'])
    def test_gt_roi_and_unknown_camera_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'ONLINE_ROI'):
                image_projection({'wrist':'unused'},Path(d)/'out',cameras=['wrist'],roi={'source':'simulator_truth'})
            with self.assertRaisesRegex(ValueError,'CAMERA_SELECTION'):
                image_projection({},Path(d)/'out',cameras=['future'])


if __name__ == '__main__':unittest.main()
