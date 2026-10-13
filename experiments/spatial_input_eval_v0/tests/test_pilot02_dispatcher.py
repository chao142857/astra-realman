import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
import pilot02_runtime as r
import pilot02_dispatcher as d
from pilot02_mock import mock_bridge
from spatial_eval.mac_bridge import validate_context as original_validate
from spatial_eval.schema import read,write

class Pilot02DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.jobs=r.verify_frozen()['ordered_samples']
        # Every test prohibits any subprocess, including a CLI generation.
        self.no_process=patch('subprocess.Popen',side_effect=AssertionError('ZERO_GENERATION_NO_SUBPROCESS'))
        self.no_process.start();self.addCleanup(self.no_process.stop)

    def witness(self,job):
        folder=r.MODULE/job['input_directory']
        return read(folder.parent.parent/'private/design_and_controls.json')['witness']

    def invoke(self,state,job,name,raw=None,timeout=180):
        state['raw']=json.dumps(self.witness(job)) if raw is None else raw
        context,images,*_=r.job_input(job);folder=self.root/name
        adapter=r.Pilot02MacBridgeAdapter(state['config'],job,offline_test=True)
        response=adapter.infer(context,images,folder,timeout_s=timeout)
        return r.record_and_rescore(folder,job),response,folder

    def test_twenty_frozen_inputs_protocol_policy_scoring_and_rescore(self):
        with mock_bridge(self.root) as state:
            for i,j in enumerate(self.jobs):
                result,response,folder=self.invoke(state,j,f'case-{i}')
                self.assertEqual(result['status'],'VALID');self.assertEqual(result['score'],1)
                self.assertEqual(response['model_calls'],0)
                self.assertEqual(read(folder/'assessment.json'),read(folder/'independent_rescore.json'))
                self.assertEqual(state['payloads'][-1]['context']['task_policy'],r.job_input(j)[4])
            self.assertEqual(state['decide_calls'],20);self.assertEqual(state['cancel_calls'],0)
            for a,c in zip(state['payloads'][::2],state['payloads'][1::2]):
                aa=copy.deepcopy(a['context']);cc=copy.deepcopy(c['context']);aa['geometry']=cc['geometry']=None
                self.assertEqual(aa,cc);self.assertEqual(a['images'],c['images'])

    def test_all_twenty_negative_controls_preserved_as_valid_zero(self):
        with mock_bridge(self.root) as state:
            for i,j in enumerate(self.jobs):
                spec=read((r.MODULE/j['input_directory']).parent.parent/'private/design_and_controls.json')
                for name,bad in spec['negative_controls'].items():
                    raw=json.dumps(bad)
                    result,_,folder=self.invoke(state,j,f'negative-{i}-{name}',raw)
                    self.assertEqual(result['status'],'VALID');self.assertEqual(result['score'],0)
                    self.assertEqual((folder/'raw.txt').read_text(),raw)

    def test_missing_or_tampered_policy_gt_schema_and_images_never_dispatch(self):
        job=self.jobs[-1]
        with mock_bridge(self.root) as state:
            context,images,*_=r.job_input(job)
            variants=[]
            c=copy.deepcopy(context);c.pop('task_policy');variants.append(c)
            c=copy.deepcopy(context);c['task_policy']['orientation']['max_tilt_rad']=.5;variants.append(c)
            c=copy.deepcopy(context);c['ground_truth']={'answer':'PRIVATE_CANARY'};variants.append(c)
            c=copy.deepcopy(context);c['geometry']={'planning_witness':'PRIVATE_CANARY'};variants.append(c)
            c=copy.deepcopy(context);c['instruction']+='PRIVATE_GT_CANARY';variants.append(c)
            c=copy.deepcopy(context);c['output_schema']={};variants.append(c)
            for c in variants:
                adapter=r.Pilot02MacBridgeAdapter(state['config'],job,offline_test=True)
                with self.assertRaises(ValueError):adapter.infer(c,images,self.root/'forbidden')
            fake=self.root/'bad.png';fake.write_bytes(images[0].read_bytes()+b'changed')
            with self.assertRaises(ValueError):adapter.infer(context,[fake,*images[1:]],self.root/'bad-image')
            self.assertEqual(state['decide_calls'],0)
            with self.assertRaises(ValueError):original_validate(context,images)

    def test_protocol_failures_are_not_capability_zero_and_never_retry(self):
        with mock_bridge(self.root) as state:
            for i,mode in enumerate(['invalid_json','empty','no_completed','duplicate_completed','failed_event','return_error','transport_error','parameter_drift','code_mode_drift']):
                state['mode']=mode;before=state['decide_calls']
                result,_,folder=self.invoke(state,self.jobs[0],f'bad-{i}')
                self.assertEqual(result['status'],'NOT_SCORED',mode);self.assertIsNone(result['score'])
                self.assertEqual(state['decide_calls'],before+1);self.assertEqual(read(folder/'transport.json')['retries'],0)

    def test_403_and_409_no_infer_or_retry(self):
        with mock_bridge(self.root) as state:
            state['config'].token_file.write_text('WRONG_OFFLINE_CREDENTIAL_ONLY')
            result,_,folder=self.invoke(state,self.jobs[0],'403')
            self.assertEqual(read(folder/'transport.json')['http_status'],403);self.assertIsNone(result['score'])
            self.assertEqual(state['stub_calls'],0)
            state['config'].token_file.write_text('OFFLINE_FIXTURE_NOT_A_REAL_CREDENTIAL')
            state['busy'].acquire()
            try:result,_,folder=self.invoke(state,self.jobs[0],'409')
            finally:state['busy'].release()
            self.assertEqual(read(folder/'transport.json')['http_status'],409);self.assertIsNone(result['score'])
            self.assertEqual(state['stub_calls'],0);self.assertEqual(state['decide_calls'],2)

    def test_timeout_cancel_is_unknown_and_no_retry(self):
        with mock_bridge(self.root) as state:
            state['mode']='timeout';result,response,folder=self.invoke(state,self.jobs[0],'timeout',timeout=.08)
            self.assertIsNone(result['score']);self.assertIn('UNKNOWN',response['error'])
            self.assertEqual(state['decide_calls'],1);self.assertEqual(state['cancel_calls'],1)
            self.assertEqual(read(folder/'transport.json')['retries'],0)

    def test_dry_run_default_and_no_grant_cannot_dispatch(self):
        root=self.root/'batch';s=d.prepare(root)
        with patch.object(d,'perform',side_effect=AssertionError('NO_DISPATCH')):
            self.assertEqual(d.run(root)['real_dispatches_this_command'],0)
            with self.assertRaises(ValueError):d.run(root,real=True)
        self.assertEqual(d.load(root)['reserved_budget'],0)
        with self.assertRaises(FileExistsError):d.prepare(root)
        with self.assertRaises(ValueError):d.prepare(r.MODULE/'evidence/pilot01_20261013/new')

    def fixture_state(self):
        root=self.root/'batch';s=d.prepare(root);s['mode']='OFFLINE_FIXTURE';s['status']='READY';d.save(root/'ledger.json',s);return root,s

    def fake_result(self,i,score=0):
        return {'status':'VALID','score':score,'thread_id':f'fixture-{i}','source':'FAKE_MAC_BRIDGE_NOT_ASTRA'}

    def test_budget_reserved_before_runner_strict_order_zero_scores_continue(self):
        root,s=self.fixture_state();seen=[]
        def runner(job,folder):
            live=d.load(root);self.assertEqual(live['reserved_budget'],len(seen)+1)
            self.assertEqual(live['runs'][-1]['status'],'RESERVED');seen.append(job['planned_order'])
            return self.fake_result(len(seen))
        d.advance(root,s,runner,20)
        self.assertEqual(seen,list(range(1,21)));self.assertEqual(s['status'],'COMPLETE')
        with self.assertRaises(ValueError):d.advance(root,s,runner,20)
        self.assertEqual(len(read(root/'paired_results.json')),10)

    def test_invalid_stops_entire_batch_without_second_request(self):
        root,s=self.fixture_state();calls=[]
        def runner(j,p):calls.append(j);return {'status':'NOT_SCORED','score':None,'source':'FAKE_MAC_BRIDGE_NOT_ASTRA'}
        d.advance(root,s,runner,20)
        self.assertEqual(len(calls),1);self.assertEqual(s['reserved_budget'],1);self.assertEqual(s['status'],'STOPPED')
        with self.assertRaises(ValueError):d.advance(root,s,runner,20)

    def test_crash_unknown_never_refunds_or_reissues(self):
        root,s=self.fixture_state()
        def crash(j,p):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):d.advance(root,s,crash,20)
        state=d.load(root);self.assertEqual(state['reserved_budget'],1);self.assertEqual(state['runs'][0]['status'],'UNKNOWN')
        with self.assertRaises(ValueError):d.advance(root,state,crash,20)
        d.reconcile(root);self.assertEqual(d.load(root)['status'],'STOPPED');self.assertEqual(d.load(root)['reserved_budget'],1)

    def test_confirmed_archive_recovery_continues_next_not_same_job(self):
        root,s=self.fixture_state()
        with mock_bridge(self.root) as state:
            j=self.jobs[0];state['raw']=json.dumps(self.witness(j))
            s['runs']=[{'index':1,'job':j,'status':'RESERVED','artifact':'run-001'}];s['reserved_budget']=1;d.save(root/'ledger.json',s)
            d.perform(j,root/'run-001',state['config'],offline=True)
            recovered=d.reconcile(root);self.assertEqual(recovered['status'],'READY');self.assertEqual(recovered['reserved_budget'],1)
            seen=[]
            d.advance(root,recovered,lambda j,p:(seen.append(j['planned_order']) or self.fake_result(2)),2)
            self.assertEqual(seen,[2]);self.assertEqual(state['decide_calls'],1)

    def test_grant_bound_to_batch_path_budget_and_no_replacement(self):
        root=self.root/'batch';s=d.prepare(root)
        grant={'generation_authorized':True,'batch_id':s['batch_id'],'output_root':s['root'],'order_sha256':s['order_sha256'],
               'max_dispatches':20,'deadline_s':180,'concurrency':1,'user_authorization_statement':'OFFLINE UNIT TEST ONLY; NEVER DISPATCH'}
        file=self.root/'fixture-grant.json';write(file,grant)
        for key,value in [('batch_id','wrong'),('max_dispatches',21),('concurrency',8),('deadline_s',90),('generation_authorized',False)]:
            bad=dict(grant,**{key:value});write(file,bad)
            with self.assertRaises(ValueError):d.authorize(copy.deepcopy(s),file)
        write(file,grant);bound=d.authorize(s,file);write(file,dict(grant,max_dispatches=19))
        with self.assertRaises(ValueError):d.authorize(bound,file)

    def test_strict_json_and_reused_session_stop(self):
        with mock_bridge(self.root) as state:
            valid=json.dumps(self.witness(self.jobs[0]))
            for i,raw in enumerate(['```json\n'+valid+'\n```',valid+' trailing','{"a":1,"a":2}','{"a":NaN}']):
                result,_,folder=self.invoke(state,self.jobs[0],f'strict-{i}',raw)
                self.assertEqual(result['status'],'NOT_SCORED');self.assertIsNone(result['score'])
                self.assertEqual((folder/'raw.txt').read_text(),raw)
        root,s=self.fixture_state()
        d.advance(root,s,lambda j,p:self.fake_result(1),20)
        self.assertEqual(s['reserved_budget'],2);self.assertEqual(s['status'],'STOPPED')
        self.assertEqual(s['runs'][-1]['assessment']['failure'],'REUSED_THREAD_ID')

    def test_seal_job_and_archive_integrity(self):
        fake=self.root/'seal.json';fake.write_text('{}')
        with patch.object(r,'SEAL',fake):
            with self.assertRaisesRegex(ValueError,'SEAL'):r.verify_frozen()
        with mock_bridge(self.root) as state:
            bad=copy.deepcopy(self.jobs[0]);bad['context_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'UNFROZEN'):r.Pilot02MacBridgeAdapter(state['config'],bad,offline_test=True)
            result,_,folder=self.invoke(state,self.jobs[0],'archive')
            self.assertEqual(result['status'],'VALID')
            (folder/'raw.txt').write_text('{}')
            self.assertEqual(r.assess(folder,self.jobs[0])['status'],'NOT_SCORED')

    def test_free_yaw_inverted_up_is_rejected_by_pilot02(self):
        with mock_bridge(self.root) as state:
            j=self.jobs[-1];prediction=copy.deepcopy(self.witness(j))
            # Inspect the schema-independent quaternion field recursively.
            def invert(value):
                if isinstance(value,dict):
                    for k,v in value.items():
                        if k=='quaternion_wxyz':
                            w,x,y,z=v;value[k]=[-x,w,z,-y]
                        else:invert(v)
                elif isinstance(value,list):
                    for v in value:invert(v)
            invert(prediction)
            result,_,folder=self.invoke(state,j,'inverted',json.dumps(prediction))
            self.assertEqual(result['status'],'VALID');self.assertEqual(result['score'],0)

    def test_lock_prevents_second_dispatcher(self):
        with d.lock():
            with self.assertRaises(ValueError):
                with d.lock():pass

    def test_real_adapter_requires_reservation_and_180(self):
        with mock_bridge(self.root) as state:
            a=r.Pilot02MacBridgeAdapter(state['config'],self.jobs[0])
            c,im,*_=r.job_input(self.jobs[0])
            with self.assertRaisesRegex(ValueError,'RESERVATION'):a.infer(c,im,self.root/'r',real=True)
            a._reserved_dispatch=True
            with self.assertRaisesRegex(ValueError,'180'):a.infer(c,im,self.root/'r',real=True,timeout_s=90)
            self.assertEqual(state['decide_calls'],0)

if __name__=='__main__':unittest.main()
