"""Opt-in sealed REAL INPUT tests, FAKE action outputs. No CLI or physical calls."""
import copy,hashlib,json,os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from platform_v1.research.public_store import PublicStore
from platform_v1.research.world_head import WorldHead
from platform_v1.research.broker import Broker
from platform_v1.research.supervisor import Supervisor
from platform_v1.research.contracts import digest
from platform_v1.research import semantic_binding as sb,review_contracts as rc
from platform_v1.research.output_validation import validate_role
from scripts.structured_outputs import check_provider,validate_local
from test_geometry_first_v2 import PendingJob,NoOwner
import test_geometry_first_v2 as gf

ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())

class PersistentBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workspace=os.environ.get('GEOMETRY_FIRST_ARCHIVE_ROOT')
        if not workspace:raise unittest.SkipTest('set GEOMETRY_FIRST_ARCHIVE_ROOT for sealed real INPUT replay')
        cls.ws=Path(workspace);cls.archive=cls.ws/'semantic-grounding-authorized-01-20261010'
        cls.cfg=read(ROOT/'config/research/persistent_semantic_s1_v1.json')
        cls.base=read(cls.ws/'geometry-first-v2-20261010/results/geometry/WORLD.json')
        cls.observation=read(cls.archive/'OBSERVATION.json')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.o=copy.deepcopy(self.observation);self.epoch=self.o['execution_epoch']
        self.store=PublicStore(self.archive/'public_rgb_only',self.o['episode_id']);self.store.observe(self.o,self.epoch)
        self.store.worlds[self.base['world_id']]=copy.deepcopy(self.base);self.store.current_world_id=self.base['world_id'];self.store.revision=self.base['world_revision'];self.store.read_versions=copy.deepcopy(self.base['read_versions'])
        self.source=sb.import_grounding_archive(self.store,self.archive,self.cfg['archive_manifest_sha256'],self.base['world_id'],self.cfg['evidence_id'])
        self.head=WorldHead(self.root/'head',self.store,epoch=lambda:self.epoch,deadline=time.monotonic()+120,emit=lambda *x:None)
    def tearDown(self):self.temp.cleanup()
    def bind(self):
        self.w=self.head.bind_semantic_grounding(self.base['world_id'],self.cfg['evidence_id'],self.cfg['task']);return self.w
    def broker(self,fixture=False):
        return Broker(self.root/('broker-'+str(time.monotonic_ns())),self.store,SimpleNamespace(fixture=fixture),deadline=time.monotonic()+90,epoch=lambda:self.epoch,allowance=lambda:1,baseline_busy=lambda:False,emit=lambda *x:None)
    def request(self):return rc.shadow_request(self.w,self.o,self.cfg['task'],{'profile':'generic_semantic_v1','object_id':self.w['state']['task_target_id'],'goal_id':''})
    def fake_start(self):
        self.b=self.broker(fixture=True)
        with patch('platform_v1.research.broker.ProcessJob',PendingJob),patch('platform_v1.research.broker.sandbox_command',return_value=([],{})):
            rid=self.b.submit(self.request())['request_id']
        self.row=self.b.rows[rid];return self.row
    def answer(self,decision='planned'):return gf.ReviewTests.shadow_answer(self,self.row,decision)
    def fake_finish(self,answer):return gf.ReviewTests.finish(self,self.row,answer)
    def test_restore_pinned_world_without_republishing_or_remeasuring(self):
        self.bind();w=copy.deepcopy(self.w)
        self.store.worlds.pop(w['world_id']);self.store.current_world_id=self.base['world_id'];self.store.revision=1;self.store.read_versions=self.base['read_versions'];self.store.semantic_world_pins.clear()
        with self.assertRaisesRegex(ValueError,'RESTORE_WORLD_PIN'):sb.restore_persistent_world(self.store,w,'forged',self.cfg['task'])
        with self.assertRaisesRegex(ValueError,'RESTORE_TASK_PIN'):sb.restore_persistent_world(self.store,w,w['world_id'],{**self.cfg['task'],'revision':'2'})
        restored=sb.restore_persistent_world(self.store,w,w['world_id'],self.cfg['task'])
        self.assertEqual(restored,w);sb.validate_persistent_world(self.store,restored)
    def test_receipt_actual_raw_schema_world_images(self):
        self.assertEqual(self.source['provenance'],'MODEL_RAW');self.assertEqual(len(self.source['raw_sha256']),64)
        self.assertEqual(self.source['binding']['world_revision'],1);self.assertEqual(self.source['read_versions'],self.base['read_versions'])
        self.assertEqual(len(self.store.get_evidence(self.cfg['evidence_id'])['result']['objects']),6)
    def test_publish_revision_two_preserves_every_nonsemantic_entity_field(self):
        w=self.bind();sb.validate_persistent_world(self.store,w)
        self.assertEqual(w['world_revision'],2);self.assertEqual(w['provenance'],sb.PROVENANCE)
        self.assertEqual(self.store.get_world(self.base['world_id']),self.base)
        for i,e in self.base['state']['entities'].items():
            self.assertEqual({k:v for k,v in e.items() if k not in sb.SEMANTIC_FIELDS},{k:v for k,v in w['state']['entities'][i].items() if k not in sb.SEMANTIC_FIELDS})
        self.assertEqual(w['state']['scene_layers'],self.base['state']['scene_layers']);self.assertEqual(w['state']['geometry_quality'],self.base['state']['geometry_quality'])
        self.assertFalse(w['state']['task_identity_verified']);self.assertEqual(w['state']['task_selection']['status'],'hypothesis')
    def test_query_target_robot_surfaces_and_green_unknown(self):
        w=self.bind();q=self.store.query_world(w['world_id']);s=q['state']
        self.assertEqual(s['task_target_geometry_id'],'object_004');self.assertEqual(s['entities']['object_004']['semantic_category'],'cuboid')
        self.assertEqual(s['entities']['object_004']['point_world_m'],self.base['state']['entities']['object_004']['point_world_m'])
        for i in ('object_001','object_002','object_003'):
            self.assertEqual(s['entities'][i]['semantic_disposition'],'robot');self.assertGreater(s['entities'][i]['candidate_surface_reference']['point_count'],0)
        self.assertEqual(len(s['entities']),6);self.assertEqual(s['semantic_requests'],[])
        self.assertEqual(s['geometry_initialization_unknowns'],self.base['state']['unknowns'])
        self.assertEqual(s['unknowns'],w['state']['semantic_unknowns'])
        self.assertTrue(any('green' in x.lower() for x in s['semantic_unknowns']));self.assertIn('unknown',s['scene_summary']['collision_free_space'])
    def test_production_prepare_zero_calls_keeps_source_and_versions(self):
        self.bind();b=self.broker();b.allowance=lambda:0
        with patch('platform_v1.research.broker.ProcessJob',side_effect=AssertionError('NO_WORKER')),patch('platform_v1.research.broker.sandbox_command',side_effect=AssertionError('NO_AUTH')):
            out=b.prepare(self.request())
        self.assertEqual(b.calls,0);self.assertEqual(b.infer_calls,0);self.assertIsNone(b.action_ready)
        row=b.rows[out['request_id']];check_provider(row['provider_schema'])
        wire=read(b.root/out['request_id']/'input_only/wire.json')
        self.assertEqual(wire['WorldSnapshot']['read_versions'],self.w['read_versions']);self.assertEqual(wire['evidence'][0]['provenance'],'MODEL_RAW')
        self.assertEqual(wire['observations'][self.o['observation_id']]['state']['actual_grasp_center_world'],self.o['state']['actual_grasp_center_world'])
        self.assertEqual(wire['WorldSnapshot']['state']['entities']['object_004']['semantic_disposition'],'object')
    def test_planned_refused_need_more_evidence_parse_and_never_execute(self):
        self.bind()
        for decision in ('planned','refused','need_more_evidence'):
            self.fake_start();a=self.answer(decision);self.fake_finish(a)
            self.assertEqual(self.row['status'],'READY',self.row['error']);self.assertEqual(self.row['provenance'],'FAKE_MODEL_RAW');self.assertIsNone(self.b.action_ready)
            sup=Supervisor(NoOwner(),self.store,None,self.b,self.root/'supervisor')
            with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.from_broker(self.row['request_id'])
            self.assertEqual(sup.plans,{})
            if decision=='planned':
                with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.load(a['result']['plan'],broker_request_id=self.row['request_id'])
                with self.assertRaisesRegex(ValueError,'V2_REQUIRES_BROKER_RAW'):sup.load(a['result']['plan'])
    def test_task_usable_tamper_cannot_grant_execution_even_after_fake_answer(self):
        self.bind();self.fake_start();a=self.answer();self.fake_finish(a)
        self.store.worlds[self.w['world_id']]['state']['geometry_quality']['task_usable']='pass'
        sup=Supervisor(NoOwner(),self.store,None,self.b,self.root/'supervisor')
        with self.assertRaisesRegex(ValueError,'NEVER_EXECUTABLE'):sup.from_broker(self.row['request_id'])
        with self.assertRaises(ValueError):self.broker().prepare(self.request())
    def test_missing_duplicate_extra_geometry_IDs_rejected(self):
        row=read(self.archive/'broker/broker-001/attempt.json')
        for change in (lambda x:x['objects'].pop(),lambda x:x['objects'].append(copy.deepcopy(x['objects'][0])),lambda x:x['objects'][0].update(geometry_instance_id='extra')):
            answer=copy.deepcopy(row['parsed']);change(answer['result'])
            with self.assertRaises(Exception):
                validate_local(answer,row['authoritative_schema'],row['provider_schema']);validate_role('semantic_grounding',answer['result'],row['attachments'],row['binding'],self.base)
    def test_wrong_manifest_pin_and_unregistered_source_rejected(self):
        with self.assertRaisesRegex(ValueError,'MANIFEST_PIN'):sb.import_grounding_archive(self.store,self.archive,'0'*64,self.base['world_id'],self.cfg['evidence_id'])
        self.store.grounding_sources.clear()
        with self.assertRaisesRegex(ValueError,'RECEIPT_REQUIRED'):self.bind()
    def test_evidence_result_or_fake_provenance_or_ID_tampering_rejected(self):
        original=copy.deepcopy(self.store.evidence)
        for change in (lambda e:e.update(provenance='FAKE_MODEL_RAW'),lambda e:e['result'].update(task_target_geometry_id='object_005'),lambda e:e.update(evidence_id='forged'),lambda e:e['attachments'][0].update(sha256='0'*64)):
            self.store.evidence=copy.deepcopy(original);change(self.store.evidence[self.cfg['evidence_id']])
            with self.assertRaises(ValueError):self.bind()
            self.assertEqual(self.store.revision,1)
    def test_receipt_raw_schema_epoch_world_revision_tampering_rejected(self):
        original=copy.deepcopy(self.source)
        for change in (lambda s:s.update(raw_sha256='0'*64),lambda s:s.update(provider_schema_sha256='0'*64),lambda s:s['binding'].update(execution_epoch=1),lambda s:s['binding'].update(world_revision=9),lambda s:s['binding'].update(world_id='wrong')):
            self.store.grounding_sources[self.cfg['evidence_id']]=copy.deepcopy(original);change(self.store.grounding_sources[self.cfg['evidence_id']])
            with self.assertRaises(ValueError):self.bind()
    def test_live_observation_calibration_FK_or_epoch_tamper_rejected(self):
        for change in (lambda o:o.update(execution_epoch=1),lambda o:o['state']['actual_grasp_center_world'].__setitem__(0,99),lambda o:o['calibration']['fixed']['intrinsic'][0].__setitem__(0,1)):
            self.store.observations[self.o['observation_id']]=copy.deepcopy(self.o);change(self.store.observations[self.o['observation_id']])
            with self.assertRaises(ValueError):self.bind()
    def test_changed_RGB_bytes_rejected(self):
        with patch.object(self.store,'image',return_value=(b'changed',{'sha256':'0'*64})):
            with self.assertRaisesRegex(ValueError,'IMAGE_CHANGED'):self.bind()
    def test_base_world_content_epoch_and_stale_binding_rejected(self):
        self.store.worlds[self.base['world_id']]['state']['entities']['object_004']['point_world_m'][0]+=1
        with self.assertRaisesRegex(ValueError,'WORLD_CONTENT_HASH'):self.bind()
        self.store.worlds[self.base['world_id']]=copy.deepcopy(self.base);self.epoch=1
        with self.assertRaisesRegex(ValueError,'STALE_BINDING_EPOCH'):self.bind()
        self.epoch=0;self.bind()
        with self.assertRaisesRegex(ValueError,'STALE_SEMANTIC_BINDING_BASE'):self.bind()
    def test_shadow_different_task_or_target_rejected(self):
        self.bind()
        for task,tb in [(self.cfg['task'],{'profile':'generic_semantic_v1','object_id':'object_005','goal_id':''}),({**self.cfg['task'],'revision':'2'},{'profile':'generic_semantic_v1','object_id':'object_004','goal_id':''})]:
            with self.assertRaisesRegex(ValueError,'SEMANTIC_TASK_BINDING'):rc.shadow_request(self.w,self.o,task,tb)
    def test_persistent_world_tampering_rejected_even_with_rehashed_ID(self):
        self.bind();before=copy.deepcopy(self.w)
        for change in (lambda w:w['state']['entities']['object_004']['point_world_m'].__setitem__(0,9),lambda w:w['state']['entities']['object_003'].update(candidate_surface_cloud=[]),lambda w:w['state'].update(task_target_id='object_005'),lambda w:w['read_versions'].update(forged=1),lambda w:w.update(provenance='MODEL_RAW'),lambda w:w['binding'].update(semantic_raw_sha256='0'*64),lambda w:w.update(world_revision=7)):
            candidate=copy.deepcopy(before);change(candidate);candidate['world_id']='w-'+digest({k:v for k,v in candidate.items() if k!='world_id'})
            self.store.worlds[candidate['world_id']]=candidate;self.store.current_world_id=candidate['world_id'];self.store.revision=candidate['world_revision'];self.store.read_versions=candidate['read_versions']
            with self.assertRaises(ValueError):sb.validate_persistent_world(self.store,candidate)
    def test_stale_versions_after_model_started_reject_output(self):
        self.bind();self.fake_start();self.store.read_versions={**self.store.read_versions,'changed':1};self.fake_finish(self.answer())
        self.assertEqual(self.row['status'],'FAILED');self.assertIsNone(self.b.action_ready)
    def test_shadow_output_tampering_rejected(self):
        self.bind()
        for edit in (lambda a:a['result'].update(K=1),lambda a:a['result'].update(grants_execution=True),lambda a:a['result']['plan']['read_versions'].update(forged=1),lambda a:a['result']['plan'].update(world_revision=1),lambda a:a['evidence_refs'].append('unsent'),lambda a:a['result']['plan']['waypoints'].pop(),lambda a:a['result']['plan'].update(source={'producer':'MODEL_RAW'}),lambda a:a['result'].update(decision='refused')):
            self.fake_start();answer=self.answer();edit(answer);self.fake_finish(answer)
            self.assertEqual(self.row['status'],'FAILED');self.assertIsNone(self.b.action_ready)
    def test_old_20mm_gate_and_geometry_update_limit_unchanged(self):
        self.bind();before=copy.deepcopy(self.w);r=rc.planning_review_eligibility(self.w,self.o)
        self.assertTrue(r['eligible_to_review']);self.assertFalse(r['grants_execution']);self.assertEqual(before,self.w)
        self.assertEqual(self.w['state']['geometry_quality']['task_usable'],'unknown')
        with self.assertRaisesRegex(ValueError,'UPDATE_CONTRACT_ONLY'):self.head.update(self.w['world_id'],self.o['observation_id'],0)
    def test_retained_archive_file_tamper_rejected_before_registration(self):
        # Copy ONLY the first pinned model seal: integrity fails before any raw read.
        fake=self.root/'tampered';fake.mkdir();(fake/'DELIVERY_MANIFEST.json').write_bytes((self.archive/'DELIVERY_MANIFEST.json').read_bytes())
        (fake/'MODEL_RESULT_SEAL.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'ARCHIVE_FILE_HASH'):sb.import_grounding_archive(self.store,fake,self.cfg['archive_manifest_sha256'],self.base['world_id'],self.cfg['evidence_id'])

if __name__=='__main__':unittest.main(verbosity=2)
