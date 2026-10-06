"""Review 3e59e85 reproductions: local synthetic files only; no devices or real inference."""
import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,write_json,read_json
from fixtures.synthetic_history import make_run,action
from episode_archive import archive_episode
from replay_evidence import replay,evidence_zip,mark,request_image_evidence
from reviewed_export import reviewed_zip
from scripts.report_history_experiment import report,aggregate
from astra_gui import Console,CameraHub
from camera_session import CameraSession


def rewrite(path,value):path.write_text(json.dumps(value))
def unzip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:return {n:z.read(n) for n in z.namelist()}
def hashes(folder):return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}

class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        p=patch('episode_archive.ARCHIVES',self.base/'archives');p.start();self.addCleanup(p.stop)
    def fixture(self,name='run'):
        run=make_run(self.base/name);write_json(run/'summary.json',{'episode_id':run.name,'status':'MODEL_DONE','mode':'REAL_EXECUTION','hardware_commands_sent':0})
        write_json(run/'history_profile.json',{'profile':'H5D1','phase':'placement'})
        step=run/'step-01';(step/'decision').mkdir()
        write_json(step/'decision/attachments.json',read_json(step/'input_observation.json')['cameras'])
        return run
    def test_r1_shadow_execute_sources_unknown_and_zero_dispatch(self):
        results=[]
        cases=[('success','REAL_EXECUTION','CodexAstraBackend',False),('ik-zero','REAL_EXECUTION','CodexAstraBackend',False),
               ('shadow','DRY_RUN_ONLY','CodexAstraBackend',False),('fixture','DRY_RUN_ONLY','OFFLINE_FIXTURE_NOT_ASTRA',False),
               ('synthetic','REAL_EXECUTION','CodexAstraBackend',True),('unknown',None,None,False)]
        for name,mode,backend,synthetic in cases:
            run=self.base/name;run.mkdir();step=run/'step-01';(step/'decision').mkdir(parents=True)
            write_json(run/'summary.json',{'episode_id':name,'status':'MODEL_DONE' if name=='success' else 'STOPPED','mode':mode,'hardware_commands_sent':0})
            write_json(run/'history_profile.json',{'profile':'H5D1','phase':'placement'})
            write_json(step/'input_observation.json',{'source':'SYNTHETIC_NOT_REAL' if synthetic else 'LIVE_READ_ONLY' if backend else 'unknown'})
            if backend:write_json(step/'decision/backend_result.json',{'backend':backend})
            if name=='success':write_json(run/'independent_observation.json',{'episode_id':name,'observer':'test','evidence':'synthetic metadata case','actual_stable_in_basket':True})
            result=report(run);results.append(result)
            self.assertEqual(result['classification']['mode'],{'REAL_EXECUTION':'execute','DRY_RUN_ONLY':'shadow',None:'unknown'}[mode])
        counts,dups=aggregate(results)
        self.assertEqual(len(counts),5);self.assertEqual(dups,[])
        self.assertEqual(counts['codex_astra/live/execute/placement/H5D1']['episodes'],2)
        self.assertEqual(counts['codex_astra/live/execute/placement/H5D1']['independently_observed_successes'],1)
        self.assertEqual(counts['codex_astra/live/execute/placement/H5D1']['unknown_outcomes'],1)
        self.assertEqual(counts['codex_astra/live/execute/placement/H5D1']['independently_observed_failures'],0)
        self.assertIn('fixture/live/shadow/placement/H5D1',counts);self.assertIn('synthetic/synthetic/execute/placement/H5D1',counts)
        self.assertIn('unknown/unknown/unknown/placement/H5D1',counts)
    def test_r1_duplicate_path_episode_and_conflicting_modes(self):
        run=self.fixture();write_json(run/'launch_manifest.json',{'settings':{'mode':'shadow'}})
        r=report(run);self.assertEqual(r['classification']['mode'],'execute');self.assertIn('CONFLICTING_MODE_RECORDS',r['classification']['warnings'])
        second=copy.deepcopy(r);second['run']=str(self.base/'other-copy')
        counts,duplicates=aggregate([r,r,second]);self.assertEqual(sum(c['episodes'] for c in counts.values()),1)
        self.assertEqual([d['reason'] for d in duplicates],['DUPLICATE_PATH','DUPLICATE_EPISODE_ID'])
        rewrite(run/'summary.json',{'episode_id':'run','hardware_commands_sent':0})
        self.assertEqual(report(run)['classification']['mode'],'shadow') # explicit launch record only
        (run/'launch_manifest.json').unlink();self.assertEqual(report(run)['classification']['mode'],'unknown')
    def test_r2_valid_missing_hash_dimensions_reference_agree_across_exports(self):
        for fault in ('valid','missing','hash','dimensions','reference'):
            with self.subTest(fault=fault):
                run=self.fixture(fault);step=run/'step-01';obs=read_json(step/'input_observation.json');camera=obs['cameras'][0];path=Path(camera['image_path'])
                expected=camera['sha256'];raw=path.read_bytes()
                if fault=='missing':path.unlink()
                if fault=='hash':
                    from observation import png_rgb
                    path.unlink();png_rgb(path,1,1,b'\xff\xff\xff',3) # another valid PNG, hash stays original in request
                if fault=='dimensions':
                    camera.update(width=99,height=99);rewrite(step/'input_observation.json',obs)
                    rewrite(step/'decision/attachments.json',obs['cameras'])
                if fault=='reference':
                    transition=read_json(step/'transition.json');transition['decision_observation_id']='wrong';rewrite(step/'transition.json',transition)
                item=replay(run,'step-01')['pairs'][0]['decision']
                self.assertEqual(item['available'],fault=='valid')
                receipt=archive_episode(run,'task');folder=Path(receipt['path']);row=read_json(folder/'episode.json')['steps'][0]
                archived=row['input_image_evidence'][0]
                self.assertEqual(archived['available'],item['available']);self.assertEqual(archived['expected_hash'],expected)
                self.assertEqual(receipt['status'],'SAVED')
                if fault=='valid':self.assertEqual(receipt['evidence_status'],'VALID_RECORDED_INPUTS')
                else:
                    self.assertEqual(receipt['evidence_status'],'INVALID_INPUTS')
                    self.assertNotIn(archived,row['input_images']);self.assertIn(archived,row['invalid_input_images'])
                    self.assertIn('INVALID ·', (folder/'index.html').read_text())
                    if fault=='hash':
                        self.assertNotEqual(archived['expected_hash'],archived['actual_hash'])
                        self.assertEqual((folder/archived['image_path']).read_bytes(),path.read_bytes())
                        self.assertNotIn('<img src="'+archived['image_path']+'"',(folder/'index.html').read_text())
                        original=read_json(folder/'record/step-01/decision/attachments.json')[0]
                        self.assertEqual(original['sha256'],expected)
    def test_r2_attachment_reference_and_gui_image_are_rejected(self):
        run=self.fixture();step=run/'step-01';attachments=read_json(step/'decision/attachments.json');attachments[0]['observation_id']='different-observation';rewrite(step/'decision/attachments.json',attachments)
        item=request_image_evidence(run,'step-01')['images'][0];self.assertFalse(item['available'])
        self.assertFalse(replay(run,'step-01')['pairs'][0]['decision']['available'])
        console=Console(demo=True);self.addCleanup(console.close);self.addCleanup(shutil.rmtree,console.session)
        console.current_run=run
        with self.assertRaisesRegex(ValueError,'INVALID'):console.historical_image(None,'step-01',0)
        receipt=archive_episode(run,'task');row=read_json(Path(receipt['path'])/'episode.json')['steps'][0]
        self.assertFalse(row['input_image_evidence'][0]['available'])
    def test_r3_snapshot_immutable_review_versioned_and_no_model_contamination(self):
        run=self.fixture();write_json(run/'step-01/model_input.json',{'task':'task','history':[],'images_in_attachment_order':read_json(run/'step-01/decision/attachments.json')})
        original_context=(run/'step-01/model_input.json').read_bytes();original_transition=(run/'step-01/transition.json').read_bytes()
        receipt=archive_episode(run,'task');capture=Path(receipt['path']);before=hashes(capture)
        first=unzip(reviewed_zip(run));first_version=json.loads(first['review_manifest.json'])['review_version']
        label={'episode_id':run.name,'observer':'human','observed_at':123,'evidence':'offline test','actual_stable_in_basket':False}
        write_json(run/'independent_observation.json',label);write_json(run/'independent-observation-1.json',label)
        mark(run,{'step':'step-01','kind':'first_clear_deviation','observer':'human','evidence':'offline test'})
        files=unzip(reviewed_zip(run));manifest=json.loads(files['review_manifest.json'])
        self.assertNotEqual(manifest['review_version'],first_version);self.assertFalse(manifest['model_input']);self.assertFalse(manifest['history_input'])
        self.assertEqual(json.loads(files['review/independent_observation.json']),label)
        self.assertTrue(all(v['review_valid'] for v in manifest['annotations'].values()))
        self.assertTrue(any(n.startswith('review/review-marker-') for n in files))
        self.assertEqual(archive_episode(run,'task'),receipt);self.assertEqual(hashes(capture),before)
        self.assertEqual((run/'step-01/model_input.json').read_bytes(),original_context);self.assertEqual((run/'step-01/transition.json').read_bytes(),original_transition)
        with tempfile.TemporaryDirectory() as elsewhere:
            with zipfile.ZipFile(io.BytesIO(reviewed_zip(run))) as z:z.extractall(elsewhere)
            for name,meta in manifest['files'].items():self.assertEqual(hashlib.sha256((Path(elsewhere)/name).read_bytes()).hexdigest(),meta['sha256'])
            self.assertEqual((Path(elsewhere)/'capture/manifest.json').read_bytes(),(capture/'manifest.json').read_bytes())
    def test_r3_wrong_episode_not_valid_and_changed_capture_refused(self):
        run=self.fixture();receipt=archive_episode(run,'task')
        write_json(run/'independent_observation.json',{'episode_id':'other','observer':'x','observed_at':1,'evidence':'x'})
        manifest=json.loads(unzip(reviewed_zip(run))['review_manifest.json'])
        self.assertFalse(manifest['annotations']['independent_observation.json']['review_valid'])
        (Path(receipt['path'])/'task.txt').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'CAPTURE_FILE_CHANGED'):reviewed_zip(run)
    def test_r4_numeric_usage_preserved_credentials_redacted_step_and_capture(self):
        run=self.fixture();usage={'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':30}}
        value={'backend':'OFFLINE_FIXTURE_NOT_ASTRA','token_usage':usage,'input_tokens':100,'output_tokens':20,
               'access_token':'fake-access','api_key':'fake-key','authorization':'fake-auth','sessionToken':'fake-session',
               'nested':{'token_usage':{'input_tokens':'fake-credential','output_tokens':True}}}
        write_json(run/'step-01/decision/backend_result.json',value)
        exported=json.loads(unzip(evidence_zip(run,'step-01'))['step-01/decision/backend_result.json'])
        capture=archive_episode(run,'task');archived=read_json(Path(capture['path'])/'record/step-01/decision/backend_result.json')
        for actual in (exported,archived):
            self.assertEqual(actual['token_usage'],usage);self.assertEqual(actual['input_tokens'],100);self.assertEqual(actual['output_tokens'],20)
            self.assertTrue(all(actual[k]=='[REDACTED]' for k in ('access_token','api_key','authorization','sessionToken')))
            self.assertNotIn('fake-credential',json.dumps(actual));self.assertIsInstance(actual['nested']['token_usage']['output_tokens'],str)
    def test_r4_prepared_zip_retains_usage(self):
        from offline_diagnostic_controls import prepare_controls
        run=self.fixture();prepare_controls(run,7,self.base/'controls');out=self.base/'controls'
        # Same allowlisted prepared-input export path as the GUI.
        path=out/'backend_result.json';write_json(path,{'token_usage':{'input_tokens':100,'output_tokens':20},'access_token':'secret-value'})
        result=json.loads(unzip(evidence_zip(out))['backend_result.json'])
        self.assertEqual(result['token_usage'],{'input_tokens':100,'output_tokens':20});self.assertEqual(result['access_token'],'[REDACTED]')
    def test_r5_controlled_runtime_files_for_gui_wrapper_and_direct_cli(self):
        for style in ('gui','wrapper','direct'):
            with self.subTest(style=style):
                run=self.fixture(style)
                write_json(run/'source_manifest.json',{'scripts/run_left_history_diagnostics.py':'run-time-sha256'})
                write_json(run/'config.json',{'task':'task','max_steps':7,'api_key':'fake-key'})
                write_json(run/'action_schema.json',{'type':'object','properties':{'done':{'type':'boolean'}}})
                if style!='direct':write_json(run/'launch_manifest.json',{'git_revision':'actual-run-revision','settings':{'task':'task','max_steps':7}})
                if style=='gui':write_json(run/'gui_launch.json',{'source_manifest':{'astra_gui.py':'actual-gui-hash'}})
                (run/'config').mkdir();(run/'config/token.txt').write_text('must-not-export')
                write_json(run/'step-01/safety.json',{'decision':'REJECT','errors':['STATE_STALE']})
                files=unzip(evidence_zip(run,'step-01'))
                self.assertEqual(json.loads(files['source_manifest.json'])['scripts/run_left_history_diagnostics.py'],'run-time-sha256')
                self.assertEqual(json.loads(files['config.json'])['max_steps'],7);self.assertEqual(json.loads(files['config.json'])['api_key'],'[REDACTED]')
                self.assertEqual(json.loads(files['action_schema.json'])['properties']['done']['type'],'boolean')
                self.assertIn('step-01/safety.json',files);self.assertFalse(any(n.startswith('config/') for n in files))
                self.assertNotIn(b'must-not-export',b''.join(files.values()))
                for name,meta in json.loads(files['manifest.json'])['files'].items():self.assertEqual(hashlib.sha256(files[name]).hexdigest(),meta['sha256'])
    def test_c_wrapper_propagates_runner_codes_and_legacy_budget_two(self):
        import importlib.util,types
        from contextlib import ExitStack,redirect_stdout
        for profile,code,budget in [('H5D1',0,False),('H5D1',1,False),('H5D1',2,False),('legacy1',0,False),('legacy1',1,False),('legacy1',1,True)]:
            with self.subTest(profile=profile,code=code,budget=budget):
                spec=importlib.util.spec_from_file_location('wrapper_test',ROOT/'scripts/run_experiment.py')
                wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
                timers=[]
                class Timer:
                    def __init__(self,seconds,callback):self.callback=callback;timers.append(self)
                    def start(self):pass
                    def cancel(self):pass
                def main():
                    if budget:timers[0].callback()
                    return code
                runner=types.SimpleNamespace(main=main)
                argv=['run_experiment.py','--profile',profile,'--task','task','--no-preview','--lock-path',str(ROOT/'logs/auto-pick.lock')]
                with ExitStack() as stack:
                    for context in (patch.object(sys,'argv',argv),patch.dict('os.environ',{},clear=True),
                        patch.object(wrapper.importlib.util,'spec_from_file_location',return_value=types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda module:None))),
                        patch.object(wrapper.importlib.util,'module_from_spec',return_value=runner),
                        patch.object(wrapper.threading,'Timer',Timer),patch.object(wrapper.os,'kill'),
                        patch('launch_provenance.snapshot',return_value={}),redirect_stdout(io.StringIO())):
                        stack.enter_context(context)
                    actual=wrapper.main()
                self.assertEqual(actual,2 if budget else code)

    def test_a_stream_and_model_sets_are_separate_without_switching(self):
        configs=[{'serial':str(i)} for i in range(4)];session=CameraSession(configs)
        session.active_stream_serials={'0','1','2','3'};session.starts=dict.fromkeys(session.active_stream_serials,1)
        hub=CameraHub(configs);hub.session=session
        with patch.object(session,'__enter__',side_effect=AssertionError('must not restart')):
            d0=hub.stream_metrics('H5D0');d1=hub.stream_metrics('H5D1');legacy=hub.stream_metrics('legacy4')
        self.assertEqual(d0,d1);self.assertEqual(d0['model_input_serials'],['0','1','2'])
        self.assertEqual(d0['active_stream_serials'],['0','1','2','3']);self.assertEqual(d0['pipeline_start_count'],dict.fromkeys('0123',1))
        self.assertEqual(legacy['model_input_serials'],['0','1','2','3'])
        d0['pipeline_start_count']['0']=99;self.assertEqual(session.starts['0'],1)

if __name__=='__main__':unittest.main()
