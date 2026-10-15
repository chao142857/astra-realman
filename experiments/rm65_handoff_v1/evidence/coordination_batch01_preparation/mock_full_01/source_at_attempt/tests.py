"""Zero-generation acceptance: cumulative limits, isolation, scoring and protocol."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import action_interface as old
from offline_tests import Protocol
from workspace_tests import rows_fixture
from workspace_task import policy as old_policy,CRITERIA
from evaluate_workspace import assess as old_assess
from .contract import HERE,ORDER,policy,assess
from .interface import Adapter,context_from_observation,validate_context,transport
from .gate import Gate,Limit,prepare,hashes,save,now,sha


class CampaignProtocol(Protocol):
    def setUp(self):
        super().setUp()
        ready=json.loads((HERE/'ready_reference.json').read_text())
        self.context,self.images=context_from_observation(self.obs,[],policy('A_fixed',ready))
    def adapter(self):
        a=Adapter(self.config,offline_test=True);a.reserved=True;return a
    def infer(self):
        f=self.root/'run';r=self.adapter().infer(self.context,self.images,f)
        self.assertEqual(r['model_calls'],0);return f
    def test_protocol_failures(self):
        for mode in ['bad_json','incomplete','reconnect','drift','403','409']:
            with self.subTest(mode=mode):
                self.mode=mode;f=self.root/('run_'+mode);self.adapter().infer(self.context,self.images,f)
                with self.assertRaises((ValueError,FileNotFoundError)):old.accept_result(f)
    def test_auth_failure(self):
        self.token.write_text('wrong-synthetic-token-only')
        r=self.adapter().infer(self.context,self.images,self.root/'bad_auth')
        self.assertEqual(r['error'],'MAC_BRIDGE_HTTP_403')
    def test_no_real_dispatch(self):
        with self.assertRaises(ValueError):self.adapter().infer(self.context,self.images,self.root/'forbidden',real=True)
        with self.assertRaises(ValueError):Adapter(old.MacBridgeConfig('http://127.0.0.1:18766',self.token),offline_test=True)
        with self.assertRaises(ValueError):Adapter(self.config,offline_test=True).infer(self.context,self.images,self.root/'unreserved')
    def test_gt_and_image_rejected(self):
        cases=[]
        c=copy.deepcopy(self.context);c['observations']['oracle']={};cases.append(c)
        c=copy.deepcopy(self.context);c['attachments'][0]['sha256']='x';cases.append(c)
        c=copy.deepcopy(self.context);c['task_policy']['visit_order'].reverse();cases.append(c)
        c=copy.deepcopy(self.context);c['task_policy']['left_goal_world_wxyz'][0]+=.01;cases.append(c)
        c=copy.deepcopy(self.context);c.pop('task_policy');cases.append(c)
        c=copy.deepcopy(self.context);c['recent_history']=[{'proposal':{'done':True,'execution':'sequential','actions':[]},'receipt':{'witness':[]}}];cases.append(c)
        for c in cases:
            with self.assertRaises(ValueError):validate_context(c,self.images)
    def test_timeout_cancel_no_retry(self):
        a=self.adapter();calls=[]
        def post(path,*args):
            calls.append(path)
            if path=='/decide':raise TimeoutError('offline')
            return 200,b'{}'
        a._post=post;r=a.infer(self.context,self.images,self.root/'timeout')
        self.assertEqual(calls,['/decide','/cancel']);self.assertIn('COMPLETION_UNKNOWN',r['error'])
    def test_campaign_bounds_existing_http_timeout(self):
        a=self.adapter();a.deadline=time.monotonic()+.2
        with patch.object(transport.MacBridgeAdapter,'_post',return_value=(200,b'{}')) as post:
            a._post('/decide',b'{}','fixture',180)
            self.assertGreater(post.call_args.args[-1],0);self.assertLessEqual(post.call_args.args[-1],.2)
            a._post('/cancel',b'{}','fixture',3);self.assertEqual(post.call_args.args[-1],3)
        a.deadline=time.monotonic()-1
        with self.assertRaises(TimeoutError):a._post('/decide',b'{}','fixture',180)


class CampaignGate(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rm65-campaign-fixture-');self.root=Path(self.tmp.name)/'batch'
        self.state=prepare(self.root,offline=True);self.cfg=self.root/'config.json';self.cfg.write_text('{}')
        self.grant=json.loads((self.root/'authorization_REQUEST_NOT_GRANTED.json').read_text())
        self.grant.update(max_dispatches=50,offline_fixture=True)
        self.auth=self.root/'MOCK_PERMISSION_NOT_USER_AUTHORIZATION.json';save(self.auth,self.grant)
        self.check={'status':'PASS','campaign_id':self.state['campaign_id'],'source_hashes':hashes(),
                    'freeze_sha256':self.state['freeze_sha256'],'actual_hostname':'Ubuntu-Robot',
                    'bridge_config_sha256':sha(self.cfg),'non_generating_auth_and_tunnel_check':True,
                    'client_timeout_s':180,'server_timeout_s':190,'model':'gpt-6-astra','reasoning':'medium','workers':1,'checked_at':now()}
        self.pre=self.root/'mock_preflight.json';save(self.pre,self.check)
    def tearDown(self):self.tmp.cleanup()
    def open(self):return Gate(self.root,self.auth,self.pre,self.cfg,offline=True)
    def test_ungranted_cannot_run_real(self):
        with self.assertRaisesRegex(ValueError,'USER_AUTHORIZATION'):
            Gate(self.root,self.auth,self.pre,self.cfg,offline=False)
        self.assertEqual(json.loads((self.root/'ledger.json').read_text())['reserved_budget'],0)
    def test_no_prepare_reset_or_old_root(self):
        with self.assertRaises(FileExistsError):prepare(self.root)
        with self.assertRaises(ValueError):prepare(HERE.parent/'evidence/workspace_runs/old')
    def test_cross_episode_cumulative_50_and_7(self):
        g=self.open()
        for index in range(50):
            ep=g.state['episodes'][index//7]
            if ep['status']=='NOT_STARTED':
                if index:g.state['episodes'][index//7-1]['status']='SUCCESS'
                g.begin_episode(ep)
            row=g.reserve(ep,g.root/ep['episode_id']/f'd{index}',{})
            self.assertEqual(json.loads((self.root/'ledger.json').read_text())['reserved_budget'],index+1)
            row['status']='VALID';g.flush()
            if index==6:
                with self.assertRaisesRegex(Limit,'EPISODE_DECISION_LIMIT'):g.reserve(ep,g.root/ep['episode_id']/'extra',{})
        with self.assertRaisesRegex(Limit,'GLOBAL_DISPATCH_LIMIT'):g.check_new_dispatch()
        self.assertEqual(g.state['reserved_budget'],50);g.close()
    def test_clock_starts_once_and_crosses_episode_boundary(self):
        g=self.open();ep=g.state['episodes'][0];ep['status']='RUNNING'
        with patch('coordination_batch01.gate.time.monotonic',return_value=100.):
            row=g.reserve(ep,g.root/ep['episode_id']/'d1',{});row['status']='VALID';g.flush()
        ep['status']='SUCCESS';ep2=g.state['episodes'][1];g.begin_episode(ep2)
        with patch('coordination_batch01.gate.time.monotonic',return_value=3699.99):
            g.reserve(ep2,g.root/ep2['episode_id']/'d1',{})['status']='VALID';self.assertEqual(g.deadline,3700.)
        with patch('coordination_batch01.gate.time.monotonic',return_value=3700.):
            with self.assertRaisesRegex(Limit,'WALL_TIME_LIMIT'):g.check_new_dispatch()
        g.close()
    def test_unknown_finished_stopped_and_active_cannot_resume(self):
        g=self.open();ep=g.state['episodes'][0];ep['status']='RUNNING';g.reserve(ep,g.root/ep['episode_id']/'unknown',{})
        with self.assertRaisesRegex(ValueError,'LOCKED'):self.open()
        g.close()
        with self.assertRaisesRegex(ValueError,'NO_RESUME'):self.open()
        self.assertEqual(json.loads((self.root/'ledger.json').read_text())['status'],'STOPPED')
        for status in ('FINISHED','STOPPED','LIMIT_REACHED'):
            s=json.loads((self.root/'ledger.json').read_text());s['status']=status;save(self.root/'ledger.json',s)
            with self.assertRaisesRegex(ValueError,'NO_RESUME'):self.open()
    def test_changed_auth_order_source_and_preflight_rejected(self):
        for key,value in [('max_dispatches',51),('max_wall_s',3601),('workers',2),('workers',True),('max_shadow_dispatches',1)]:
            grant=dict(self.grant);grant[key]=value;save(self.auth,grant)
            with self.assertRaises(ValueError):self.open()
        save(self.auth,self.grant)
        for key,value in [('checked_at','2020-01-01T00:00:00+00:00'),('campaign_id','other'),('source_hashes',{})]:
            check=dict(self.check);check[key]=value;save(self.pre,check)
            with self.assertRaisesRegex(ValueError,'PREFLIGHT'):self.open()

    def test_cannot_start_or_dispatch_a_later_episode(self):
        g=self.open()
        with self.assertRaisesRegex(ValueError,'FROZEN_EPISODE_ORDER'):g.begin_episode(g.state['episodes'][1])
        g.begin_episode(g.state['episodes'][0])
        with self.assertRaisesRegex(ValueError,'FROZEN_EPISODE_ORDER'):g.begin_episode(g.state['episodes'][0])
        g.close()


class FrozenScoring(unittest.TestCase):
    def test_a_matches_old_physical_scoring(self):
        rows=rows_fixture();ready=json.loads((HERE/'ready_reference.json').read_text())
        new=assess(rows,.1,policy('A_fixed',ready));oldscore=old_assess(rows,.1,old_policy(CRITERIA['nominal_initial_right_ready_world_wxyz']))
        self.assertEqual(new['pass'],oldscore['pass'])
        self.assertEqual(list(new['checks'].values()),list(oldscore['checks'].values()))
        for names in (['L__Link6','R__Link6'],['L__Link6','table']):
            r=copy.deepcopy(rows);r[0]['contacts']=[{'names':names}]
            self.assertFalse(assess(r,.1,policy('A_fixed',ready))['pass'])
    def test_role_swap_and_initial_occupancy_not_credit(self):
        rows=rows_fixture();ready=json.loads((HERE/'ready_reference.json').read_text());p=policy('C_roles_swapped',ready)
        # Build left-first/right-second rows using public goals and Ready only.
        for i,r in enumerate(rows):
            for side in ('left','right'):
                goal=(p['left_goal_world_wxyz'] if side=='left' else p['right_goal_world_wxyz'])
                if side=='left' and i>=14:goal=ready['left']
                if side=='left' and i<8:goal=ready['left']
                r['arms'][side]={'actual_grasp_center_world':goal[:3],'flange_pose_world':goal,'actual_pad_gap_m':.09}
        self.assertTrue(assess(rows,.1,p)['pass'])
        self.assertFalse(assess(rows[:14],.1,p)['checks']['subsequent_second_dwell_0_5s'])
    def test_fixed_order_three_independent_repeats_each(self):
        self.assertEqual(ORDER['shadow_dispatches'],0)
        for cid in ('A_fixed','B_shift_y40','C_roles_swapped'):
            self.assertEqual(sorted(r['repeat'] for r in ORDER['order'] if r['condition_id']==cid),[1,2,3])
        self.assertEqual(len({r['episode_id'] for r in ORDER['order']}),9)


if __name__=='__main__':unittest.main(verbosity=2)
