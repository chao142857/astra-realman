import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from spatial_eval.data import fixtures, box, geometry, task, questions, constraints
from spatial_eval.inputs import load_snapshot, build_input, FRAME
from spatial_eval.schema import parse_prediction, strict_json, read, write, CONDITIONS
from spatial_eval.geometry import contains, swept_collision, angle
from spatial_eval.scoring import evaluate
from spatial_eval.cli import run

class GeometryTests(unittest.TestCase):
    def test_full_volume_and_rotated_container(self):
        region=box('r',[0,0,0],[2,1,1]);small=box('b',[.9,0,0],[.4,.4,.4])
        self.assertFalse(contains(region,small)) # center in bounds, corner outside
        q=[math.cos(math.pi/4),0,0,math.sin(math.pi/4)]
        region['quaternion_wxyz']=q
        self.assertTrue(contains(region,box('b',[0,0,0],[.4,1.8,.4])))
        self.assertFalse(contains(region,box('b',[0,0,0],[1.8,.4,.4])))
    def test_continuous_collision_thin_obstacle(self):
        b=box('b',[0,0,0],[.02]*3);o=box('o',[.5,0,0],[.00001,.05,.05])
        self.assertFalse(swept_collision(b,b['center_m'],o))
        self.assertTrue(swept_collision(b,[1,0,0],o))
        self.assertFalse(swept_collision(b,[1,.5,0],o))
    def test_touch_clearance_and_quaternion_sign(self):
        b=box('b',[0,0,0],[1]*3);o=box('o',[1.001,0,0],[1]*3)
        self.assertFalse(swept_collision(b,[0,0,0],o))
        self.assertTrue(swept_collision(b,[0,0,0],o,.002))
        self.assertAlmostEqual(angle([1,0,0,0],[-1,0,0,0]),0.)
    def test_full_3d_orientation(self):
        q=[math.cos(math.pi/4),math.sin(math.pi/4),0,0]
        region=box('r',[0,0,0],[1,1,2]);b=box('b',[0,0,0],[.1,1.8,.1],q)
        self.assertTrue(contains(region,b))

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.paths=fixtures(self.root/'fixtures');self.s=load_snapshot(self.paths[0])
    def tearDown(self):self.temp.cleanup()
    def test_input_gt_firewall_and_prompt_equality(self):
        self.s['ground_truth']['PRIVATE_SCORE_CANARY']='NEVER_SEND'
        a,ma,_=build_input(self.s,self.s['task'][0],CONDITIONS[0])
        c,mc,_=build_input(self.s,self.s['task'][0],CONDITIONS[2])
        self.assertNotIn('NEVER_SEND',json.dumps(a));self.assertNotIn('NEVER_SEND',json.dumps(c))
        self.assertIsNone(a['geometry']);self.assertNotIn('depth',a['observations'])
        self.assertEqual(ma['task_prompt_sha256'],mc['task_prompt_sha256'])
        c['geometry']=None;self.assertEqual(a,c)
    def test_unknown_fields_reject_geometry_answer_leak(self):
        self.s['geometry']['oracle']['answer']=[.1,.2,.3]
        with self.assertRaises(ValueError):build_input(self.s,self.s['task'][0],CONDITIONS[2])
    def test_b_missing_and_loaded_same_schema(self):
        with self.assertRaisesRegex(ValueError,'GEOMETRY_UNAVAILABLE'):build_input(self.s,self.s['task'][0],CONDITIONS[1])
        self.s['geometry']['reconstruction']=copy.deepcopy(self.s['geometry']['oracle'])
        self.s['geometry']['reconstruction']['source']='RECONSTRUCTION'
        b,m,_=build_input(self.s,self.s['task'][0],CONDITIONS[1]);self.assertEqual(m['geometry_source'],'RECONSTRUCTION')
        self.assertEqual(b['output_schema'],build_input(self.s,self.s['task'][0],CONDITIONS[0])[0]['output_schema'])
    def test_strict_json(self):
        for raw in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}','```json\n{}\n```','{} trailing'):
            with self.assertRaises(ValueError):strict_json(raw)
    def test_understanding_independent_truth(self):
        t=self.s['task'][0];gt=self.s['ground_truth'];b=gt['objects'][0];other=gt['objects'][1]
        values={'relative_x':('relation','less'),'position':('vector_m',b['center_m']),
                'top_height':('scalar_m',.13),'size':('vector_m',b['size_m']),
                'gap_x':('scalar_m',.195),'fits':('fits',True)}
        answers=[]
        for q in t['questions']:
            ans={'question_id':q['question_id'],'relation':None,'scalar_m':None,'vector_m':None,'fits':None}
            slot,value=values[q['question_id']];ans[slot]=value;answers.append(ans)
        p=parse_prediction(json.dumps({'answers':answers}),t)
        self.assertEqual(evaluate(self.s,t,p)['score'],1.)
        p['answers'][1]['vector_m']=[100,0,0]
        self.assertFalse(evaluate(self.s,t,p)['constraints']['position'])
    def test_bad_answer_semantics_and_duplicates(self):
        t=self.s['task'][0]
        for payload in ({'answers':[]},{'answers':[{'question_id':'position','relation':'less','scalar_m':None,'vector_m':[0,0,0],'fits':None}]}):
            with self.assertRaises(ValueError):parse_prediction(json.dumps(payload),t)
    def test_any_valid_placement_and_bad_volume(self):
        t=self.s['task'][1]
        for x in (.58,.62):
            p={'object_id':'target_cube','position_m':[x,.2,.12],'quaternion_wxyz':[1,0,0,0],'waypoints_m':[]}
            self.assertTrue(evaluate(self.s,t,p)['success'])
        p['position_m']=[.675,.2,.12]
        self.assertFalse(evaluate(self.s,t,p)['constraints']['entire_volume_in_allowed_region'])
        p['position_m']=[.6,.2,.12];p['object_id']='other'
        self.assertFalse(evaluate(self.s,t,p)['constraints']['correct_object'])
    def test_path_detour_and_continuous_segment(self):
        s=load_snapshot(self.paths[1]);t=s['task'][1]
        p={'object_id':'target_cube','position_m':[.6,.2,.12],'quaternion_wxyz':[1,0,0,0],
           'waypoints_m':[[.6,.2,.12]]}
        self.assertFalse(evaluate(s,t,p)['constraints']['continuous_path_collision_free'])
        p['waypoints_m']=[[.215,-.2,.12],[.6,-.2,.12],[.6,.2,.12]]
        self.assertTrue(evaluate(s,t,p)['success'])
    def test_invalid_quaternion_bool_and_waypoint_end(self):
        t=self.s['task'][1]
        p={'object_id':'target_cube','position_m':[True,0,0],'quaternion_wxyz':[0,0,0,0],'waypoints_m':[]}
        with self.assertRaises(ValueError):parse_prediction(json.dumps(p),t)
        p['position_m']=[0,0,0]
        with self.assertRaises(ValueError):parse_prediction(json.dumps(p),t)
    def test_unscored_truth_absent(self):
        self.s['ground_truth']=None
        self.assertIsNone(evaluate(self.s,self.s['task'][0],{'answers':[]})['score'])
    def test_image_hash_guard(self):
        path=Path(self.paths[0]);s=read(path);s['observations']['rgb'][0]['sha256']='0'*64;write(path,s)
        with self.assertRaisesRegex(ValueError,'IMAGE_HASH'):load_snapshot(path)
    def test_mock_e2e_and_pairs(self):
        rows=run(self.paths,self.root/'run',[CONDITIONS[0],CONDITIONS[2]])
        self.assertEqual(len(rows),24);self.assertEqual(sum(r['model_calls'] for r in rows),0)
        self.assertTrue(all(r['parse_status']=='VALID' for r in rows))
        pairs=read(self.root/'run/paired_comparison.json');self.assertEqual(len(pairs),12)
        self.assertTrue(all(p['eligible'] for p in pairs))
        self.assertTrue((self.root/'run/failure_index.json').exists())
    def test_malformed_model_response_retained_and_scored_failure(self):
        raw=self.root/'bad.txt';raw.write_text('not json')
        rows=run([self.paths[0]],self.root/'bad_run',[CONDITIONS[0]],fixture_response=raw)
        self.assertTrue(all(r['parse_status']=='INVALID' and r['score']==0. for r in rows))
        self.assertEqual((self.root/'bad_run/sample-0000/raw.txt').read_text(),'not json')
    def test_real_requires_finite_budget_and_rejects_fixture_override(self):
        with self.assertRaisesRegex(ValueError,'BUDGET'):run([self.paths[0]],self.root/'real',CONDITIONS[::2],real=True)
        with self.assertRaisesRegex(ValueError,'FIXTURE'):run([self.paths[0]],self.root/'real',CONDITIONS[::2],real=True,max_real_calls=4,fixture_response='unused')
    def test_no_output_overwrite(self):
        out=self.root/'out';out.mkdir()
        with self.assertRaises(FileExistsError):run([self.paths[0]],out,[CONDITIONS[0]])


