import copy
import importlib.util
import io
import json
import math
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from io_utils import ROOT, read_json
from fixtures.synthetic_history import observation, state, action, make_run
from history_diagnostics import PROFILES, DIAGNOSTIC_FIELDS, TransitionHistory, build_transition, decode, schema_path
from left_terminal import validate_state, command_plan
from prepare_history_replay import prepare
from report_history_experiment import report


def envelope(a):
    return {'action':a,'diagnostics':{k:'unknown; synthetic evidence only.' for k in DIAGNOSTIC_FIELDS}}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'logs').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='synthetic-history-test-')
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.obs=observation(self.folder,now=100)
        self.after=observation(self.folder,1,110)
        self.a=action()
    def transition(self, index=1, sent=True):
        plan=command_plan(self.a,self.obs['canonical_states']['left'])
        execution={'status':'EXECUTED' if sent else 'REJECTED_IK','hardware_commands_sent':int(sent),
                   'executed_action':{'arm':plan['arm'] if sent else None,'gripper':None},
                   'sdk_result':{'called':sent,'arm':0 if sent else None,'gripper':None}}
        return build_transition('episode',index,self.obs,self.obs,self.after,self.a,execution,
                                {'status':'PASS_IK' if sent else 'REJECTED_IK'},completed_at=111)
    def test_synthetic_valid_state_and_measured_delta(self):
        self.assertEqual(validate_state(self.obs),[])
        self.after['canonical_states']['left']['ee_pose']['xyz_m'][0]+=.01
        t=self.transition()
        self.assertAlmostEqual(t['actual_xyz_delta_m'][0],.01)
        self.assertAlmostEqual(t['translation_residual_m'][0],-.03)
        self.assertEqual(t['object_state']['holding'],'unknown')
    def test_rejection_noop_gripper_partial_and_wrap(self):
        t=self.transition(sent=False)
        self.assertIsNone(t['translation_residual_m'])
        self.assertEqual(t['executed_channels'],[])
        for status,commands,count in [('NOOP',{'arm':None,'gripper':None},0),
                                       ('EXECUTED',{'arm':None,'gripper':{'wire_target':420}},1)]:
            t=build_transition('episode',1,self.obs,self.obs,self.after,self.a,
                {'status':status,'executed_action':commands,'hardware_commands_sent':count,'sdk_result':{}},{},completed_at=111)
            self.assertIsNone(t['rotation_residual_rad'])
        self.after['canonical_states']['left']['ee_pose']['rpy_rad'][0]+=2*math.pi+.02
        t=self.transition()
        self.assertAlmostEqual(t['rotation_residual_rad'][0],.02)
        t['execution_status']='STOPPED'
        h=TransitionHistory('H5D0','episode');h.append(t)
        self.assertEqual(h.records[0]['executed_channels'],['arm'])
    def test_clip_dedupe_immutable_reset_future(self):
        h=TransitionHistory('H5D0','episode')
        for i in range(1,8):h.append(self.transition(i))
        h.append(self.transition(7))
        self.assertEqual([t['step'] for t in h.records],[3,4,5,6,7])
        obs=copy.deepcopy(self.after);obs['decision_ready_at']=120
        c=h.context(obs,read_json(schema_path('H5D0')),8)
        self.assertEqual(c,h.context(obs,read_json(schema_path('H5D0')),8))
        c['history'][0]['proposed_action']['translation_m'][0]=9
        self.assertEqual(h.records[0]['proposed_action'],self.a)
        with self.assertRaisesRegex(ValueError,'FUTURE'):h.context(obs,{},7)
        obs['decision_ready_at']=109
        with self.assertRaisesRegex(ValueError,'FUTURE'):h.context(obs,{},8)
        t=self.transition(8);h.append(t);t['proposed_action']['translation_m'][0]=99
        self.assertEqual(h.records[-1]['proposed_action']['translation_m'][0],.04)
        h.reset('new');self.assertEqual(list(h.records),[])
        with self.assertRaisesRegex(ValueError,'EPISODE'):h.append(self.transition())
    def test_decode_strict_and_values_preserved(self):
        self.a['translation_m']=[.123456789012345,-.01,0]
        d,a=decode(json.dumps(envelope(self.a)),'H5D1')
        self.assertEqual(a,self.a)
        malformed=[{},dict(envelope(self.a),reason='extra'),{'diagnostics':{},'action':self.a},
                   envelope(dict(self.a,reason='extra')),envelope(dict(self.a,gripper_opening=True))]
        x=envelope(self.a);x['diagnostics']['scene_assessment']='x'*601;malformed.append(x)
        for value in malformed:
            with self.subTest(value=value),self.assertRaises(ValueError):decode(json.dumps(value),'H5D1')
        with self.assertRaises(ValueError):decode('{"action":{},"action":{}}','H5D1')
    def test_fixed_replay_same_transitions_prompt_and_three_images(self):
        source=make_run(self.folder/'source')
        out=prepare(source,7,source/'profiles')
        images=[]
        for profile in PROFILES:
            c=read_json(out/profile/'model_input.json')
            self.assertEqual(c,read_json(out/profile/'decision/prompt.txt'))
            self.assertEqual(len(c['history']),int(profile[1]))
            self.assertEqual(c['history'][-1],read_json(source/'step-06/transition.json'))
            self.assertNotIn('previous',c)
            self.assertNotIn('diagnostics',c['history'][-1])
            self.assertNotIn('expected_visible_change',json.dumps(c['history']))
            self.assertEqual(c['task'],'  SYNTHETIC: put ball in basket  ')
            images.append(c['images_in_attachment_order'])
        self.assertTrue(all(x==images[0] and len(x)==3 for x in images))
        self.assertEqual(read_json(out/'H5D0/model_input.json')['history'][0]['execution_status'],'REJECTED_IK')
        # Deliberately corrupt future prefix; current-step result must never be loaded.
        (source/'step-07/transition.json').write_text('{"future":true}')
        prepare(source,7,source/'profiles-again')


