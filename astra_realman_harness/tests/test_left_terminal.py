import copy,json,math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json
from left_terminal import parse,command_plan,DryRunExecutor,camera_config,select_replay,model_input,validate_state,SCHEMA_PATH

class LeftInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.a=read_json(ROOT/'tests/left_opening_fixture.json')
        self.config=read_json(ROOT/'config/left_terminal.json')
        self.source=read_json(ROOT/'logs/auto-pick-20261002T134809Z-ed07af0a/step-01/observation.json')
        self.obs=select_replay(self.source,self.config,'  my task 原样  ',None)
    def test_fractional_opening_preserved(self):
        a=parse(json.dumps(self.a));p=command_plan(a,self.obs['canonical_states']['left'])
        self.assertEqual(p['gripper']['opening_target'],.42);self.assertEqual(p['gripper']['wire_target'],420)
        self.assertEqual(a,self.a)
    def test_invalid_opening_rejected(self):
        for v in ['open','close','hold',True,None,-.01,1.01,float('nan'),float('inf')]:
            with self.subTest(v=v),self.assertRaises(ValueError):parse(json.dumps(dict(self.a,gripper_opening=v)))
    def test_right_or_unknown_frame_rejected(self):
        for k,v in [('arm','right'),('frame','World'),('tool_frame','TCP'),('action_type','joint')]:
            with self.subTest(k=k),self.assertRaises(ValueError):parse(json.dumps(dict(self.a,**{k:v})))
    def test_no_clamp(self):
        a=dict(self.a,translation_m=[.12,-.2,.3],rotation_rpy_rad=[.1,.2,.3])
        self.assertEqual(parse(json.dumps(a)),a)
    def test_bad_vectors(self):
        for v in [[0,0],[0,True,0],[0,float('inf'),0],'xyz']:
            with self.subTest(v=v),self.assertRaises(ValueError):parse(json.dumps(dict(self.a,translation_m=v)))
    def test_duplicate_keys(self):
        with self.assertRaises(ValueError):parse('{"arm":"left","arm":"left"}')
    def test_model_input_task_exact_left_three_only(self):
        c=model_input(self.obs,read_json(SCHEMA_PATH))
        self.assertEqual(c['task'],'  my task 原样  ');self.assertEqual(set(c['robot_states']),{'left'})
        self.assertEqual(len(c['images_in_attachment_order']),3);self.assertIsNone(c['previous'])
        self.assertNotIn('348522072063',json.dumps(c));self.assertNotIn('192.168.1.18',json.dumps(c))
        self.assertNotIn('raw',c['robot_states']['left']['gripper'])
    def test_original_archive_unchanged(self):
        self.assertEqual(len(self.source['cameras']),4);self.assertIn('right',self.source['canonical_states'])
    def test_hash_failure(self):
        self.obs['cameras'][0]['sha256']='bad'
        with self.assertRaises(ValueError):model_input(self.obs,read_json(SCHEMA_PATH))
    def test_unconfirmed_mapping_blocks_live(self):
        unconfirmed=copy.deepcopy(self.config)
        unconfirmed['cameras'][0]['role_confirmed']=False
        with self.assertRaises(ValueError):camera_config(unconfirmed,live=True)
    def test_baseline_state_valid_for_offline_replay(self):
        self.assertEqual(validate_state(self.obs),[])
    def test_controller_error_rejected(self):
        self.obs['canonical_states']['left']['system_error']['codes']=[4099]
        self.assertIn('ROBOT_ERROR_OR_UNKNOWN',validate_state(self.obs))
    def test_frame_change_rejected(self):
        self.obs['canonical_states']['left']['raw_work_frame']['pose'][0]=1
        self.assertIn('WORK_FRAME_CHANGED',validate_state(self.obs))
    def test_stale_replay_not_valid_live(self):
        self.assertIn('STALE_OBSERVATION',validate_state(self.obs,live=True))
    def test_dry_executor_never_dispatches(self):
        x=DryRunExecutor().execute({'arm':{'function':'danger'},'gripper':{'opening_target':0}})
        self.assertEqual(x['hardware_commands_sent'],0);self.assertFalse(x['sdk_result']['called'])
        self.assertEqual(x['executed_action'],{'arm':None,'gripper':None})
    def test_done_has_no_actuation(self):
        a=dict(self.a,translation_m=[0,0,0],done=True)
        self.assertEqual(command_plan(parse(json.dumps(a)),self.obs['canonical_states']['left']),{'arm':None,'gripper':None,'terminal':True})
    def test_done_with_arm_motion_rejected(self):
        with self.assertRaises(ValueError):parse(json.dumps(dict(self.a,done=True)))
    def test_satisfied_gripper_not_resent(self):
        s=copy.deepcopy(self.obs['canonical_states']['left']);s['gripper_state']['position']=420;s['gripper_state']['raw']['speed']=[0]
        self.assertIsNone(command_plan(self.a,s)['gripper'])
    def test_no_motion_imports_or_dispatch(self):
        import ast
        paths=[ROOT/'left_terminal.py',ROOT/'left_preview.py',ROOT/'scripts/run_left_terminal.py']
        forbidden={'rm_movej_p','rm_movel','rm_movej','set_gripper','set_gripper_position','rm_set_hand_follow_pos'}
        for path in paths:
            tree=ast.parse(path.read_text())
            calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
            self.assertFalse(forbidden.intersection(calls),path.name)

    def test_stop_terminates_owned_model_process(self):
        import tempfile,threading
        from unittest.mock import patch
        from left_terminal import call_astra
        class Proc:
            returncode=None
            terminated=False
            def poll(self):return self.returncode
            def terminate(self):self.terminated=True;self.returncode=-15
            def wait(self,timeout=None):return self.returncode
        proc=Proc();stop=threading.Event();stop.set()
        context=model_input(self.obs,read_json(SCHEMA_PATH))
        with tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='left-unit-') as d:
            with patch('left_terminal.subprocess.Popen',return_value=proc),self.assertRaisesRegex(RuntimeError,'HUMAN_STOP'):
                call_astra(context,Path(d),read_json(ROOT/'config/decision_backend.json'),'gpt-6-astra',stop,lambda *_:None)
            self.assertTrue(proc.terminated)
            self.assertEqual(read_json(Path(d)/'backend_result.json')['status'],'FAILED')
    def test_preview_readonly(self):
        import urllib.request,urllib.error
        from left_preview import Preview
        with Preview(self.config['cameras'],0) as preview:
            preview.update(self.obs)
            url='http://127.0.0.1:'+str(preview.server.server_port)
            self.assertIn(b'READ ONLY',urllib.request.urlopen(url).read())
            self.assertTrue(urllib.request.urlopen(url+'/view/0').read().startswith(b'\x89PNG'))
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(url+'/execute',data=b'{}'))
            self.assertEqual(e.exception.code,501)

if __name__=='__main__':unittest.main()
