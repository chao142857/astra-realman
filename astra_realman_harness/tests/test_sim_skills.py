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
from sim_skills.contract import action_catalog, approval_request
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
        catalog = action_catalog(json.loads((ROOT/'config/sim_rm65_targets.json').read_text()))
        self.context['binding'].update(revision=catalog['targets']['revision'], primitive_index=0)
        self.context.update(action_catalog=catalog, approval_request=approval_request(catalog, 'S', 0))
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
    def test_runtime_m_s_send_same_complete_catalog_to_worker(self):
        sent = {'M': [], 'S': []}
        runtimes = {}
        targets = json.loads((ROOT/'config/sim_rm65_targets.json').read_text())
        for condition in ('M', 'S'):
            def worker(payload, stop, **kw):
                sent[condition].append(copy.deepcopy(payload))
                return self.worker(payload, stop, **kw)
            backend = Backend()
            backend.observe = lambda: copy.deepcopy(self.context['observation'])
            policy = LocalPolicy('/bin/false', self.root/condition/'workers', authorized=True,
                                 max_requests=4 if condition == 'M' else 1, worker=worker)
            runtime = PlacementRuntime(backend, targets, self.root/condition/'episode',
                                       condition=condition, policy=policy)
            self.assertEqual(runtime.run()['status'], 'PASS')
            runtimes[condition] = runtime
        self.assertEqual((len(sent['M']), len(sent['S'])), (4, 1))
        reference = sent['S'][0]['context']['action_catalog']
        self.assertEqual(reference['targets'], targets)
        self.assertEqual(reference['expanded_sequence'], runtimes['S'].backend.actions)
        self.assertEqual(reference['skill']['primitive_order'],
                         ['approach', 'release_pose', 'release', 'retract'])
        self.assertEqual(reference['units']['position'], 'metres')
        self.assertIn('wxyz', reference['units']['orientation'])
        self.assertEqual(sent['S'][0]['context']['approval_request']['scope'], 'complete_skill')
        self.assertEqual(sent['S'][0]['context']['approval_request']['primitive_indices'], [0,1,2,3])
        for index, payload in enumerate(sent['M']):
            context = payload['context']
            self.assertEqual(context['action_catalog'], reference)
            offer = context['approval_request']
            self.assertEqual(offer['scope'], 'one_primitive')
            self.assertEqual(offer['primitive_index'], index)
            self.assertEqual(offer['primitive'], runtimes['M'].backend.actions[index])
            self.assertNotIn('SECRET', json.dumps(context))
        self.assertEqual(runtimes['M'].backend.checks, runtimes['S'].backend.checks)
    def test_corrupt_or_stale_offer_rejected_before_worker(self):
        variants = []
        context = copy.deepcopy(self.context)
        context['action_catalog']['targets']['object_pose_gt'] = 'SECRET'
        variants.append(context)
        context = copy.deepcopy(self.context)
        context['action_catalog']['expanded_sequence'][0]['target'][0] += .1
        variants.append(context)
        context = copy.deepcopy(self.context)
        context['binding']['revision'] = 'stale'
        variants.append(context)
        context = copy.deepcopy(self.context)
        context['approval_request']['scope'] = 'one_primitive'
        variants.append(context)
        for index, context in enumerate(variants):
            with self.subTest(index=index):
                p = LocalPolicy('/bin/false', self.root, authorized=True, max_requests=1,
                                worker=lambda *a, **k: self.fail('worker reached'))
                with self.assertRaises(ValueError):p.decide(context, self.root/str(index))
                self.assertEqual(p.calls, 0)
    def test_truth_and_future_sentinels_excluded_from_final_payload(self):
        sentinels = {key: 'FORBIDDEN_SENTINEL' for key in
                     ('object_pose_gt','contact_truth','contact_latch','final_score','future_results')}
        self.context.update(sentinels)
        self.context['observation'].update(sentinels)
        self.context['observation']['state'].update(sentinels)
        self.context['previous_feedback'] = [dict(sentinels, ok=True, after=sentinels)]
        self.assertNotIn('FORBIDDEN_SENTINEL', json.dumps(input_payload(self.context)))
    def test_valid_stop_has_no_checks_actions_or_evaluation(self):
        backend = Backend()
        backend.observe = lambda: copy.deepcopy(self.context['observation'])
        backend.evaluate = lambda: self.fail('evaluator reached after stop')
        def worker(payload, stop, **kw):
            result = self.worker(payload, stop, **kw)
            result['raw'] = result['raw'].replace('continue', 'stop')
            result['events'] = result['events'].replace('continue', 'stop')
            return result
        p = LocalPolicy('/bin/false', self.root/'workers', authorized=True, max_requests=1, worker=worker)
        runtime = PlacementRuntime(backend, self.context['action_catalog']['targets'],
                                   self.root/'episode', condition='S', policy=p)
        result = runtime.run()
        self.assertEqual(result['error'], 'RuntimeError:POLICY_STOP')
        self.assertEqual(p.calls, 1)
        self.assertFalse(backend.actions)
        self.assertFalse(backend.checks)
        metadata = json.loads((self.root/'episode/request-01/metadata.json').read_text())
        self.assertEqual(metadata['status'], 'COMPLETE')
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
assert context==json.loads((root/'context.json').read_text())
assert context['approval_request']['scope']=='complete_skill'
assert context['approval_request']['primitive_indices']==[0,1,2,3]
catalog=context['action_catalog']
assert catalog['skill']['primitive_order']==['approach','release_pose','release','retract']
assert len(catalog['primitive_catalog'])==len(catalog['expanded_sequence'])==4
assert catalog['targets']['revision']==context['binding']['revision']
assert all(key in catalog['targets'] for key in ('frame','tool','pose_source'))
assert 'SECRET' not in json.dumps(context)
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
        transmitted = json.loads((run/'prompt.json').read_text())
        self.assertEqual(transmitted, input_payload(self.context)['context'])


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
