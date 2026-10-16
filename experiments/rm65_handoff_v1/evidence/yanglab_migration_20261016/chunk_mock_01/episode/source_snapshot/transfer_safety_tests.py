"""Permission/metric unit fixtures only: no model, simulator, or network requests."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import transfer_gate as g
from evaluate_transfer import assess


class Permission(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rm65-transfer-fixture-');self.root=Path(self.tmp.name)/'draft'
        self.s=g.prepare(self.root);self.auth=self.root/'fixture_grant.json';self.pre=self.root/'fixture_preflight.json';self.cfg=self.root/'fixture_config.json';self.cfg.write_text('{}')
        self.grant=json.loads((self.root/'authorization_REQUEST_NOT_GRANTED.json').read_text())
        self.grant.update(generation_authorized=True,max_dispatches=16,user_authorization_statement='UNIT FIXTURE ONLY, NO ACTUAL GENERATION PERMISSION')
        self.check={'status':'PASS','batch_id':self.s['batch_id'],'source_hashes':g.hashes(),'actual_hostname':'tongji-Precision-3680',
            'bridge_config_sha256':g.sha(self.cfg),'client_timeout_s':180,'server_timeout_s':190,'model':'gpt-6-astra','reasoning':'medium',
            'non_generating_auth_and_tunnel_check':True,'checked_at':g.now()}
    def tearDown(self):self.tmp.cleanup()
    def open(self,stage='shadow'):
        self.auth.write_text(json.dumps(self.grant));self.pre.write_text(json.dumps(self.check))
        with patch('transfer_gate.socket.gethostname',return_value='tongji-Precision-3680'):
            return g.Gate(self.root,self.auth,self.pre,self.cfg,stage)
    def test_draft_cannot_generate_or_reset(self):
        self.grant['generation_authorized']=False
        with self.assertRaises(ValueError):self.open()
        with self.assertRaises(FileExistsError):g.prepare(self.root)
        self.assertEqual(json.loads((self.root/'ledger.json').read_text())['reserved_budget'],0)
    def test_maximum_16_and_shadow_first(self):
        self.grant['max_dispatches']=17
        with self.assertRaises(ValueError):self.open()
        self.grant['max_dispatches']=16
        with self.assertRaisesRegex(ValueError,'SHADOW_REQUIRED'):self.open('execute')
    def test_reservation_is_durable_unknown_is_stopped(self):
        gate=self.open();gate.reserve(self.root/'shadow/decision_000',{'fixture':True})
        state=json.loads((self.root/'ledger.json').read_text());self.assertEqual(state['reserved_budget'],1);self.assertEqual(state['runs'][0]['status'],'RESERVED')
        with self.assertRaisesRegex(ValueError,'OUTSTANDING'):gate.reserve(self.root/'parallel/decision_000',{})
        gate.close()
        with self.assertRaisesRegex(ValueError,'NO_RESUME'):self.open()
        state=json.loads((self.root/'ledger.json').read_text());self.assertEqual(state['status'],'STOPPED');self.assertEqual(state['reserved_budget'],1)
    def test_wrong_batch_and_stale_preflight(self):
        self.grant['batch_id']='OLD_BATCH'
        with self.assertRaises(ValueError):self.open()
        self.grant['batch_id']=self.s['batch_id'];self.check['checked_at']='2020-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'PREFLIGHT_REQUIRED'):self.open()
    def test_one_shadow_only_then_same_batch_execute(self):
        gate=self.open();row=gate.reserve(self.root/'shadow/decision_000',{'fixture':True})
        row['status']='VALID';gate.state['shadow_validated']=True;gate.flush()
        with self.assertRaisesRegex(ValueError,'SHADOW_ALREADY_DISPATCHED'):
            gate.reserve(self.root/'second_shadow/decision_000',{})
        gate.close()
        with self.assertRaisesRegex(ValueError,'SHADOW_ALREADY_DISPATCHED'):self.open('shadow')
        with patch('transfer_gate.accept_result',return_value={'fixture_only':True}):
            gate=self.open('execute')
        row=gate.reserve(self.root/'execute/decision_000',{'fixture':True})
        self.assertEqual(row['index'],2);self.assertEqual(gate.state['reserved_budget'],2);gate.close()
    def test_boolean_alone_does_not_establish_valid_shadow(self):
        state=json.loads((self.root/'ledger.json').read_text());state['shadow_validated']=True
        g.save(self.root/'ledger.json',state)
        with self.assertRaisesRegex(ValueError,'SHADOW_STATE_INCONSISTENT'):self.open('execute')


def physics_fixture():
    rows=[]
    for i in range(10):
        left=i<4;x=.1 if i>=6 else 0.
        pad='L__' if left else 'R__'
        rows.append({'step':i+1,'phase':'transfer_initial_left_hold' if left else 'fixture_action',
            'object_pose':[x,0,.2,1,0,0,0],'object_velocity':[.04,0,0],
            'arms':{'left':{'actual_grasp_center_world':[0,0,.2] if left else [-.05,0,.2],'flange_pose_world':[0,0,.4,1,0,0,0],'actual_pad_gap_m':.05 if left else .08},
                    'right':{'actual_grasp_center_world':[x,0,.2],'flange_pose_world':[x,0,.4,1,0,0,0],'actual_pad_gap_m':.05}},
            'bilateral_contact':{'left':left,'right':not left},
            'contacts':[{'names':['target_cube',pad+'ctag_'+s+'_Support_Link'],'points':[{'separation':-.0002,'impulse':[0,0,.1]}]} for s in ('Left','Right')]})
    return rows


class PhysicalMetricFixtures(unittest.TestCase):
    def test_physical_support_and_exit_required(self):
        rows=physics_fixture();self.assertTrue(assess(rows,.5)['transfer_only_pass'])
        for r in rows[4:]:r['bilateral_contact']['right']=False
        self.assertFalse(assess(rows,.5)['transfer_only_pass'])
    def test_left_support_is_not_handoff(self):
        rows=physics_fixture()
        for r in rows[4:]:r['contacts'].append(copy.deepcopy(rows[0]['contacts'][0]))
        self.assertFalse(assess(rows,.5)['checks']['right_independent_hold'])
    def test_drift_and_penetration_are_failures(self):
        rows=physics_fixture()
        for r in rows[5:]:r['arms']['right']['actual_grasp_center_world'][1]=.003
        self.assertFalse(assess(rows,.5)['transfer_only_pass'])
        rows=physics_fixture();rows[-1]['contacts'][0]['points'][0]['separation']=-.0023
        self.assertFalse(assess(rows,.5)['checks']['original_penetration_limit'])
    def test_holding_without_exit_not_success(self):
        rows=physics_fixture()
        for r in rows:r['object_pose'][0]=0;r['arms']['right']['actual_grasp_center_world'][0]=0
        result=assess(rows,.5);self.assertTrue(result['checks']['right_independent_hold']);self.assertFalse(result['checks']['right_held_exit'])


if __name__=='__main__':unittest.main(verbosity=2)
