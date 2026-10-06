import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,read_json,write_json
from fixtures.synthetic_history import make_run,action
from replay_evidence import replay,evidence_zip,mark
from offline_diagnostic_controls import prepare_controls,annotation_template,verified_facts
from scripts.prepare_history_replay import decision_observation

class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs');self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.run=make_run(self.base/'recording')
        for step in sorted(self.run.glob('step-*'))[:6]:
            before=read_json(step/'input_observation.json');(step/'pre-execution').mkdir()
            write_json(step/'pre-execution/observation.json',before)
            t=read_json(step/'transition.json')
            write_json(step/'parsed_action.json',t['proposed_action'])
            write_json(step/'execution_result.json',{'status':t['execution_status'],'executed_action':t['executed_command'],'hardware_commands_sent':t['hardware_commands_sent']})
            write_json(step/'feasibility.json',t['feasibility'])
        self.obs=decision_observation(self.run/'step-07')
    def annotation(self):
        a=annotation_template(self.obs);a['observer']='test-observer'
        a['visual_positions']=[{'object':'ball','camera_serial':self.obs['cameras'][1]['serial'],'coordinate_system':'normalized_0_1000_top_left_x_right_y_down','xy':[250,750],'source':'human_verified_current_image'}]
        return a
    def test_pairing_reordered_after_and_zero_dispatch(self):
        path=self.run/'step-02/next_observation.json';obs=read_json(path);obs['cameras'].reverse();path.write_text(json.dumps(obs))
        data=replay(self.run,'step-02')
        self.assertEqual(len(data['pairs']),3)
        for pair in data['pairs']:
            self.assertTrue(pair['before']['available']);self.assertTrue(pair['after']['available'])
            self.assertEqual(pair['before']['serial'],pair['after']['serial'])
        self.assertEqual(data['facts']['transition']['hardware_commands_sent'],0)
        self.assertIsNone(data['facts']['transition']['translation_residual_m'])
    def test_missing_before_and_after_are_never_substituted(self):
        data=replay(self.run,'step-07')
        self.assertTrue(all(p['before'] is None and p['after'] is None for p in data['pairs']))
        self.assertTrue(any('MISSING_DISPATCH_BEFORE' in w for w in data['warnings']))
    def test_hash_observation_reference_and_step_mismatch_block_images(self):
        path=self.run/'step-03/next_observation.json';obs=read_json(path)
        obs['observation_id']='wrong';path.write_text(json.dumps(obs))
        data=replay(self.run,'step-03');self.assertFalse(any(p['after']['available'] for p in data['pairs']))
        obs['observation_id']=read_json(self.run/'step-03/transition.json')['after_observation_id'];obs['cameras'][0]['sha256']='bad';path.write_text(json.dumps(obs))
        data=replay(self.run,'step-03');self.assertFalse(data['pairs'][0]['after']['available'])
        self.assertIn('IMAGE_HASH',data['pairs'][0]['after']['errors'])
    def test_markers_are_post_hoc_and_export_is_portable(self):
        mark(self.run,{'step':'step-02','kind':'first_clear_deviation','observer':'reader','evidence':'Observed frame; cause unknown'})
        write_json(self.run/'gui_launch.json',{'token':'do-not-export','settings':{'task':'task'},'source':'sk-sensitive123'})
        archive=evidence_zip(self.run,'step-02')
        self.assertNotIn(b'do-not-export',archive)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            manifest=json.loads(z.read('manifest.json'))
            for name,item in manifest['files'].items():self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),item['sha256'])
            for name in z.namelist():
                if name.endswith('.json'):
                    raw=z.read(name).decode();self.assertNotIn(str(ROOT),raw);self.assertNotIn('do-not-export',raw);self.assertNotIn('sk-sensitive123',raw)
            replay_data=json.loads(z.read('replay.json'))
            for pair in replay_data['pairs']:
                for stage in ('decision','before','after'):
                    item=pair[stage];self.assertIn(item['image_path'],z.namelist())
            self.assertTrue(replay_data['markers'][0]['post_hoc'])
    def test_independent_controls_preserve_original_task_and_history(self):
        mark(self.run,{'step':'step-06','kind':'first_clear_deviation','observer':'reader','evidence':'DO_NOT_FEED_FUTURE_FAILURE'})
        out=self.base/'controls';manifest=prepare_controls(self.run,7,out,annotation=self.annotation())
        baseline=read_json(out/'baseline/H5D1/model_input.json')
        self.assertEqual(read_json(out/'original/model_input.json'),baseline)
        for name,key in [('verified_visual_positions','verified_current_visual_positions'),('verified_current_task_state','verified_current_task_state')]:
            c=read_json(out/name/'model_input.json');added=c.pop(key);self.assertEqual(c,baseline)
            self.assertNotIn('DO_NOT_FEED_FUTURE_FAILURE',json.dumps(added))
        self.assertEqual(manifest['model_calls'],0);self.assertFalse(manifest['executor_present'])
        self.assertEqual(verified_facts(self.obs,self.annotation())['visual_positions'][0]['pixels_xy'],[0,0])
    def test_annotations_reject_future_fields_wrong_image_and_out_of_range(self):
        for edit in (lambda a:a.update(final_success=True),lambda a:a['task_state'].update(next_action='release'),lambda a:a['visual_positions'][0].update(xy=[1001,0]),lambda a:a['reference_images'][0].update(sha256='bad')):
            a=self.annotation();edit(a)
            with self.assertRaises(ValueError):verified_facts(self.obs,a)
    def test_visual_history_fourth_is_previous_fixed_before_and_base_unchanged(self):
        out=self.base/'history';m=prepare_controls(self.run,7,out,visual_history_mode='previous_fixed_before')
        base=read_json(out/'baseline/H5D1/model_input.json');c=read_json(out/'three_current_plus_previous_fixed/model_input.json')
        self.assertEqual(len(base['images_in_attachment_order']),3)
        self.assertEqual(c['images_in_attachment_order'][:3],base['images_in_attachment_order'])
        fourth=c['images_in_attachment_order'][3]
        before=read_json(self.run/'step-06/pre-execution/observation.json')
        self.assertEqual(fourth['observation_id'],before['observation_id']);self.assertEqual(fourth['image_path'],before['cameras'][1]['image_path'])
        self.assertEqual(c['history'],base['history']);self.assertEqual(c['task'],base['task'])
        self.assertNotIn('Only the three current images',c['evidence_rules'])
        self.assertEqual(c['visual_history_experiment']['base_profile'],'H5D1')
        with zipfile.ZipFile(out/'prepared-evidence.zip') as z:
            exported=json.loads(z.read('three_current_plus_previous_fixed/model_input.json'))
            self.assertEqual(len(exported['images_in_attachment_order']),4)
            for image in exported['images_in_attachment_order']:self.assertIn(image['image_path'],z.namelist())
    def test_visual_history_first_and_missing_image_are_explicit(self):
        for step in (1,7):
            if step==7:(self.run/'step-06/pre-execution/observation.json').unlink()
            out=self.base/('missing'+str(step));prepare_controls(self.run,step,out,visual_history_mode='previous_fixed_before')
            c=read_json(out/'three_current_plus_previous_fixed/model_input.json')
            self.assertEqual(len(c['images_in_attachment_order']),3);self.assertTrue(c['visual_history_experiment']['status'].startswith('MISSING'))
    def test_dimensions_and_future_transition_rejected(self):
        p=self.run/'step-06/pre-execution/observation.json';before=read_json(p)
        before['cameras'][1]['width']=99;p.write_text(json.dumps(before))
        self.assertFalse(replay(self.run,'step-06')['pairs'][1]['before']['available'])
        with self.assertRaisesRegex(ValueError,'INTEGRITY'):prepare_controls(self.run,7,self.base/'badsize',visual_history_mode='previous_fixed_before')
        before['cameras'][1]['width']=1;p.write_text(json.dumps(before))
        tpath=self.run/'step-06/transition.json';t=read_json(tpath);t['timestamps']['completed_at']=self.obs['decision_ready_at']+1;tpath.write_text(json.dumps(t))
        with self.assertRaisesRegex(ValueError,'FUTURE'):prepare_controls(self.run,7,self.base/'future',visual_history_mode='previous_fixed_before')
    def test_future_and_after_image_rejected(self):
        p=self.run/'step-06/pre-execution/observation.json';before=read_json(p);before['observation_id']=self.obs['observation_id'];p.write_text(json.dumps(before))
        with self.assertRaisesRegex(ValueError,'CURRENT_OR_AFTER'):prepare_controls(self.run,7,self.base/'bad',visual_history_mode='previous_fixed_before')
    def test_real_backend_payload_accepts_four_attachments_without_hardware(self):
        out=self.base/'history';prepare_controls(self.run,7,out,visual_history_mode='previous_fixed_before')
        c=read_json(out/'three_current_plus_previous_fixed/model_input.json');folder=self.base/'transport';folder.mkdir()
        from codex_astra_backend import CodexAstraBackend
        from history_diagnostics import schema_path,decode,DIAGNOSTIC_FIELDS
        raw=json.dumps({'action':action(),'diagnostics':dict.fromkeys(DIAGNOSTIC_FIELDS,'unknown')})
        events='\n'.join(json.dumps(v) for v in [{'type':'item.completed','item':{'type':'agent_message','text':raw}},{'type':'turn.completed'}])
        payloads=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'return_code':0,'raw':raw,'events':events}).encode()
        def transport(req,timeout):payloads.append(json.loads(req.data));return Response()
        original=Path.read_text
        def read(path,*a,**kw):return 'offline-token' if path.name=='codex_astra_bridge.token' else original(path,*a,**kw)
        with patch.object(Path,'read_text',read),patch('codex_astra_backend.urllib.request.urlopen',transport):
            backend=CodexAstraBackend({'bridge_url':'http://127.0.0.1:18766','timeout_s':3},folder,'gpt-6-astra',threading.Event(),lambda *v:None,schema_path('H5D1'),lambda raw:decode(raw,'H5D1')[1])
            self.assertEqual(backend.decide(c,c['images_in_attachment_order']),action())
        self.assertEqual(len(payloads),1);self.assertEqual(len(payloads[0]['images']),4)
        self.assertEqual(read_json(folder/'attachments.json'),c['images_in_attachment_order'])
        import importlib.util
        spec=importlib.util.spec_from_file_location('bridge',ROOT/'scripts/codex_astra_mac_bridge.py');bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
        cmd=bridge.command(folder,[Path(v['image_path']) for v in c['images_in_attachment_order']])
        self.assertEqual(cmd.count('--image'),4)

if __name__=='__main__':unittest.main()
