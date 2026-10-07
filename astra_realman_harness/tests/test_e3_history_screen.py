import copy
import importlib.abc
import json
import io
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class HardwareImportBlocker(importlib.abc.MetaPathFinder):
    forbidden=('left_executor','arm_stack','realman','Robotic_Arm','pyrealsense2',
               'exact_target_feasibility','left_live','sdk_session','bimanual_demo.executors')
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==n or fullname.startswith(n+'.') for n in self.forbidden):
            raise AssertionError('HARDWARE_IMPORT:'+fullname)

BLOCKER=HardwareImportBlocker()
sys.meta_path.insert(0,BLOCKER)
import e3_history_screen as e3
sys.meta_path.remove(BLOCKER)  # Import guard must not poison unrelated unittest discovery.

def event(n, status='EXECUTED', big=False):
    return {'version':1,'episode_id':'fixture','step':n,
        'proposed_action':{'translation_m':[.01,0.,-0.0],'frame':'work:World'},
        'executed_command':{'arm':None if status=='REJECTED_IK' else {'pose':[1,2,3]},'gripper':None},
        'hardware_commands_sent':0 if status=='REJECTED_IK' else 1,
        'execution_status':status,'execution_error':None,'sdk_result':{'arm':None if status=='REJECTED_IK' else 0},
        'readback_available':True,'readback_error':None,'after_validation_errors':[],
        'object_state':{'holding':'unknown','grasp_success':'unknown'},
        'timestamps':{'completed_at':n,'after':n},'actual_after_pose':{'xyz_m':[1,2,3],'units':'m'},
        'feasibility':{'status':status,'return_code':1 if status=='REJECTED_IK' else 0},
        'detail':('unique-'+str(n))* (500 if big else 1)}

class ProjectionTests(unittest.TestCase):
    def test_lossless_types_numbers_and_escaping(self):
        shared={'frame':'World','unknown':None,'numbers':[0,-0.0,False,True,2**80,1e-100,1.2345678901234567]}
        value=[shared,copy.deepcopy(shared),{'$e3':0,'$literal':[1]},[],{},'未知',None]
        self.assertEqual(e3.wire(value),e3.wire(e3.unpack(e3.pack(value))))

    def test_nonfinite_rejected(self):
        for value in (float('nan'),float('inf'),-float('inf')):
            with self.assertRaises(ValueError):e3.pack([value])

    def test_bad_reference(self):
        for ref in (-1,True,2):
            with self.assertRaises(ValueError):e3.unpack({'encoding':'e3-json-dictionary-v1','dictionary':[], 'data':{'$e3':ref}})
        with self.assertRaises(ValueError):e3.unpack({'encoding':'e3-json-dictionary-v1','dictionary':[{'$e3':0}],'data':{'$e3':0}})

    def test_t0_identical_t1_all_facts(self):
        history=[event(i) for i in range(1,6)]; before=copy.deepcopy(history)
        for condition in ('T0','T1'):
            value,audit,meta=e3.project(history,condition)
            self.assertTrue(all(row['retained'] for row in audit))
            self.assertEqual(value if condition=='T0' else e3.unpack(value),history)
        self.assertEqual(history,before)

    def test_common_protected_and_unknown_ik(self):
        h=[event(i,big=True) for i in range(1,6)];h[1]=event(2,'REJECTED_IK',big=True)
        protected,mapping=e3.protected_history(h)
        self.assertEqual(protected[1]['hardware_commands_sent'],0)
        self.assertEqual(protected[1]['executed_command']['arm'],None)
        self.assertEqual(protected[-1]['object_state']['holding'],'unknown')
        values=[]
        for c in ('T2','T3'):
            p,a,m=e3.project(h,c);values.append((p,a,m))
            if not m['fallback_reason']:
                self.assertLessEqual(e3.size(p),m['budget_bytes'])
                self.assertEqual(e3.unpack(p)['protected'],protected)
            self.assertTrue(any(r['source_pointer']=='/history/1/hardware_commands_sent' and r['retained'] for r in a))

    def test_shared_fallback(self):
        h=[event(1)]
        p2,_,m2=e3.project(h,'T2');p3,_,m3=e3.project(h,'T3')
        self.assertEqual(m2['fallback_reason'],'PROTECTED_ENVELOPE_EXCEEDS_50_PERCENT_BUDGET')
        self.assertEqual(p2,p3);self.assertEqual(e3.unpack(p2),h)
        self.assertEqual(m3['effective_condition'],'T1')

    def test_explicit_optin_before_any_call(self):
        with patch('subprocess.Popen',side_effect=AssertionError('NO MODEL')):
            with self.assertRaisesRegex(ValueError,'OPT_IN'):e3.infer(Path('/unused'))

    def test_medium_command_is_actual(self):
        from scripts.codex_astra_mac_bridge import command
        c=command(Path('/tmp/unused'),[Path('/tmp/a.png')]*3);e3.check_command(c)
        c[c.index('model_reasoning_effort="medium"')]='model_reasoning_effort="low"'
        with self.assertRaisesRegex(ValueError,'MEDIUM'):e3.check_command(c)


class RecordedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=ROOT/'logs/e3-source-20261007'
        if not cls.source.is_dir():raise unittest.SkipTest('Local archived sources not installed')
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='e3-offline-test-')
        cls.batch=Path(cls.tmp.name)/'batch'
        with patch('subprocess.Popen',side_effect=AssertionError('NO MODEL/PROCESS')), \
             patch.object(socket,'socket',side_effect=AssertionError('NO NETWORK/HARDWARE')):
            cls.manifest=e3.prepare(cls.source,cls.batch)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_all32_sources_images_and_medium(self):
        with patch('subprocess.Popen',side_effect=AssertionError('NO MODEL/PROCESS')), \
             patch.object(socket,'socket',side_effect=AssertionError('NO NETWORK/HARDWARE')):
            m=e3.validate_batch(self.batch)
        self.assertEqual(len(m['requests']),32)
        self.assertTrue(all(c['replay_equal'] and c['actual_effort']=='medium' for c in m['source_checks']))
        for row in m['requests']:
            folder=self.batch/row['request_id'];ctx=e3.read_json(folder/'model_input.json')
            original=e3.read_json(self.source/'runs'/row['checkpoint'][0]/f"step-{row['source_step']:02}"/'model_input.json')
            for key in original:
                if key!='history':self.assertEqual(ctx[key],original[key])
            if row['condition']=='T1':self.assertEqual(e3.wire(e3.unpack(ctx['history'])),e3.wire(original['history']))

    def test_future_transition_stopped(self):
        from history_diagnostics import TransitionHistory
        obs=e3.read_json(self.source/'runs/A/step-06/input_observation.json')
        obs['decision_ready_at']=e3.ready_time(obs)
        h=TransitionHistory('H5D1',obs['episode_id'])
        t=e3.read_json(self.source/'runs/A/step-05/transition.json');t['step']=6
        h.append(t)
        with self.assertRaisesRegex(ValueError,'FUTURE'):h.context(obs,{},6)

    def test_frozen_prompt_tamper(self):
        p=self.batch/'A06-T0/prompt.txt';original=p.read_bytes()
        try:
            p.write_bytes(original+b' ')
            with self.assertRaisesRegex(ValueError,'FROZEN_REQUEST_CHANGED'):e3.validate_batch(self.batch)
        finally:p.write_bytes(original)

    def test_no_calls_report(self):
        r=e3.report(self.batch)
        self.assertEqual(r['attempted'],0);self.assertEqual(r['hardware_commands_sent'],0)
        self.assertTrue(all(row['status']=='NOT_RUN' and row['input_tokens'] is None for row in r['rows']))

    def test_original_protocol_not_replaced(self):
        diagnostics={key:'unknown' for key in ('scene_assessment','previous_result_assessment','next_action_intent','expected_visible_change')}
        a={'action_type':'cartesian_delta','arm':'left','frame':'realman:left:work:World',
           'tool_frame':'realman:left:tool:Arm_Tip','translation_m':[0,0,0],
           'rotation_rpy_rad':[0,0,0],'gripper_opening':.4,'done':False}
        self.assertEqual(e3.decode(json.dumps({'diagnostics':diagnostics,'action':a}),'H5D1')[1],a)
        a['arm']='right'
        with self.assertRaises(ValueError):e3.decode(json.dumps({'diagnostics':diagnostics,'action':a}),'H5D1')

    def test_no_hardware_modules_loaded(self):
        self.assertFalse(any(n in sys.modules for n in HardwareImportBlocker.forbidden))

    def test_once_only_batch_no_retry_on_backend_failures(self):
        from scripts.codex_astra_mac_bridge import command
        calls=[]
        def fake(payload,stop):
            calls.append(payload)
            return {'command':command(Path('/tmp/fixture'),[Path('/tmp/image.png')]*3),
                'raw':'','events':'','stderr':'fixture failure','error':'MODEL_TIMEOUT',
                'return_code':1,'latency_s':.01,'local_log':'/tmp/fixture'}
        with patch('scripts.codex_astra_mac_bridge.infer',side_effect=fake), \
             patch('subprocess.Popen',side_effect=AssertionError('NO REAL MODEL')), \
             patch.object(socket,'socket',side_effect=AssertionError('NO NETWORK')), redirect_stdout(io.StringIO()):
            e3.infer(self.batch,authorize_32=True)
            with self.assertRaises(FileExistsError):e3.infer(self.batch,authorize_32=True)
        self.assertEqual(len(calls),32)
        self.assertTrue(all(len(p['images'])==3 for p in calls))
        r=e3.report(self.batch)
        self.assertEqual(r['attempted'],32)
        self.assertEqual(r['valid'],0)
        self.assertEqual(r['hardware_commands_sent'],0)
        # This test shares prepared data with the preceding checks; remove only
        # mocked outputs so later tests continue to see the original offline batch.
        import shutil
        for cp in e3.CHECKPOINTS:
            for c in e3.CONDITIONS:
                f=self.batch/(cp+'-'+c)
                for name in ('result.json','dispatch.json'): (f/name).unlink()
                shutil.rmtree(f/'decision')
        (self.batch/'inference.claim').unlink()
        e3.report(self.batch)

    def test_successful_stub_outputs_and_usage_without_executor(self):
        from scripts.codex_astra_mac_bridge import command
        tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='e3-success-test-')
        self.addCleanup(tmp.cleanup);batch=Path(tmp.name)/'batch';e3.prepare(self.source,batch)
        d={key:'unknown' for key in ('scene_assessment','previous_result_assessment','next_action_intent','expected_visible_change')}
        a={'action_type':'cartesian_delta','arm':'left','frame':'realman:left:work:World',
           'tool_frame':'realman:left:tool:Arm_Tip','translation_m':[0,0,0],
           'rotation_rpy_rad':[0,0,0],'gripper_opening':.4,'done':False}
        raw=json.dumps({'diagnostics':d,'action':a})
        events='\n'.join(map(json.dumps,[{'type':'turn.started'},
            {'type':'item.completed','item':{'type':'agent_message','text':raw}},
            {'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':20,'output_tokens':10}}]))
        fake={'command':command(Path('/tmp/stub'),[Path('/tmp/image.png')]*3),
            'raw':raw,'events':events,'stderr':'','error':None,'return_code':0,'latency_s':.01,'local_log':'/tmp/stub'}
        with patch('scripts.codex_astra_mac_bridge.infer',return_value=fake), \
             patch('subprocess.Popen',side_effect=AssertionError('NO REAL MODEL')), \
             patch.object(socket,'socket',side_effect=AssertionError('NO NETWORK')), redirect_stdout(io.StringIO()):
            e3.infer(batch,authorize_32=True)
        self.assertEqual(e3.report(batch)['valid'],32)
        self.assertEqual(e3.report(batch)['by_condition']['T1']['token_totals_known_only']['input_tokens'],800)
        self.assertEqual(e3.read_json(batch/'A06-T0/parsed_action.json'),a)
        self.assertFalse(any(batch.rglob('executed_action.json')))
        with patch('episode_archive.ARCHIVES',Path(tmp.name)/'archives'):
            archived=e3.archive(batch)
        self.assertEqual(archived['image_count'],24)
        self.assertTrue((Path(archived['path'])/'record/A06-T0/decision/astra_raw.txt').exists())

if __name__=='__main__':unittest.main()