class ResponseBoundaryTests(unittest.TestCase):
    def test_backend_failure_does_not_become_model_geometry_failure(self):
        from spatial_eval.cli import assess_response
        result=assess_response({'raw':'','return_code':1,'error':None},{'ground_truth':{}},{'kind':'understanding'})
        self.assertEqual(result['parse_status'],'NO_MODEL_RESPONSE')
        self.assertEqual(result['score_status'],'NOT_SCORED');self.assertIsNone(result['score'])
        self.assertTrue(any(x.startswith('MODEL_TRANSPORT_ERROR:') for x in result['error_types']))
    def test_missing_truth_invalid_json_remains_unscored(self):
        from spatial_eval.cli import assess_response
        result=assess_response({'raw':'not JSON','return_code':0,'error':None},{'ground_truth':None},{'kind':'understanding'})
        self.assertEqual(result['parse_status'],'INVALID');self.assertIsNone(result['score'])
    def test_observation_hidden_fields_rejected(self):
        from spatial_eval.inputs import validate_observations
        from spatial_eval.data import fixtures
        with tempfile.TemporaryDirectory() as d:
            s=load_snapshot(fixtures(Path(d)/'fixtures')[0]);s['observations']['robot_state']['correct_answer']='LEAK'
            with self.assertRaises(ValueError):validate_observations(s['observations'])
    def test_synthetic_real_forbidden(self):
        with tempfile.TemporaryDirectory() as d:
            paths=fixtures(Path(d)/'fixtures')
            with self.assertRaisesRegex(ValueError,'SYNTHETIC_FIXTURE'):
                run([paths[0]],Path(d)/'run',CONDITIONS[::2],real=True,max_real_calls=4)

if __name__=='__main__':unittest.main()
