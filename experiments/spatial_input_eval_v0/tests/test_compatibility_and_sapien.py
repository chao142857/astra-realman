"""Offline acceptance over real saved renders and local (fake) CLI protocol evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from local_protocol_probe import sandbox
from telemetry_filter import phases
from prepare_native_text_plan import plan
from spatial_eval.sapien_scenes import truth_from_state
from spatial_eval.inputs import load_snapshot,build_input
from spatial_eval.scoring import evaluate

CAPTURES=ROOT/'evidence/sapien_six_v0_attempt1/captures'


class CompatibilityTests(unittest.TestCase):
    def test_failed_http_and_stream_each_make_one_fake_post(self):
        for name in ('local_http503_no_retry','local_truncate_no_retry'):
            r=json.loads((ROOT/'evidence/compatibility_audit'/name/'RESULT.json').read_text())
            self.assertEqual(r['status'],'PASS')
            self.assertEqual(r['inference_post_count'],1)
            self.assertEqual(r['real_model_calls'],0)
            self.assertFalse(r['turn_completed']);self.assertEqual(r['raw'],'')

    def test_native_supported_telemetry_exposes_wire_phases_without_identity(self):
        r=json.loads((ROOT/'evidence/compatibility_audit/local_protocol_final/sanitized_native_phases.json').read_text())
        events=[p['attributes'].get('event.kind') for p in r if p['type']=='event']
        self.assertIn('response.created',events);self.assertIn('response.completed',events)
        self.assertIn('response.output_text.delta',events)
        for p in r:
            self.assertNotIn('resource',p);self.assertNotIn('headers',p);self.assertNotIn('body',p)

    def test_next_request_plan_is_budget_zero_with_no_execution_api(self):
        r=plan()
        self.assertEqual(r['status'],'PLAN_ONLY_NOT_AUTHORIZED')
        self.assertEqual(r['authorized_real_generation_budget'],0)
        self.assertEqual(r['model'],'gpt-6-astra')
        self.assertIsNone(r['output_schema']);self.assertEqual(r['images'],[])
        self.assertFalse(r['host_enabled_diagnostic_design']['production_bridge_change'])
        self.assertIn('model_provider="openai"',r['baseline_native_ws_argv'])
        self.assertIn('model_providers.astra_diag_openai_http_once.name="OpenAI"',r['proposed_single_http_argv'])

    def test_warning_is_not_terminal_in_current_native_local_fixture(self):
        folder=ROOT/'evidence/compatibility_audit/local_protocol_host_v2'
        result=json.loads((folder/'RESULT.json').read_text())
        self.assertEqual(result['real_model_calls'],0)
        self.assertTrue(result['fail_closed_warning'])
        self.assertTrue(result['turn_completed'])
        self.assertEqual(json.loads(result['raw']),{'offline_fixture':True})
        self.assertTrue(result['strict_json_valid'])
        req=next(x['body'] for x in json.loads((folder/'fake_requests.json').read_text()) if x['path'].endswith('/responses'))
        self.assertEqual(req['model'],'gpt-6-astra')
        self.assertEqual(req['reasoning']['effort'],'medium')
        self.assertTrue(any(x['type']=='additional_tools' for x in req['input']))

    def test_matching_host_negotiates_v1_without_executing_cells(self):
        result=json.loads((ROOT/'evidence/compatibility_audit/local_protocol_host_v2/host_handshake.json').read_text())
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['executed_cells'],0)
        self.assertEqual(result['nested_tools'],0)
        self.assertEqual(result['transcript'][0]['response']['selectedVersion'],1)

    def test_local_sandbox_has_no_external_network_auth_or_gt_mount(self):
        cmd=sandbox(Path('/tmp/out'),Path('/tmp/cli'),Path('/tmp/host'),Path('/tmp/probe.py'))
        self.assertIn('--unshare-all',cmd);self.assertNotIn('--share-net',cmd)
        binds=[cmd[i+1:i+3] for i,v in enumerate(cmd) if v in ('--ro-bind','--bind')]
        for source,dest in binds:
            for banned in ('auth.json','ground_truth','scoring.py','controller','astra_realman_harness'):
                self.assertNotIn(banned,source)
        self.assertEqual([b for b in binds if b[1]=='/output'],[['/tmp/out','/output']])

    def test_telemetry_drops_credentials_resource_ids_raw_body_and_unknown_values(self):
        attrs=[{'key':k,'value':{'stringValue':v}} for k,v in {
          'event.name':'codex.sse_event','event.kind':'response.created','authorization':'Bearer PRIVATE',
          'user.email':'PRIVATE_EMAIL','error.message':'PRIVATE_ERROR','duration_ms':'PRIVATE_TEXT'}.items()]
        sample={'resourceLogs':[{'resource':{'attributes':[{'key':'PRIVATE_ACCOUNT','value':{'stringValue':'PRIVATE'}}]},
          'scopeLogs':[{'logRecords':[{'body':{'stringValue':'PRIVATE_BODY'},'attributes':attrs}]}]}]}
        result=phases(sample)
        self.assertEqual(result,[{'type':'event','attributes':{'event.name':'codex.sse_event','event.kind':'response.created'}}])
        self.assertNotIn('PRIVATE',json.dumps(result))


class SapienEvidenceTests(unittest.TestCase):
    def test_all_six_render_seals_and_model_input_boundary(self):
        folders=sorted(CAPTURES.glob('sapien_*'));self.assertEqual(len(folders),6)
        for folder in folders:
            seal=json.loads((folder/'SEAL.json').read_text())
            for name,expected in seal['sha256'].items():
                self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(),expected)
            scene=load_snapshot(folder/'snapshot.json')
            self.assertEqual(len(scene['task']),2)
            self.assertEqual(len(scene['observations']['rgb']),3)
            self.assertEqual(len(scene['observations']['depth']),3)
            self.assertIsNone(scene['geometry']['reconstruction'])
            self.assertEqual(scene['ground_truth']['source'],'SIMULATOR_TRUTH')
            for task in scene['task']:
                a,am,_=build_input(scene,task,'RGB_MULTI_VIEW')
                c,cm,_=build_input(scene,task,'RGB_ORACLE_3D')
                self.assertIsNone(a['geometry']);self.assertNotIn('ground_truth',a);self.assertNotIn('ground_truth',c)
                self.assertEqual(am['task_prompt_sha256'],cm['task_prompt_sha256'])
                self.assertNotIn('answers',c['geometry']);self.assertNotIn('physics_state.json',json.dumps(c))

    def test_gt_tracks_actual_collider_pose_size_and_container_inner_faces(self):
        state=json.loads((CAPTURES/'sapien_v0_clear/physics_state.json').read_text())
        gt=truth_from_state(state)
        changed=copy.deepcopy(state)
        target=next(r for r in changed if r['id']=='target_cube')
        target['pose_xyz_wxyz'][0]+=.037;target['half_size_m'][0]*=1.5
        wall=next(r for r in changed if r['id']=='container_x_plus')
        wall['pose_xyz_wxyz'][0]+=.025
        result=truth_from_state(changed)
        self.assertAlmostEqual(result['objects'][0]['center_m'][0]-gt['objects'][0]['center_m'][0],.037)
        self.assertAlmostEqual(result['objects'][0]['size_m'][0],gt['objects'][0]['size_m'][0]*1.5)
        self.assertAlmostEqual(result['regions'][0]['size_m'][0]-gt['regions'][0]['size_m'][0],.025)

    def test_planning_tasks_have_geometric_solutions_and_colliding_paths_fail(self):
        for folder in CAPTURES.glob('sapien_*'):
            scene=load_snapshot(folder/'snapshot.json');task=scene['task'][1]
            region=next(r for r in scene['ground_truth']['regions'] if r['id']=='container_interior')
            end=region['center_m']
            prediction={'object_id':'target_cube','position_m':end,'quaternion_wxyz':[1,0,0,0],'waypoints_m':[]}
            if task['kind']=='path':
                start=task['constraints']['start_position_m']
                prediction['waypoints_m']=[[start[0],start[1],.40],[end[0],end[1],.40],end]
            self.assertTrue(evaluate(scene,task,prediction)['success'],folder.name)
            if task['kind']=='path':
                prediction['waypoints_m']=[end]
                self.assertFalse(evaluate(scene,task,prediction)['constraints']['continuous_path_collision_free'])


if __name__=='__main__':unittest.main()
