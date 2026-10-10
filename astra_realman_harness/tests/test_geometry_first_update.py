import copy,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from platform_v1.research.world_head import WorldHead
from platform_v1.research import rgbd_world as rw,semantic_binding as sb
from platform_v1.research import review_contracts as rc
from platform_v1.research.broker import Broker
from types import SimpleNamespace
from candidate_update_fixtures import sensor_store,inject_observation,read,ROOT

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store,self.o,self.w,self.cfg=sensor_store(self.root);self.epoch=0
        self.head=WorldHead(self.root/'head',self.store,epoch=lambda:self.epoch,deadline=time.monotonic()+120,emit=lambda *x:None)
    def tearDown(self):self.temp.cleanup()
    def injected(self,mode='unchanged',old=None,index=1):
        o,fb=inject_observation(self.store,old or self.o,index,mode);self.epoch=o['execution_epoch'];return o,fb
    def update(self,o,fb,reference=None):
        return self.head.update((reference or self.w)['world_id'],o['observation_id'],fb['completed_monotonic'],execution_feedback=fb)
    def test_current_sensor_remeasurement_and_semantic_causal_chain(self):
        o,fb=self.injected()
        with patch.object(rw,'build_geometry_first',side_effect=AssertionError('NO_BUILD_RESET')):
            w=self.update(o,fb)
        sb.validate_geometry_update(self.store,w)
        e=w['state']['entities']['object_004'];self.assertEqual(e['status'],'coarse');self.assertEqual(e['semantic_status'],'hypothesis')
        self.assertEqual(e['semantic_source'],self.w['state']['entities']['object_004']['semantic_source'])
        self.assertEqual(e['observation_id'],o['observation_id']);self.assertEqual(e['historical_geometry']['observation_id'],self.o['observation_id'])
        self.assertEqual(w['world_revision'],3);self.assertEqual(w['binding']['execution_epoch'],1)
        self.assertEqual(w['binding']['evidence_ids'],self.w['binding']['evidence_ids']);self.assertNotEqual(w['read_versions'],self.w['read_versions'])
        self.assertEqual(w['state']['robot_state'],o['state']);self.assertEqual(w['state']['geometry_quality']['task_usable'],'unknown')
        self.assertEqual(w['provenance'],'SYNTHETIC_SENSOR_REPLAY')
        self.assertEqual(self.store.get_world(self.w['world_id']),self.w)
        self.assertEqual(w['state']['resource_metrics']['Astra_calls'],0)
        q=self.store.query_world(w['world_id']);self.assertEqual(q['state']['entities']['object_004']['temporal_association']['status'],'unique_current_match')
    def test_all_holes_separate_current_unknown_historical_geometry_semantics(self):
        o,fb=self.injected('holes');w=self.update(o,fb)
        for e in w['state']['entities'].values():
            self.assertEqual(e['status'],'unknown');self.assertIsNone(e['point_world_m']);self.assertEqual(e['candidate_surface_cloud'],[])
            self.assertEqual(e['semantic_status'],'unknown');self.assertTrue(e['historical_geometry']['candidate_surface_cloud'])
            self.assertEqual(e['views'],[]);self.assertEqual(e['current_evidence'],[])
        self.assertEqual(w['state']['scene_layers']['static']['current_support_count'],0)
        self.assertEqual(w['state']['task_target_current_support']['status'],'unknown')
        self.assertFalse(w['state']['scene_layers']['unassigned_current']['temporal_fusion'])
    def test_recovery_from_short_gap_uses_new_depth_not_old_position(self):
        o,fb=self.injected('holes');lost=self.update(o,fb)
        # Copy original sensor content but advance from the gap's metadata; explicit synthetic recovery.
        current,feedback=self.injected('unchanged',old=self.o,index=2)
        # inject_observation derives a +1 time; force the second frame's causal metadata consistently.
        self.store.observations.pop(current['observation_id'])
        delta=1.;current['captured_monotonic']+=delta;current['execution_epoch']=2
        for d in current['depth']:
            d['captured_monotonic']+=delta;d['capture_interval_monotonic']=[v+delta for v in d['capture_interval_monotonic']];d['readback_completed_monotonic']+=delta
        feedback.update(completed_monotonic=current['captured_monotonic']-.02,source_observation_id=o['observation_id'])
        self.store.observe(current,2);self.epoch=2;w=self.update(current,feedback,lost)
        e=w['state']['entities']['object_004'];self.assertEqual(e['status'],'coarse');self.assertEqual(e['semantic_status'],'hypothesis')
        self.assertTrue(all(v['observation_id']==current['observation_id'] for v in e['views']))
        sb.validate_geometry_update(self.store,w)
    def test_wrist_holes_keep_fixed_view_support_without_copying_bbox(self):
        o,fb=self.injected('wrist_holes');w=self.update(o,fb);e=w['state']['entities']['object_004']
        self.assertEqual(e['status'],'coarse');self.assertEqual(set(v['camera'] for v in e['views']),{'assembly','fixed'})
        self.assertEqual(e['visibility']['wrist']['status'],'depth_unknown')
    def test_FK_and_bad_depth_fail_without_new_revision(self):
        for index,mode in enumerate(('bad_fk','nan'),1):
            o,fb=self.injected(mode,index=index)
            with self.assertRaisesRegex(ValueError,'FK_INCONSISTENT|DEPTH_VALIDITY_VALUES'):self.update(o,fb)
            self.assertEqual(self.store.revision,2)
    def test_feedback_and_completion_causality_fail_closed(self):
        o,fb=self.injected()
        for bad in (None,{**fb,'completed_monotonic':fb['completed_monotonic']+1},{**fb,'source_observation_id':'wrong'}):
            with self.assertRaises(ValueError):self.head.update(self.w['world_id'],o['observation_id'],fb['completed_monotonic'],execution_feedback=bad)
            self.assertEqual(self.store.revision,2)
        self.epoch=0
        with self.assertRaisesRegex(ValueError,'STALE_UPDATE_EPOCH'):self.update(o,fb)
    def test_occlusion_is_projection_evidence_not_current_object_measurement(self):
        o,fb=self.injected('occlusion')
        ext,k=rw.calibrated_cameras(o);depths={c:self.store.depth(o['observation_id'],c) for c in rw.CAMERAS}
        hist={'surface_cloud':self.w['state']['entities']['object_004']['candidate_surface_cloud']}
        visibility=[rw.expected_visibility(hist,c,ext[i],k[i],depths) for i,c in enumerate(rw.CAMERAS)]
        self.assertTrue(any(v['status']=='occluded' for v in visibility))
        w=self.update(o,fb);e=w['state']['entities']['object_004']
        self.assertEqual(e['status'],'unknown');self.assertIsNone(e['point_world_m']);self.assertEqual(e['semantic_status'],'unknown')
        self.assertTrue(any(v.get('temporal_association',{}).get('status')=='new_or_unresolved_candidate' for v in w['state']['entities'].values()))
    def test_stale_feedback_and_cross_episode_rejected(self):
        o,fb=self.injected();fb['completed_monotonic']=self.o['captured_monotonic']-1
        with self.assertRaisesRegex(ValueError,'STALE_COMPLETION_FEEDBACK'):self.update(o,fb)
        fb['completed_monotonic']=o['captured_monotonic']-.01;fb['execution_epoch']=99
        with self.assertRaisesRegex(ValueError,'FEEDBACK_EPOCH'):self.update(o,fb)
        wrong=copy.deepcopy(o);wrong['episode_id']='different'
        with self.assertRaisesRegex(ValueError,'OBSERVATION_EPISODE'):self.store.observe(wrong,self.epoch)
    def test_failed_execution_does_not_infer_holding_or_confirmed_identity(self):
        o,fb=self.injected();fb['ok']=False;w=self.update(o,fb)
        for old_id in self.w['state']['entities']:
            self.assertEqual(w['state']['entities'][old_id]['semantic_status'],'unknown')
            self.assertEqual(w['state']['entities'][old_id]['held_relation'],'unknown')
    def test_two_admissible_candidates_do_not_steal_identity(self):
        e=copy.deepcopy(self.w['state']['entities']['object_004']);c={'a':copy.deepcopy(e),'b':copy.deepcopy(e)}
        matches,report=rw.associate_geometry_frames({'old':e},c,self.o,{**self.o,'captured_monotonic':self.o['captured_monotonic']+1},
            self.head._images(self.o['observation_id']),self.head._images,read(ROOT/'config/research/geometry_first_update_v1.json'),self.w['state']['object_config']['tracker'])
        self.assertEqual(matches,{});self.assertEqual(set(report['previous_candidates']['old']),{'a','b'})
    def test_two_previous_instances_competing_for_one_current_remain_unknown(self):
        e=copy.deepcopy(self.w['state']['entities']['object_004'])
        matches,r=rw.associate_geometry_frames({'a':e,'b':copy.deepcopy(e)},{'new':copy.deepcopy(e)},self.o,
            {**self.o,'captured_monotonic':self.o['captured_monotonic']+1},self.head._images(self.o['observation_id']),self.head._images,
            read(ROOT/'config/research/geometry_first_update_v1.json'),self.w['state']['object_config']['tracker'])
        self.assertEqual(matches,{});self.assertEqual(len(r['current_competitors']['new']),2)
    def test_synthetic_movement_measures_residual_and_never_accumulates_object_surface(self):
        e=copy.deepcopy(self.w['state']['entities']['object_004']);moved=copy.deepcopy(e)
        moved['candidate_surface_cloud']=(np.asarray(e['candidate_surface_cloud'])+[.06,0,0]).tolist()
        # Explicit FAKE tracker measurement to isolate association, not a physical-motion trial.
        fake={'mask':e['views'][0]['mask'],'reason':'SYNTHETIC_TEST_TRACK','association':'hypothesis'}
        with patch.object(rw,'track_view',return_value=fake):
            matches,r=rw.associate_geometry_frames({'old':e},{'new':moved},self.o,{**self.o,'captured_monotonic':self.o['captured_monotonic']+1},
                self.head._images(self.o['observation_id']),self.head._images,read(ROOT/'config/research/geometry_first_update_v1.json'),self.w['state']['object_config']['tracker'])
        self.assertEqual(matches,{'old':'new'});self.assertAlmostEqual(r['pairs'][0]['geometry_residual']['surface_median_displacement_m'],.06)
    def test_update_receipt_version_and_source_tampering_rejected(self):
        o,fb=self.injected();w=self.update(o,fb)
        bad=copy.deepcopy(w);bad['state']['entities']['object_004']['point_world_m'][0]+=.1
        with self.assertRaisesRegex(ValueError,'HASH'):sb.validate_geometry_update(self.store,bad)
        self.store.read_versions['forged']=1
        with self.assertRaisesRegex(ValueError,'STALE'):sb.validate_geometry_update(self.store,w)
        self.store.read_versions=copy.deepcopy(w['read_versions']);self.store.observations[o['observation_id']]['state']['qpos'][0]+=1
        with self.assertRaisesRegex(ValueError,'OBSERVATION_CHANGED'):sb.validate_geometry_update(self.store,w)
    def test_synthetic_injection_never_qualifies_as_real_model_input(self):
        o,fb=self.injected();w=self.update(o,fb)
        req=rc.candidate_shadow_request(w,o,self.cfg['task'],{'profile':'generic_semantic_v1','object_id':'object_004','goal_id':''})
        b=Broker(self.root/'broker',self.store,SimpleNamespace(fixture=False),deadline=time.monotonic()+30,epoch=lambda:self.epoch,
            allowance=lambda:0,baseline_busy=lambda:False,emit=lambda *x:None)
        with self.assertRaisesRegex(ValueError,'UNTRUSTED_GEOMETRY_SOURCE'):b.prepare(req)
        self.assertEqual(b.calls,0)

if __name__=='__main__':unittest.main(verbosity=2)
