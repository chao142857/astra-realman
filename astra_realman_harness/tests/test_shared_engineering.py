"""Offline unit contracts, never instantiate SAPIEN or load/connect an SDK."""
import copy,json,tempfile,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engineering.public_view import observation,execution,model_proposal,error_code
from scripts.run_engineering_pnp import layout_config,classify,process_status
from scripts.export_engineering_observations import export
from scripts.prepare_realman_readonly import inspect_config
from scripts.report_engineering_pnp import release_exit_checks
BASE=Path(__file__).resolve().parents[1]
class EngineeringTests(unittest.TestCase):
    def test_timeout_or_process_failure_cannot_become_pass_from_partial_result(self):
        self.assertEqual(process_status({'status':'PASS'},0,'TIMEOUT_NO_RETRY'),'TIMEOUT')
        self.assertEqual(process_status({'status':'PASS'},-15,None),'PROCESS_FAILURE')
        self.assertEqual(process_status({'status':'FAIL'},1,None),'FAIL')
    def test_export_uses_relocated_archive_images_not_old_absolute_paths(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'run';(run/'episode').mkdir(parents=True);(run/'scene/obs_0001').mkdir(parents=True)
            cal={n:{'pose_world_xyz_wxyz':[0,0,0,1,0,0,0],'intrinsic':[[1,0,0],[0,1,0],[0,0,1]],'resolution':[2,2]} for n in ('assembly','fixed','wrist')}
            for n in cal:Image.new('RGB',(2,2)).save(run/'scene/obs_0001'/(n+'.png'))
            obs={'observation_id':'o1','captured_monotonic':1.,'capture_span_s':.01,'state':{'sim_step':1},'calibration':cal,
                 'images':{n:'/missing-original-location/scene/obs_0001/'+n+'.png' for n in cal}}
            (run/'episode/timeline.jsonl').write_text(json.dumps({'kind':'OBSERVATION','data':obs})+'\n')
            export(run,root/'public');self.assertTrue((root/'public/obs-0000/fixed.png').is_file())
    def test_initial_open_clear_pose_is_not_release_or_exit_completion(self):
        score={'released':True,'exited':True}
        self.assertEqual(release_exit_checks(score,[]),{'release':False,'exit':False})
        events=[{'data':{'result':{'ok':True}}} for _ in range(7)]
        self.assertEqual(release_exit_checks(score,events),{'release':True,'exit':True})
        events[5]['data']['result']['ok']=False
        self.assertFalse(release_exit_checks(score,events)['release'])
    def test_layout_changes_only_initial_object_and_marker(self):
        cfg={'scene':{'cube_initial_xyz':[0,0,.026],'place_zone_xy':[0,0],'gravity':[0,0,-9.81],'cube_mass_kg':.01},'control':{'contact_hold_torque_Nm':.1}}
        original=copy.deepcopy(cfg);layout={'object_initial_xyz':[.33,-.1,.026],'target_xy':[.33,.13]}
        out=layout_config(cfg,layout);self.assertEqual(cfg,original)
        for k in ('cube_initial_xyz','place_zone_xy'):out['scene'][k]=original['scene'][k]
        self.assertEqual(out,original)
    def test_invalid_coordinates_rejected(self):
        for bad in ([.3,float('nan'),.026],[.3,True,.026],[.3,0]):
            with self.assertRaises(ValueError):layout_config({'scene':{}},{'object_initial_xyz':bad,'target_xy':[.3,.1]})
    def test_predeclared_six_distinct_layout_trials(self):
        p=json.loads((BASE/'config/engineering/layouts_v1.json').read_text());self.assertEqual(p['repeats']*len(p['layouts']),6)
        self.assertEqual(len({tuple(x['object_initial_xyz']+x['target_xy']) for x in p['layouts']}),3)
        self.assertEqual(p['seed_each_process'],2);self.assertEqual(p['model_calls'],0)
    def test_failure_classification_keeps_failure(self):
        for error,want in [('GRASP_CONTACT_LOST_AFTER_LATCH','CONTACT_LOSS_OR_GRASP'),('IK Failed!','PLANNING_IK'),('PAD_CONTACT_PENETRATION','GEOMETRY_CONTACT_SAFETY'),('HUMAN_STOP','STOP')]:
            self.assertEqual(classify({'status':'FAIL','episode':{'error':error}}),want)
    def test_observation_excludes_private_fields_and_copies_current_images(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);Image.new('RGB',(3,3),'red').save(p/'rgb.png')
            cal={n:{'pose_world_xyz_wxyz':[0,0,0,1,0,0,0],'intrinsic':[[1,0,0],[0,1,0],[0,0,1]],'resolution':[3,3],'GT':'PRIVATE_SENTINEL'} for n in ('assembly','fixed','wrist')}
            r={'observation_id':'o1','captured_monotonic':1.,'capture_span_s':.01,'state':{'sim_step':1,'stopped':False,'qpos':[0]*12,'contact_truth':'PRIVATE_SENTINEL'},'calibration':cal,'images':{n:str(p/'rgb.png') for n in cal},'score':'PRIVATE_SENTINEL','expert_grasp':'PRIVATE_SENTINEL'}
            out=observation(r,p/'public');self.assertNotIn('PRIVATE_SENTINEL',json.dumps(out));self.assertEqual(len(out['rgb']),3)
            self.assertTrue(all(x['sensor_exposure_timestamp'] is None for x in out['rgb']))
            with self.assertRaises(FileExistsError):observation(r,p/'public')
    def test_feedback_excludes_expert_targets_truth_and_raw_error_blob(self):
        r={'ok':False,'error':'PRIVATE_SENTINEL','results':[{'action':{'type':'move_pose','pose':'PRIVATE_SENTINEL'},'result':{'ok':False,'requested_target_rad':'PRIVATE_SENTINEL','error':'GRASP_CONTACT_LOST_AFTER_LATCH PRIVATE_SENTINEL','contact_truth':'PRIVATE_SENTINEL','after':{'sim_step':2,'object_pose':'PRIVATE_SENTINEL'}}}]}
        p=execution(r);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(p));self.assertEqual(p['results'][0]['error_code'],'GRASP_CONTACT_LOST_AFTER_LATCH')
        self.assertEqual(p['holding_status'],'UNKNOWN_FROM_COMMAND_COMPLETION')
    def test_nonnumeric_feedback_refused(self):
        with self.assertRaises(ValueError):execution({'ok':True,'results':[{'result':{'ok':True,'position_error_m':{'GT':1}}}]})
    def test_engineering_proposal_never_becomes_model_raw(self):
        with self.assertRaisesRegex(ValueError,'ENGINEERING_ANSWERS'):model_proposal('{}',{},source='ENGINEERING_REFERENCE')
    def test_model_proposal_comes_only_from_strict_raw(self):
        w={'role':'B','binding':{'source':'o1'},'attachments':[{'id':'i1'}],'evidence_packet_hash':None}
        c={'kind':'candidate','binding':w['binding'],'operation':'chunk','actions':[{'type':'gripper','opening':.45}],
           'requirements':['scene_healthy'],'evidence_refs':['i1'],'parent_evidence_hash':None,'verdict':None,'reason':'test raw'}
        self.assertEqual(model_proposal(json.dumps(c),w,source='MODEL_RAW')['candidate'],c)
        with self.assertRaises(Exception):model_proposal('BROKEN_RAW',w,source='MODEL_RAW')
    def test_sdk_default_inspection_never_loads_or_connects(self):
        cfg=json.loads((BASE/'config/engineering/realman_readonly_template.json').read_text())
        with patch('realman_api2_readonly.load_sdk',side_effect=AssertionError('NO_SDK')),patch('socket.create_connection',side_effect=AssertionError('NO_NETWORK')):
            r=inspect_config(cfg)
        self.assertEqual(r['status'],'NOT_READY');self.assertEqual(r['device_connections'],0);self.assertFalse(r['sdk_loaded'])
        self.assertIn('world_to_base',r['unknown_parameters'])
    def test_motion_scope_not_accepted_by_readonly(self):
        r=inspect_config({'scope':'MOTION','execution_permitted':True});self.assertIn('SCOPE',r['blocking'])

if __name__=='__main__':unittest.main(verbosity=2)
