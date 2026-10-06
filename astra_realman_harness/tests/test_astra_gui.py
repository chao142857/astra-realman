"""GUI/control boundary tests, all synthetic; never import a robot SDK or model client."""
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json,write_json,new_run
from astra_gui import Console,CameraHub,action_summary,step_evidence,make_server
from camera_session import CameraSession
from experiment_launch import validate,runner_args,ALL_PROFILES
from fixtures.synthetic_history import action


class EvidenceAndLaunch(unittest.TestCase):
    def setUp(self):
        (ROOT/'logs').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs',prefix='synthetic-gui-test-');self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
    def test_action_mm_degrees_opening_and_done(self):
        a=action();a.update(translation_m=[.012,-.003,0],rotation_rpy_rad=[0,0,3.141592653589793/2],gripper_opening=.42)
        result=action_summary(a)
        self.assertEqual(result['translation_mm'],[12,-3,0]);self.assertEqual(result['rotation_deg'],[0,0,90])
        self.assertEqual(result['opening_percent'],42)
        a.update(done=True);self.assertIsNone(action_summary(a)['opening_percent'])
    def test_success_not_inferred_and_rejection_residual_not_reused(self):
        step=self.folder/'step-01';step.mkdir()
        write_json(step/'parsed_action.json',action())
        write_json(step/'execution_result.json',{'status':'REJECTED_IK','hardware_commands_sent':0,'executed_action':{'arm':None,'gripper':None}})
        write_json(step/'feasibility.json',{'status':'REJECTED_IK','reason':'endpoint unavailable'})
        write_json(step/'pose-telemetry.json',{'translation_residual_m':[99,99,99]})
        result=step_evidence(step)
        self.assertIsNone(result['translation_residual_mm'])
        self.assertEqual(result['failure_reason'],'endpoint unavailable')
        self.assertIn('零下发',result['result_text'])
    def test_profiles_preserve_arguments_and_no_shell_interpolation(self):
        task='把球放入框； $(touch /tmp/SHOULD_NOT_EXIST) "原样"'
        for profile in ALL_PROFILES:
            argv=runner_args({'profile':profile,'task':task,'max_steps':7,'mode':'execute'},no_preview=True)
            self.assertEqual(argv[argv.index('--task')+1],task)
            self.assertEqual(argv[argv.index('--max-steps')+1],'7')
            self.assertIn('--execute',argv);self.assertIn('--no-preview',argv)
            self.assertEqual('--profile' in argv,profile.startswith('H'))
        for invalid in [{'profile':'bad'},{'max_steps':True},{'max_steps':0},{'wall_budget_s':float('nan')},{'unexpected':1}]:
            with self.assertRaises(ValueError):validate(dict(task='task',**invalid))
    def test_all_shell_launchers_parse_and_flags_override(self):
        for path in (ROOT/'launch').glob('*.sh'):
            subprocess.run(['bash','-n',str(path)],check=True,capture_output=True)
        env=dict(os.environ,ASTRA_PYTHON=sys.executable,ASTRA_MAX_STEPS='3',ASTRA_TASK='environment task')
        result=subprocess.run(['bash',str(ROOT/'launch/H1D1.sh'),'--print-command','--max-steps','8','--task','literal $()'],env=env,capture_output=True,text=True,check=True)
        import shlex
        command=shlex.split(result.stdout)
        self.assertEqual(command[command.index('--profile')+1],'H1D1')
        self.assertEqual(command[command.index('--max-steps')+1],'8')
        self.assertEqual(command[command.index('--task')+1],'literal $()')
        clean={k:v for k,v in os.environ.items() if not k.startswith('ASTRA_')}
        clean['ASTRA_PYTHON']=sys.executable
        for entry,flags in [('launch/H5D1.sh',['--print-command','--task','task']),
                            ('run_official_astra_history_diagnostics.sh',['--print-command'])]:
            result=subprocess.run(['/bin/bash',str(ROOT/entry)]+flags,env=clean,capture_output=True,text=True,check=True)
            self.assertIn('--live',result.stdout)
    def test_shared_subset_excludes_missing_fourth_without_restart(self):
        configs=[{'serial':str(i)} for i in range(4)]
        session=CameraSession(configs,snapshot_timeout=0)
        session.errors={'3':'SDK_SERIAL_NOT_FOUND'}
        for i in range(3):
            session.latest[str(i)]={'serial':str(i),'sequence':1,'host_received_monotonic':time.monotonic(),
                'host_received_at':time.time(),'device_timestamp_domain':'timestamp_domain.system_time',
                'device_timestamp_ms':time.time()*1000,'shape':[1,1,3],'_pixels':b'abc','_stride':3}
        with patch('observation.png_rgb',return_value='synthetic-hash'):
            images,failures,metrics=session.snapshot(self.folder,configs=configs[:3])
        self.assertEqual(len(images),3);self.assertEqual(failures,[])
        self.assertEqual(metrics['expected_serials'],['0','1','2'])
        self.assertEqual(session.starts,{})
        with self.assertRaises(ValueError):session.snapshot(self.folder,configs=[{'serial':'not-known'}])
    def test_demo_camera_zero_through_four_and_preview_only(self):
        console=Console(demo=True,cameras_only=True)
        self.addCleanup(lambda:shutil.rmtree(console.session));self.addCleanup(console.close)
        for n in range(5):
            console.camera.demo_count=n
            self.assertEqual(sum(c['available'] for c in console.camera.status()),n)
            if n:self.assertIn(b'SYNTHETIC',console.camera.image(0)[0])
        with self.assertRaisesRegex(ValueError,'CAMERAS_ONLY'):console.start({'task':'task'})
    def test_partial_cameras_preview_but_model_requirements_unchanged(self):
        console=Console(demo=False)
        self.addCleanup(lambda:shutil.rmtree(console.session));self.addCleanup(console.close)
        statuses=[{'available':True}]*3+[{'available':False}]
        with patch.object(console.camera,'status',return_value=statuses),patch('astra_gui.subprocess.Popen') as proc,patch('astra_gui.threading.Thread'),patch('launch_provenance.snapshot',return_value={}):
            with self.assertRaisesRegex(ValueError,'4'):console.start({'task':'task','profile':'legacy4'})
            console.url='http://127.0.0.1:1';console.start({'task':'task','profile':'H5D0'})
            self.assertTrue(console.active);self.assertEqual(proc.call_count,1)
            self.assertNotIn('shell',proc.call_args.kwargs)
            self.assertTrue(proc.call_args.kwargs['env']['ASTRA_CAMERA_HUB_TOKEN'])
            proc.return_value.poll.return_value=None
            console.stop();proc.return_value.send_signal.assert_called_once()
            proc.return_value.kill.assert_not_called();proc.return_value.terminate.assert_not_called()
            console.active=False;console.process=None
    def test_demo_duplicate_start_and_independent_labels(self):
        console=Console(demo=True)
        self.addCleanup(lambda:shutil.rmtree(console.session));self.addCleanup(console.close)
        with patch('astra_gui.threading.Thread'):
            console.start({'task':'task','profile':'H5D1'})
            with self.assertRaisesRegex(ValueError,'已有'):console.start({'task':'task'})
        with patch.object(console.demo_stop,'wait',return_value=False):console._demo_run()
        run=console.current_run;self.addCleanup(lambda:shutil.rmtree(run))
        state=console.state();self.assertEqual(state['summary']['model_calls'],0)
        self.assertEqual(state['summary']['hardware_commands_sent'],0)
        self.assertEqual(state['independent_success'],'unknown')
        self.assertEqual(state['steps'][1]['actual_xyz_delta_mm'],[0,0,0])
        self.assertEqual(state['steps'][1]['status'],'REJECTED_IK')
        with self.assertRaises(ValueError):console.annotate({'run':run.name,'result':'success'})
        console.annotate({'run':run.name,'result':'fail','observer':'SYNTHETIC TEST','evidence':'synthetic: no real robot','reason':'GUI annotation test'})
        self.assertIs(console.state()['independent_success'],False)
        self.assertTrue(read_json(run/'independent_observation.json')['synthetic'])
        self.assertEqual(len(list(run.glob('independent-observation-*.json'))),1)
        self.assertNotIn('labels',read_json(run/'step-01/input_observation.json'))
        from scripts.report_history_experiment import report
        self.assertTrue(report(run)['synthetic'])
        self.assertEqual(console.state(run.name)['profile']['profile'],'H5D1')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.console=Console(demo=True)
        self.server=make_server(self.console,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=self.console.url
    def tearDown(self):
        self.console.close();self.server.shutdown();self.server.server_close();self.thread.join(2)
        shutil.rmtree(self.console.session)
    def post(self,path,body,*,token=True,origin=None,host=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Astra-Token']=self.console.token
        if origin:headers['Origin']=origin
        if host:headers['Host']=host
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode(),headers=headers)
        return urllib.request.urlopen(req,timeout=5)
    def test_write_auth_origin_host_and_no_hardware_in_demo(self):
        for options in ({'token':False},{'origin':'https://other.example'},{'host':'evil.example'}):
            with self.subTest(options=options),self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/api/start',{'task':'task'},**options)
            self.assertEqual(error.exception.code,403)
            error.exception.close()
        with self.post('/api/demo-cameras',{'count':2}) as response:self.assertEqual(json.load(response),{'count':2})
        with urllib.request.urlopen(self.base+'/api/state') as response:self.assertEqual(sum(c['available'] for c in json.load(response)['camera_status']),2)
        with self.assertRaises(urllib.error.HTTPError) as error:self.post('/api/capture',{'path':str(ROOT/'logs'),'cameras':[]})
        error.exception.close()
    def test_shared_camera_client_real_http_and_subset(self):
        from shared_cameras import SharedCameraSession
        configs=read_json(ROOT/'config/left_terminal.json')['cameras']
        self.console.camera.demo=False
        fake=MagicMock();fake.snapshot.return_value=([{'synthetic':True}],[],{'expected_serials':[c['serial'] for c in configs]})
        self.console.camera.session=fake
        with tempfile.TemporaryDirectory(dir=ROOT/'logs') as folder,patch.dict(os.environ,ASTRA_CAMERA_HUB_URL=self.base,ASTRA_CAMERA_HUB_TOKEN=self.console.token):
            with SharedCameraSession(configs) as session:images,failures,metrics=session.snapshot(Path(folder))
        self.assertEqual(images,[{'synthetic':True}]);self.assertEqual(failures,[])
        self.assertEqual(len(fake.snapshot.call_args.kwargs['configs']),3)
        self.assertEqual(fake.snapshot.call_count,1)
    def test_path_traversal_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(self.base+'/api/state?run=..')
        error.exception.close()
        with self.assertRaises(ValueError):self.console.resolve_run('../config')

if __name__=='__main__':unittest.main()
