import copy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
import pilot02_continuation as c
import pilot02_dispatcher as base
import pilot02_runtime as r
from pilot02_mock import mock_bridge

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        p=patch('subprocess.Popen',side_effect=AssertionError('NO_MODEL_SUBPROCESS'));p.start();self.addCleanup(p.stop)
        self.old={name:r.sha(r.MODULE/name) for name in r.read(c.PREP/'original_batch_hashes.json')}
    def tearDown(self):
        self.assertEqual(self.old,{name:r.sha(r.MODULE/name) for name in self.old})
    def prepare(self):
        root=self.root/'new';return root,c.prepare(root)
    def grant(self,s,n=8):
        return {'generation_authorized':True,'batch_id':s['batch_id'],'output_root':s['root'],'order_sha256':s['order_sha256'],
                'max_dispatches':n,'deadline_s':180,'concurrency':1,'user_authorization_statement':'OFFLINE TEST ONLY',
                'original_batch_id':s['original_batch_id'],'prior_client_dispatches':12,'continuation_manifest_sha256':c.MANIFEST_SHA}
    def test_exact_suffix_and_default_dry_run(self):
        root,s=self.prepare()
        self.assertEqual(s['jobs'],r.read(r.ORDER)['ordered_samples'][12:]);self.assertEqual(s['reserved_budget'],0)
        with patch.object(base,'perform',side_effect=AssertionError('NO_DISPATCH')):
            self.assertEqual(c.run(root)['original_orders'],list(range(13,21)))
            with self.assertRaises(ValueError):c.run(root,real=True)
        self.assertEqual(c.load(root)['status'],'DRY_RUN')
        with self.assertRaises(FileExistsError):c.prepare(root)
        with self.assertRaises(ValueError):c.prepare(c.OLD/'new')
    def test_old_grant_rejected_and_new_limit_eight(self):
        root,s=self.prepare();old=c.OLD/'authorization.json'
        with self.assertRaises(ValueError):c.authorize(copy.deepcopy(s),old)
        file=self.root/'fixture-grant.json'
        for n in [0,9,20,True]:
            r.write(file,self.grant(s,n))
            with self.assertRaises(ValueError):c.authorize(copy.deepcopy(s),file)
        r.write(file,self.grant(s));bound=c.authorize(s,file)
        r.write(file,self.grant(s,7))
        with self.assertRaises(ValueError):c.authorize(bound,file)
    def test_tampered_scope_and_twelfth_job_rejected(self):
        root,s=self.prepare();s['jobs'][0]=r.read(r.ORDER)['ordered_samples'][11];base.save(root/'ledger.json',s)
        with self.assertRaises(ValueError):c.load(root)
        root2=self.root/'another';s=c.prepare(root2);s['prior_client_dispatches']=0;base.save(root2/'ledger.json',s)
        with self.assertRaises(ValueError):c.load(root2)
    def test_preflight_binding_freshness_and_no_missing_gate_dispatch(self):
        root,s=self.prepare();config=self.root/'config.json';r.write(config,{'fixture':True});p=self.root/'preflight.json'
        valid={'status':'PASS','batch_id':s['batch_id'],'execution_host':'ubuntu-robot','continuation_manifest_sha256':c.MANIFEST_SHA,
               'bridge_config_sha256':r.sha(config),'server_timeout_s':190,'client_timeout_s':180,'single_worker':True,
               'non_generating_auth_and_tunnel_check':True,'model':'gpt-6-astra','reasoning':'medium','checked_at':datetime.now(timezone.utc).isoformat()}
        r.write(p,valid);c.check_preflight(s,p,config)
        for key,value in [('batch_id',s['original_batch_id']),('server_timeout_s',180),('model','other'),('checked_at',(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())]:
            r.write(p,dict(valid,**{key:value}))
            with self.assertRaises(ValueError):c.check_preflight(s,p,config)
        grant=self.root/'grant.json';r.write(grant,self.grant(s))
        with patch.object(base,'perform',side_effect=AssertionError('NO_DISPATCH')):
            with self.assertRaises(ValueError):c.run(root,real=True,authorization=grant,config=config)
        self.assertEqual(c.load(root)['reserved_budget'],0)
    def test_eight_real_protocol_fixtures_use_suffix_only(self):
        root,s=self.prepare();s.update(mode='OFFLINE_FIXTURE',status='READY');base.save(root/'ledger.json',s)
        seen=[]
        with mock_bridge(self.root) as mock:
            def runner(job,folder):
                self.assertEqual(c.load(root)['reserved_budget'],len(seen)+1)
                seen.append(job['planned_order'])
                scene=(r.MODULE/job['input_directory']).parent.parent
                mock['raw']=json.dumps(r.read(scene/'private/design_and_controls.json')['witness'])
                result=base.perform(job,folder,mock['config'],offline=True)
                self.assertEqual(result['score'],1);self.assertEqual(result,r.read(folder/'independent_rescore.json'))
                return result
            with base.lock():base.advance(root,s,runner,8)
            self.assertEqual(mock['decide_calls'],8);self.assertEqual(mock['cancel_calls'],0)
        self.assertEqual(seen,list(range(13,21)));self.assertEqual(s['status'],'BUDGET_EXHAUSTED')
        self.assertEqual(len(r.read(root/'paired_results.json')),4)
        with self.assertRaises(ValueError):base.advance(root,s,runner,8)
    def test_zero_continues_error_stops_without_retry(self):
        root,s=self.prepare();s.update(mode='OFFLINE_FIXTURE',status='READY');seen=[]
        def runner(job,folder):
            seen.append(job['planned_order'])
            return {'status':'VALID','score':0,'source':'FAKE_MAC_BRIDGE_NOT_ASTRA','thread_id':'fixture'} if len(seen)==1 else {'status':'NOT_SCORED','score':None,'source':'FAKE_MAC_BRIDGE_NOT_ASTRA'}
        with base.lock():base.advance(root,s,runner,8)
        self.assertEqual(seen,[13,14]);self.assertEqual(s['reserved_budget'],2);self.assertEqual(s['status'],'STOPPED')
        with self.assertRaises(ValueError):base.advance(root,s,runner,8)
    def test_posthoc_is_separate_and_old_batch_stays_stopped(self):
        post=r.read(c.PREP/'run12_posthoc_geometry.json');old=r.read(c.OLD/'ledger.json')
        self.assertEqual(post['posthoc_geometry']['score'],1)
        self.assertTrue(post['excluded_from_primary_scores_pairs_and_no_reconnect_latency'])
        self.assertEqual(old['status'],'STOPPED');self.assertEqual(old['reserved_budget'],12)
        self.assertEqual(r.read(c.OLD/'run-012/assessment.json')['status'],'NOT_SCORED')
        self.assertEqual(len(r.read(c.OLD/'paired_results.json')),5)

if __name__=='__main__':unittest.main()
