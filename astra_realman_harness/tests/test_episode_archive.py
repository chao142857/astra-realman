import copy
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,write_json,read_json,new_run
from fixtures.synthetic_history import make_run,observation,action
from episode_archive import archive_episode,finalize_archive,task_filename
from history_diagnostics import DIAGNOSTIC_FIELDS

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'logs');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.archive_root=self.base/'episodes'
        change=patch('episode_archive.ARCHIVES',self.archive_root);change.start();self.addCleanup(change.stop)
    def fixture(self,name='run',status='MODEL_DONE'):
        run=make_run(self.base/name)
        write_json(run/'summary.json',{'status':status,'episode_id':run.name})
        step=run/'step-01';(step/'decision').mkdir()
        obs=read_json(step/'input_observation.json')
        write_json(step/'decision/attachments.json',obs['cameras'])
        write_json(step/'parsed_action.json',action())
        write_json(step/'diagnostics.json',dict.fromkeys(DIAGNOSTIC_FIELDS,'public evidence only'))
        (step/'decision/astra_raw.txt').write_text('exact public model output')
        return run
    def test_all_steps_images_raw_output_and_exact_task_portable(self):
        run=self.fixture();task='  抓球/放框: "任务"\n<script>alert(1)</script>  '
        result=archive_episode(run,task);folder=Path(result['path'])
        self.assertTrue(folder.name.startswith(task_filename(task)+'__'))
        self.assertTrue(folder.name.endswith('_CST'));self.assertEqual(folder.parent,self.archive_root)
        self.assertEqual((folder/'task.txt').read_text(),task)
        doc=read_json(folder/'episode.json');self.assertEqual(doc['task'],task);self.assertEqual(len(doc['steps']),7)
        self.assertEqual(doc['steps'][0]['diagnostics']['scene_assessment'],'public evidence only')
        self.assertEqual((folder/'record/step-01/decision/astra_raw.txt').read_text(),'exact public model output')
        self.assertNotIn('<script>',(folder/'index.html').read_text());self.assertIn('&lt;script&gt;', (folder/'index.html').read_text())
        for step in doc['steps']:
            for image in step['input_images']:self.assertTrue((folder/image['image_path']).is_file())
        for name,meta in read_json(folder/'manifest.json')['files'].items():self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(),meta['sha256'])
        self.assertEqual(read_json(run/'auto_archive.json')['status'],'SAVED')
    def test_idempotent_concurrent_save_and_same_task_different_episodes(self):
        run=self.fixture()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:archive_episode(run,'任务'),range(2)))
        self.assertEqual(results[0]['path'],results[1]['path'])
        second=archive_episode(self.fixture('another'),'任务')
        self.assertNotEqual(results[0]['path'],second['path'])
    def test_failed_episode_missing_images_preserves_available_evidence(self):
        run=self.fixture(status='STOPPED')
        Path(read_json(run/'step-01/input_observation.json')['cameras'][0]['image_path']).unlink()
        result=archive_episode(run,'失败任务');folder=Path(result['path'])
        self.assertTrue(result['warnings']);self.assertEqual(read_json(folder/'episode.json')['summary']['status'],'STOPPED')
        self.assertTrue((folder/'record/step-01/parsed_action.json').is_file())
    def test_write_failure_reports_without_deleting_original(self):
        run=self.fixture();events=[]
        with patch('episode_archive._build_archive',side_effect=OSError('disk full')):
            result=finalize_archive(run,'任务',lambda *args:events.append(args))
        self.assertEqual(result['status'],'FAILED');self.assertTrue((run/'summary.json').is_file())
        self.assertFalse(list(self.archive_root.glob('.partial-*')))
        self.assertEqual(read_json(run/'auto_archive.json')['status'],'FAILED');self.assertEqual(events[0][0],'AUTO ARCHIVE')
    def test_filename_long_unicode_and_path_characters(self):
        for task in ('../../bad\\path:*?<>|',' ','CON','抓球'*200):
            name=task_filename(task);self.assertLessEqual(len(name.encode()),125)
            self.assertNotIn('/',name);self.assertNotIn('\\',name);self.assertTrue(name)
    def test_seven_original_cli_profiles_archive_without_hardware(self):
        obs=observation(self.base,now=100)
        config=read_json(ROOT/'config/left_terminal_fourview.json')['cameras'][-1]
        obs4=copy.deepcopy(obs);obs4['cameras'].append(dict(config,width=1,height=1,image_path=obs['cameras'][0]['image_path'],sha256=obs['cameras'][0]['sha256'],captured_at=100))
        write_json(self.base/'obs.json',obs);write_json(self.base/'obs4.json',obs4)
        write_json(self.base/'action.json',action());write_json(self.base/'envelope.json',{'action':action(),'diagnostics':dict.fromkeys(DIAGNOSTIC_FIELDS,'unknown')})
        entries=[('run_left_history_diagnostics.py',p) for p in ('H1D0','H5D0','H1D1','H5D1')]+[('run_left_terminal.py',None),('run_left_threeview_history5.py',None),('run_left_fourview.py',None)]
        for entry,profile in entries:
            with self.subTest(entry=entry,profile=profile):
                spec=importlib.util.spec_from_file_location('archive_runner',ROOT/'scripts'/entry);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
                argv=[entry,'--replay',str(self.base/('obs4.json' if entry=='run_left_fourview.py' else 'obs.json')),'--fixture',str(self.base/('envelope.json' if profile and profile.endswith('D1') else 'action.json')),'--task','  终端原样任务  ','--no-preview','--max-steps','1']
                if profile:argv+=['--profile',profile]
                capture=io.StringIO()
                with patch.object(sys,'argv',argv),patch.object(sys,'stdin',io.StringIO('')),patch('signal.signal'),redirect_stdout(capture):runner.main()
                lines=capture.getvalue().splitlines();result=json.loads(next(line.split(' → ',1)[1] for line in lines if line.startswith('AUTO ARCHIVE → ')))
                self.assertEqual(result['status'],'SAVED',result)
                run=Path(result['source_run']);self.addCleanup(shutil.rmtree,run)
                self.assertEqual(read_json(run/'summary.json')['hardware_commands_sent'],0)
                self.assertEqual(read_json(run/'summary.json')['model_calls'],0)
                self.assertEqual((Path(result['path'])/'task.txt').read_text(),'  终端原样任务  ')
                self.assertEqual(len(read_json(Path(result['path'])/'episode.json')['steps']),1)

if __name__=='__main__':unittest.main()