class LoopTests(unittest.TestCase):
    def run_loop(self, profile, *, malformed=False, arm_error=False, readback_failure=False, gripper=False,
                 ik_fault=False, budget=False):
        spec=importlib.util.spec_from_file_location('measured_runner',ROOT/'scripts/run_left_history_diagnostics.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='synthetic-loop-')
        self.addCleanup(tmp.cleanup)
        folder=Path(tmp.name);run=folder/'run';motions=[];contexts=[];payloads=[]
        s=state();frame_count=0;grips=[]
        class Robot:
            def rm_get_rm_plus_state_info(self):return (0,copy.deepcopy(s['gripper_state']['raw']))
            def rm_algo_inverse_kinematics(self,params):
                return (-2 if ik_fault else (1 if len(contexts)==1 else 0),[0.]*6)
            def rm_movej_p(self,pose,*args):
                motions.append((copy.deepcopy(pose),args))
                s['ee_pose']['xyz_m']=[pose[0]-.02]+pose[1:3]
                s['ee_pose']['rpy_rad']=pose[3:]
                s['raw_sdk_state']['pose']=s['ee_pose']['xyz_m']+s['ee_pose']['rpy_rad']
                return 1 if arm_error else 0
        robot=Robot()
        class SDK:
            def __init__(self,*a):self.connected={'left':robot};self.sdk=types.SimpleNamespace(rm_inverse_kinematics_params_t=lambda **kw:kw)
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def connect(self,*a):return {'connected':True}
            def snapshot(self,*a):
                if readback_failure and motions:raise RuntimeError('SYNTHETIC_READBACK_FAILURE')
                s['timestamp']=time.time();return {'canonical':copy.deepcopy(s)}
        class Cameras:
            def __init__(self,*a):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def snapshot(self,path):
                nonlocal frame_count
                frame_count+=1
                o=observation(path,frame_count)
                return o['cameras'],[],{'capture_span_ms':0,'synthetic':True}
        class Grip:
            def __init__(self):self.last_result=None
            def set_gripper(self,arm,value):
                grips.append(value);self.last_result={'command_return':{'command':'hand_follow_pos','set_state':False}};return self.last_result
            def close(self):pass
        def transport(req,timeout):
            payload=json.loads(req.data);payloads.append(payload)
            c=payload['context'];contexts.append(copy.deepcopy(c))
            a=action()
            if gripper:a['gripper_opening']=.42
            if len(contexts)==7:a.update(done=True,translation_m=[0,0,0])
            raw='{}' if malformed else json.dumps(envelope(a) if profile.endswith('D1') else a)
            response={'return_code':0,'raw':raw,'events':'\n'.join(json.dumps(x) for x in [
                {'type':'turn.started'},{'type':'item.completed','item':{'type':'agent_message','text':raw}},
                {'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':20}}]),
                'latency_s':.01,'command':['codex','exec'],'stderr':'','mac_home':'/Users/synthetic'}
            class Response:
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def read(self,*a):return json.dumps(response).encode()
            return Response()
        original_new=runner.new_run
        def new(path):return original_new(run if path.name.startswith('left-measured-') else path)
        original_read=Path.read_text
        def read(path,*a,**kw):
            return 'synthetic-not-a-credential' if path.name=='codex_astra_bridge.token' else original_read(path,*a,**kw)
        argv=['runner','--live','--execute','--profile',profile,'--task','  unchanged task  ','--max-steps','7','--no-preview','--lock-path',str(ROOT/'logs/auto-pick.lock')]
        if budget:argv+=['--wall-budget-s','0.000001']
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules,{'camera_session':types.SimpleNamespace(CameraSession=Cameras),
                'realman_api2_readonly':types.SimpleNamespace(SDKReadOnly=SDK),
                'lab_gripper_adapter':types.SimpleNamespace(LabGripperAdapter=Grip)}))
            for context in (patch.object(runner,'new_run',new),patch.object(runner.signal,'signal'),
                patch.object(sys,'argv',argv),patch.object(sys,'stdin',io.StringIO('')),
                patch.object(Path,'read_text',read),patch('codex_astra_backend.urllib.request.urlopen',transport),redirect_stdout(io.StringIO())):
                stack.enter_context(context)
            code=runner.main()
        return code,run,contexts,motions,payloads,grips
    def test_all_profiles_actual_backend_pipeline_and_replay(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                code,run,contexts,motions,payloads,_=self.run_loop(profile)
                self.assertEqual(code,0)
                self.assertEqual(len(contexts),7)
                self.assertEqual(len(motions),5)
                self.assertEqual(contexts[0]['history'],[])
                self.assertEqual(contexts[1]['history'][-1]['execution_status'],'REJECTED_IK')
                self.assertEqual(contexts[1]['history'][-1]['executed_channels'],[])
                self.assertIsNone(contexts[1]['history'][-1]['translation_residual_m'])
                self.assertAlmostEqual(contexts[2]['history'][-1]['translation_residual_m'][0],-.02)
                self.assertEqual(len(contexts[-1]['history']),int(profile[1]))
                for n,c in enumerate(contexts,1):
                    step=run/('step-%02d'%n)
                    self.assertEqual(c,read_json(step/'model_input.json'))
                    self.assertEqual(c,read_json(step/'decision/prompt.txt'))
                    self.assertEqual(len(payloads[n-1]['images']),3)
                    self.assertEqual(read_json(step/'parsed_action.json'),action() if n<7 else dict(action(),done=True,translation_m=[0,0,0]))
                    self.assertEqual((step/'diagnostics.json').exists(),profile.endswith('D1'))
                    if n>1:self.assertEqual(c['history'][-1],read_json(run/('step-%02d'%(n-1))/'transition.json'))
                replay=prepare(run,7,run/'fixed',profiles=[profile])
                self.assertEqual(read_json(replay/profile/'model_input.json'),contexts[-1])
                result=report(run)
                self.assertEqual(result['summary']['model_calls'],7)
                self.assertEqual(result['independent_success'],'unknown')
                self.assertEqual(result['ik_rejections'],1)
                self.assertEqual(result['steps'][0]['token_usage'],{'input_tokens':100,'output_tokens':20})
                self.assertTrue(all(args==(1,0,0,1) for _,args in motions))
    def test_bad_output_no_executor(self):
        code,run,contexts,motions,_,_=self.run_loop('H5D1',malformed=True)
        self.assertEqual(code,1);self.assertEqual(motions,[])
        self.assertEqual(len(contexts),1)
        self.assertTrue((run/'step-01/decision/astra_raw.txt').exists())
        self.assertFalse((run/'step-01/execution_result.json').exists())
    def test_partial_failure_and_failed_readback_logged(self):
        for options in ({'arm_error':True},{'gripper':True},{'readback_failure':True}):
            with self.subTest(options=options):
                code,run,contexts,motions,_,grips=self.run_loop('H5D1',**options)
                self.assertEqual(code,1);self.assertEqual(len(motions),1)
                t=read_json(run/'step-02/transition.json')
                self.assertEqual(t['execution_status'],'STOPPED')
                self.assertEqual(t['hardware_commands_sent'],2 if grips else 1)
                self.assertEqual(t['object_state']['place_success'],'unknown')
                if options.get('readback_failure'):
                    self.assertIsNone(t['actual_after_pose']);self.assertIsNone(t['translation_residual_m'])
                else:self.assertIsNotNone(t['actual_after_pose'])
    def test_ik_fault_and_budget_never_dispatch(self):
        for options in ({'ik_fault':True},{'budget':True}):
            code,run,contexts,motions,_,_=self.run_loop('H5D0',**options)
            self.assertEqual(motions,[])
            summary=read_json(run/'summary.json')
            if options.get('budget'):
                self.assertEqual(summary['status'],'WALL_BUDGET_EXHAUSTED')
            else:
                self.assertEqual(code,1)
                self.assertEqual(read_json(run/'step-01/transition.json')['hardware_commands_sent'],0)

if __name__=='__main__':unittest.main()
