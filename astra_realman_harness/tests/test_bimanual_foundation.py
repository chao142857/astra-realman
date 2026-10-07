"""Offline contract and ordering checks; never imports a robot SDK or model client."""
import copy, hashlib, json, sys, tempfile, time, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bimanual_demo.protocol import action, parse, Rejected, HardwareDisabled, DisabledAstraBackend
from bimanual_demo.runtime import Runtime, TaskLock
from bimanual_demo.executors import RealArmExecutor, make_arms
from bimanual_demo.gui_contract import snapshot
ROOT=Path(__file__).resolve().parents[1]

class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.site=json.loads((ROOT/'config/bimanual_synthetic.json').read_text())
        self.r=Runtime(self.site,self.root,{'apple':'apple','ball':'tennis_ball'},{'apple':'fruit','ball':'clutter'})
    def tearDown(self):self.tmp.cleanup()
    def do(self,kind,obj='apple',**kw):return self.r.execute(action(self.r.state,kind,obj,**kw))
    def select(self):self.do('SELECT_OBJECT',semantic_class='fruit',destination='plate')
    def present(self):self.select();self.do('LEFT_PICK');self.do('LEFT_PRESENT')
    def count(self):return sum(len(x.calls) for x in self.r.arms.values())
    def test_evidence_image_binding(self):
        self.select();obs=self.r.observe();e=self.r.observer.confirm('LEFT_HOLDING','apple','op',self.r.state,obs);e['camera_hashes']=['fake']
        with self.assertRaisesRegex(Rejected,'EVIDENCE_IMAGE_BINDING'):self.r.state.confirm('LEFT_HOLDING',e,'op')
    def test_schema_version_boolean_rejected(self):
        a=action(self.r.state,'OBSERVE');a['schema_version']=True
        with self.assertRaises(Rejected):parse(a)
    def test_schema_extra_field(self):
        a=action(self.r.state,'OBSERVE');a['extra']=1
        with self.assertRaises(Rejected):parse(a)
    def test_nonfinite(self):
        a=action(self.r.state,'OBSERVE');a['translation_m'][0]=float('nan')
        with self.assertRaises(Rejected):parse(a)
    def test_bool_not_number(self):
        a=action(self.r.state,'OBSERVE');a['translation_m'][0]=True
        with self.assertRaises(Rejected):parse(a)
    def test_class_destination(self):
        with self.assertRaises(Rejected):action(self.r.state,'SELECT_OBJECT','apple',semantic_class='fruit',destination='box')
    def test_stale_decision(self):
        old=action(self.r.state,'OBSERVE');self.select()
        with self.assertRaises(Rejected):self.r.execute(old)
    def test_duplicate_decision(self):
        a=action(self.r.state,'OBSERVE');self.r.execute(a)
        with self.assertRaises(Rejected):self.r.execute(a)
    def test_unknown_object(self):
        with self.assertRaises(Rejected):self.do('LEFT_PICK','unknown')
    def test_no_left_release_before_right_confirmation(self):
        self.present();self.r.observer.fail_events.add('RIGHT_HOLDING_CONFIRMED')
        n=len(self.r.arms['left'].calls);result=self.do('BIMANUAL_HANDOFF')
        self.assertEqual(result['status'],'RECOVER_REQUIRED');self.assertEqual(len(self.r.arms['left'].calls),n)
        self.assertFalse(self.r.state.objects['apple']['holder_valid'])
    def test_partial_open_also_release(self):
        self.present()
        with self.assertRaisesRegex(Rejected,'LEFT_RELEASE'):self.r.gate('left','set_gripper',.7)
    def test_sdk_ack_does_not_prove_grasp(self):
        self.select();self.r.observer.fail_events.add('LEFT_HOLDING');self.do('LEFT_PICK')
        self.assertEqual(self.r.arms['left'].calls[-1]['return_code'],0)
        self.assertEqual(self.r.state.objects['apple']['holder'],'none')
        self.assertNotIn('apple',self.r.state.completed_objects)
    def test_full_handshake(self):
        self.present();self.do('BIMANUAL_HANDOFF')
        events=[e['event'] for e in self.r.state.events]
        ordered=['LEFT_HOLDING','LEFT_AT_HANDOFF','RIGHT_AT_HANDOFF','RIGHT_HOLDING_CONFIRMED','LEFT_RELEASED','LEFT_RETRACT','LEFT_CLEAR']
        self.assertEqual([e for e in events if e in ordered],ordered)
        self.assertEqual(self.r.state.handoff,'RIGHT_OWNS_OBJECT');self.assertEqual(self.r.state.objects['apple']['holder'],'right')
    def test_right_transport_before_left_clear_forbidden(self):
        self.present()
        with self.assertRaisesRegex(Rejected,'LEFT_NOT_CLEAR'):self.r.gate('right','move','plate_approach')
    def test_no_automatic_retry_unknown_ack(self):
        self.present();self.r.arms['right'].fail_next='unknown'
        result=self.do('BIMANUAL_HANDOFF')
        self.assertEqual(result['status'],'RECOVER_REQUIRED');self.assertEqual(len(self.r.arms['right'].calls),1)
        raw=[x['data'] for x in self.r.recorder.rows if x['kind']=='RAW_HARDWARE_COMMAND'][-1]
        self.assertTrue(raw['uncertain_dispatch'])
    def test_recovery_is_evidence_only(self):
        self.present();self.r.arms['right'].fail_next='unknown';self.do('BIMANUAL_HANDOFF');n=self.count()
        self.r.observer.recovery={'holder':'left','checkpoint':'LEFT_AT_HANDOFF'}
        self.do('RECOVER');self.assertEqual(self.count(),n);self.assertIsNone(self.r.state.fault)
        self.assertTrue(self.r.state.objects['apple']['holder_valid'])
    def test_recovery_without_evidence_stays_failed(self):
        self.present();self.r.state.fail('test');n=self.count();self.do('RECOVER')
        self.assertIsNotNone(self.r.state.fault);self.assertEqual(self.count(),n)
    def test_wrong_sort_destination(self):
        self.present();self.do('BIMANUAL_HANDOFF');n=self.count();result=self.do('RIGHT_PLACE',destination='box')
        self.assertEqual(result['status'],'RECOVER_REQUIRED');self.assertEqual(self.count(),n)
    def test_endpoint_alias_rejected(self):
        self.site['arms']['right']['endpoint']=self.site['arms']['left']['endpoint']
        with self.assertRaises(Rejected):make_arms(self.site,'synthetic')
    def test_hardware_unavailable(self):
        with self.assertRaises(HardwareDisabled):RealArmExecutor('right')
        self.site['hardware_enabled']=True
        with self.assertRaises(Rejected):make_arms(self.site,'synthetic')
    def test_model_unavailable(self):
        with self.assertRaisesRegex(RuntimeError,'REAL_MODEL_DISABLED'):DisabledAstraBackend().decide({},[])
    def test_medium_only(self):
        self.site['requested_effort']='low'
        with self.assertRaises(Rejected):Runtime(self.site,self.root/'other',{}, {})
    def test_delta_exact(self):
        self.select();before=self.r.arms['left'].pose[:]
        result=self.do('DELTA_CORRECTION',arm_id='left',frame='synthetic:left:work',translation_m=[.002,-.003,.001],rotation_rpy_rad=[.01,0,0])
        self.assertEqual(result['status'],'COMPLETED_WITH_RECORDED_EVIDENCE')
        self.assertEqual(self.r.arms['left'].pose,[x+y for x,y in zip(before,[.002,-.003,.001,.01,0,0])])
        self.assertEqual(len(self.r.arms['right'].calls),0)
    def test_cross_arm_frame_rejected(self):
        self.select();result=self.do('DELTA_CORRECTION',arm_id='left',frame='synthetic:right:work')
        self.assertEqual(result['status'],'RECOVER_REQUIRED');self.assertEqual(self.count(),0)
    def test_stop_blocks_commands(self):
        self.select();self.r.stop.set()
        with self.assertRaises(Rejected):self.do('LEFT_PICK')
        self.assertEqual(self.count(),0)
    def test_lock_exclusion(self):
        with TaskLock(self.root/'lock'):
            with self.assertRaises(BlockingIOError):
                with TaskLock(self.root/'lock'):pass
    def test_revision_clears_history_and_invalidates_targets(self):
        self.present();self.assertTrue(self.r.memory.frames)
        new=dict(self.site['revision'],camera='moved')
        self.r.invalidate_revision(new)
        self.assertFalse(self.r.memory.frames);self.assertIsNotNone(self.r.state.fault)
        self.assertNotEqual(self.site['synthetic_waypoints']['left_handoff']['revision'],new)
    def test_four_current_images_not_displaced(self):
        self.select();self.do('LEFT_PICK');obs=self.r.observe()
        images=self.r.memory.attachments(obs,'apple','last_clear_object_view')
        self.assertEqual(len(images),4);self.assertEqual({x['kind'] for x in images},{'current'})
    def test_history_label_and_provenance(self):
        self.select();obs=self.r.observe();obs['images']=obs['images'][:3]
        images=self.r.memory.attachments(obs,'apple','last_clear_object_view')
        self.assertEqual(images[-1]['kind'],'history');self.assertIn('reason_selected',images[-1])
    def test_image_hash(self):
        obs=self.r.observe();Path(obs['images'][0]['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(Rejected,'IMAGE_HASH'):self.r.memory.attachments(obs,'apple')
    def test_future_history(self):
        self.select();frame=self.r.memory.frames[('apple','last_clear_object_view')];frame['timestamp']=time.time()+100
        obs=self.r.observe();obs['images']=obs['images'][:3]
        with self.assertRaisesRegex(Rejected,'FUTURE_HISTORY'):self.r.memory.attachments(obs,'apple','last_clear_object_view')
    def test_evidence_stale(self):
        self.select();obs=self.r.observe();e=self.r.observer.confirm('LEFT_HOLDING','apple','op',self.r.state,obs)
        self.r.observe()
        with self.assertRaisesRegex(Rejected,'STALE_EVIDENCE'):self.r.state.confirm('LEFT_HOLDING',e,'op')
    def test_evidence_future_timestamp(self):
        self.select();obs=self.r.observe();e=self.r.observer.confirm('LEFT_HOLDING','apple','op',self.r.state,obs);e['timestamp']+=100
        with self.assertRaisesRegex(Rejected,'EVIDENCE_TIME'):self.r.state.confirm('LEFT_HOLDING',e,'op')
    def test_new_evidence_can_invalidate_old_belief(self):
        self.present();obs=self.r.observe();e=self.r.observer.confirm('BELIEF_CONTRADICTED','apple','op',self.r.state,obs)
        self.r.state.contradict(e,'op');self.assertEqual(self.r.state.phase,'RECOVER');self.assertFalse(self.r.state.objects['apple']['holder_valid'])
    def test_log_snapshots_are_immutable(self):
        value={'a':[]};self.r.recorder.emit('TEST',value);value['a'].append(1)
        self.assertEqual(self.r.recorder.rows[-1]['data']['a'],[])
    def test_not_sent_log_cannot_reuse_last_command(self):
        self.present();self.r.site['synthetic_waypoints']['left_handoff']['frame']='wrong'
        a=action(self.r.state,'BIMANUAL_HANDOFF','apple')
        with self.assertRaises(Rejected):self.r.move('left','left_handoff',a)
        raw=[x['data'] for x in self.r.recorder.rows if x['kind']=='RAW_HARDWARE_COMMAND'][-1]
        self.assertFalse(raw['dispatched']);self.assertNotIn('return_code',raw)
    def test_nominal_two_objects_and_archive(self):
        for obj,cls,dest in [('apple','fruit','plate'),('ball','clutter','box')]:
            self.do('SELECT_OBJECT',obj,semantic_class=cls,destination=dest)
            for kind in ['LEFT_PICK','LEFT_PRESENT','BIMANUAL_HANDOFF']:self.do(kind,obj)
            self.do('RIGHT_PLACE',obj,destination=dest);self.do('VERIFY',obj)
        summary=self.r.recorder.export(self.r.state)
        self.assertEqual(summary['completed_objects'],['apple','ball'])
        self.assertEqual(summary['real_model_calls']+summary['real_hardware_calls'],0)
        for x in summary['per_object'].values():self.assertTrue(x['successful_sort'] and x['successful_handoff']);self.assertEqual(x['calls_per_object'],0)
        with zipfile.ZipFile(self.root/'capture_snapshot.zip') as z:
            manifest=json.loads(z.read('manifest.json'))
            for path,digest in manifest['files'].items():self.assertEqual(hashlib.sha256(z.read(path)).hexdigest(),digest)
        kinds={x['kind'] for x in self.r.recorder.rows}
        self.assertTrue({'ASTRA_DECISION','SKILL_INTERNAL_ACTION','RAW_HARDWARE_COMMAND','MEASURED_FEEDBACK','SKILL_RESULT'}<=kinds)
        self.assertFalse(snapshot(self.r.state,self.r.recorder.metrics())['hardware_enabled'])

if __name__=='__main__':unittest.main()
