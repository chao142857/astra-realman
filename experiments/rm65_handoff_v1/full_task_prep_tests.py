"""Zero-generation semantics and new-batch atomic permission tests."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import full_task_gate as g
from gripper_state_v3 import annotate
from numeric_action_chunk import public_receipt


class States(unittest.TestCase):
    def row(self,mode='bilateral_hold',latch=False,contact=False):
        r={'ok':False if mode=='bilateral_hold' and not (latch and contact) else True,
            'executed':True,'gripper_execution':{'left':{'contact_mode':mode,'latched':latch,'bilateral_contact_at_end':contact}}}
        if not r['ok']:r['reason']='GRIPPER_BILATERAL_HOLD_NOT_ESTABLISHED'
        return annotate(r)
    def test_position_is_command_success_not_grasp_claim(self):
        r=self.row('position');self.assertTrue(r['ok']);s=r['gripper_execution']['left']
        self.assertEqual(s['command_execution'],'EXECUTED');self.assertEqual(s['contact_hold_state'],'NOT_REQUESTED')
        self.assertEqual(s['stable_grasp'],'NOT_ASSESSED_BY_SERVO')
    def test_pending_hold_retains_raw_failure_and_is_recoverable(self):
        r=self.row();self.assertFalse(r['ok']);self.assertTrue(r['executed']);self.assertTrue(r['recoverable_action_feedback'])
        self.assertEqual(r['task_grasp_verdict'],'NOT_DETERMINED')
        clean=public_receipt(r);self.assertNotIn('latched',clean['gripper_execution']['left'])
        self.assertNotIn('bilateral_contact_at_end',clean['gripper_execution']['left'])
        self.assertIn('bilateral_contact_at_end',r['gripper_execution']['left'])
    def test_contact_hold_is_not_stable_lifted_grasp(self):
        r=self.row(latch=True,contact=True);self.assertTrue(r['ok'])
        self.assertEqual(r['gripper_execution']['left']['contact_hold_state'],'ESTABLISHED_AT_COMMAND_END')
        self.assertEqual(r['gripper_execution']['left']['stable_grasp'],'NOT_ASSESSED_BY_SERVO')
    def test_lost_contact_after_latch_not_established(self):
        self.assertFalse(self.row(latch=True)['ok'])


class Permission(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rm65-full-fixture-');self.root=Path(self.tmp.name)/'draft'
        self.state=g.prepare(self.root);self.auth=self.root/'fixture_grant.json';self.pre=self.root/'fixture_preflight.json'
        self.cfg=self.root/'fixture_config.json';self.cfg.write_text('{}')
        self.grant=json.loads((self.root/'authorization_REQUEST_NOT_GRANTED.json').read_text())
        self.grant.update(generation_authorized=True,max_dispatches=16,user_authorization_statement='UNIT FIXTURE ONLY, NO REAL PERMISSION')
        self.check={'status':'PASS','batch_id':self.state['batch_id'],'source_hashes':g.hashes(),'actual_hostname':'tongji-Precision-3680',
            'bridge_config_sha256':g.sha(self.cfg),'client_timeout_s':180,'server_timeout_s':190,'model':'gpt-6-astra','reasoning':'medium',
            'non_generating_auth_and_tunnel_check':True,'checked_at':'2026-01-01T00:00:00+00:00'}
        from transfer_gate import now
        self.check['checked_at']=now()
    def tearDown(self):self.tmp.cleanup()
    def open(self):
        self.auth.write_text(json.dumps(self.grant));self.pre.write_text(json.dumps(self.check))
        with patch('transfer_gate.socket.gethostname',return_value='tongji-Precision-3680'):
            return g.Gate(self.root,self.auth,self.pre,self.cfg)
    def test_draft_cannot_generate_or_reprepare(self):
        self.grant['generation_authorized']=False
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION_REQUIRED'):self.open()
        with self.assertRaises(FileExistsError):g.prepare(self.root)
        self.assertEqual(json.loads((self.root/'ledger.json').read_text())['reserved_budget'],0)
    def test_no_shadow_and_first_reservation_durable(self):
        gate=self.open();row=gate.reserve(self.root/'episode/decision_000',{'fixture':True})
        self.assertEqual(row['stage'],'execute');self.assertEqual(json.loads((self.root/'ledger.json').read_text())['reserved_budget'],1)
        with self.assertRaisesRegex(ValueError,'OUTSTANDING'):gate.reserve(self.root/'episode/decision_001',{})
        gate.close()
        with self.assertRaisesRegex(ValueError,'NO_RESUME'):self.open()
        self.assertEqual(json.loads((self.root/'ledger.json').read_text())['status'],'STOPPED')
    def test_budget_parameters_and_batch_binding(self):
        for key,val in [('max_dispatches',17),('workers',2),('model','other'),('batch_id','OLD')]:
            saved=copy.deepcopy(self.grant);self.grant[key]=val
            with self.assertRaises(ValueError):self.open()
            self.grant=saved
    def test_stale_or_wrong_host_preflight(self):
        self.check['checked_at']='2020-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'PREFLIGHT'):self.open()
    def test_source_change_and_stopped_no_resume(self):
        self.grant['source_hashes']={}
        with self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):self.open()
        self.grant['source_hashes']=self.state['source_hashes'];s=json.loads((self.root/'ledger.json').read_text())
        s['status']='STOPPED';g.save(self.root/'ledger.json',s)
        with self.assertRaisesRegex(ValueError,'NO_RESUME'):self.open()
    def test_budget_and_scope_never_touch_historical_roots(self):
        with self.assertRaisesRegex(ValueError,'NEW_FULL_TASK_ROOT'):g.new_root(g.ROOT/'evidence/transfer_runs/old')
        gate=self.open();gate.limit=0
        with self.assertRaisesRegex(ValueError,'BUDGET_EXHAUSTED'):gate.reserve(self.root/'episode/decision_000',{})
        gate.close()
    def test_real_adapter_without_reservation_never_posts(self):
        from chunk_handoff_task import ChunkAdapter
        from action_interface import MacBridgeConfig
        token=self.root/'fixture_token';token.write_text('not-real-credential')
        adapter=ChunkAdapter(MacBridgeConfig('http://127.0.0.1:18766',token),offline_test=False)
        with patch.object(adapter,'_post',side_effect=AssertionError('HTTP_MUST_NOT_RUN')):
            with self.assertRaisesRegex(ValueError,'AUTHORIZATION_REQUIRED'):adapter.infer({},[],self.root/'never',real=True)
    def test_reserved_adapter_is_context_bound_and_one_shot(self):
        from chunk_handoff_task import ChunkAdapter,transport
        from action_interface import MacBridgeConfig
        token=self.root/'fixture_token';token.write_text('unit-fixture-not-credential')
        adapter=ChunkAdapter(MacBridgeConfig('http://127.0.0.1:18766',token),offline_test=False)
        gate=self.open();folder=self.root/'episode/decision_000';ctx={'test':'NO_HTTP'}
        row=gate.reserve(folder,ctx);adapter._reservation=(gate,row)
        with patch.object(transport.MacBridgeAdapter,'infer',return_value={'fixture_only':True}) as base:
            adapter.infer(ctx,[],folder,real=True);self.assertEqual(base.call_count,1)
            with self.assertRaisesRegex(ValueError,'AUTHORIZATION_REQUIRED'):adapter.infer(ctx,[],folder,real=True)
        gate.close()
    def test_changed_context_cannot_use_reservation(self):
        from chunk_handoff_task import ChunkAdapter
        from action_interface import MacBridgeConfig
        token=self.root/'fixture_token';token.write_text('unit-fixture-not-credential')
        adapter=ChunkAdapter(MacBridgeConfig('http://127.0.0.1:18766',token),offline_test=False)
        gate=self.open();folder=self.root/'episode/decision_000';row=gate.reserve(folder,{'test':1})
        adapter._reservation=(gate,row)
        with patch.object(adapter,'_post',side_effect=AssertionError('NO_HTTP')):
            with self.assertRaisesRegex(ValueError,'INPUT_OR_SOURCE_CHANGED'):adapter.infer({'test':2},[],folder,real=True)
        gate.close()


if __name__=='__main__':unittest.main(verbosity=2)
