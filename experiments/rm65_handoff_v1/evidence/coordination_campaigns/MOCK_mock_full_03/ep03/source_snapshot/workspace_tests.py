"""Zero-generation acceptance of task isolation, physical scoring and budget."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workspace_gate as g
from workspace_task import CRITERIA, policy
from evaluate_workspace import assess
from offline_tests import Protocol
from action_interface import context_from_observation, validate_context


class WorkspaceProtocol(Protocol):
    def setUp(self):
        super().setUp()
        self.context, self.images = context_from_observation(self.obs, [], task_id='shared_workspace_yield_v1',
            task_policy=policy(CRITERIA['nominal_initial_right_ready_world_wxyz']))

    def test_policy_and_instruction_are_immutable(self):
        for field in ('task_policy',):
            c=copy.deepcopy(self.context);c.pop(field)
            with self.assertRaises(ValueError):validate_context(c,self.images)
        c=copy.deepcopy(self.context);c['task_policy']['dwell_s']=.1
        with self.assertRaises(ValueError):validate_context(c,self.images)
        c=copy.deepcopy(self.context);c['task_policy']['initial_right_ready_world_wxyz'][0]+=.1
        with self.assertRaises(ValueError):validate_context(c,self.images)
        c=copy.deepcopy(self.context);c['instruction']+=' 左臂先退让。'
        with self.assertRaises(ValueError):validate_context(c,self.images)


class Permission(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='rm65-workspace-fixture-')
        self.root=Path(self.tmp.name)/'draft';self.state=g.prepare(self.root)
        self.auth=self.root/'fixture_grant.json';self.pre=self.root/'fixture_preflight.json';self.cfg=self.root/'fixture_config.json';self.cfg.write_text('{}')
        self.grant=json.loads((self.root/'authorization_REQUEST_NOT_GRANTED.json').read_text())
        self.grant.update(generation_authorized=True,max_dispatches=8,user_authorization_statement='UNIT FIXTURE ONLY; NO REAL GENERATION AUTHORIZATION')
        self.check={'status':'PASS','batch_id':self.state['batch_id'],'source_hashes':g.hashes(),'actual_hostname':'Ubuntu-Robot',
                    'bridge_config_sha256':g.original.sha(self.cfg),'client_timeout_s':180,'server_timeout_s':190,
                    'model':'gpt-6-astra','reasoning':'medium','non_generating_auth_and_tunnel_check':True,'checked_at':g.original.now()}
    def tearDown(self):self.tmp.cleanup()
    def open(self,stage='shadow'):
        self.auth.write_text(json.dumps(self.grant));self.pre.write_text(json.dumps(self.check))
        with patch('transfer_gate.socket.gethostname',return_value='Ubuntu-Robot'):
            return g.Gate(self.root,self.auth,self.pre,self.cfg,stage)
    def test_draft_and_old_scope_cannot_dispatch(self):
        self.grant['generation_authorized']=False
        with self.assertRaises(ValueError):self.open()
        with self.assertRaises(ValueError):g.new_root(g.ROOT/'evidence/transfer_runs/first_real_1100_20261015_01')
        with self.assertRaises(FileExistsError):g.prepare(self.root)
        self.assertEqual(json.loads((self.root/'ledger.json').read_text())['reserved_budget'],0)
    def test_total_8_stage_caps_and_shadow_first(self):
        for key,value in [('max_dispatches',9),('max_shadow_dispatches',2),('max_execute_dispatches',8)]:
            grant=copy.deepcopy(self.grant);self.grant[key]=value
            with self.assertRaises(ValueError):self.open()
            self.grant=grant
        with self.assertRaisesRegex(ValueError,'SHADOW_REQUIRED'):self.open('execute')
    def test_reservation_is_atomic_unknown_stops(self):
        gate=self.open();gate.reserve(self.root/'shadow/decision_000',{'fixture':True});gate.close()
        s=json.loads((self.root/'ledger.json').read_text());self.assertEqual(s['reserved_budget'],1)
        with self.assertRaisesRegex(ValueError,'NO_RESUME'):self.open()
        self.assertEqual(json.loads((self.root/'ledger.json').read_text())['status'],'STOPPED')
    def test_exactly_one_shadow_no_budget_replacement(self):
        gate=self.open();row=gate.reserve(self.root/'shadow/decision_000',{})
        row['status']='VALID';gate.state['shadow_validated']=True;gate.flush();gate.close()
        with self.assertRaisesRegex(ValueError,'SHADOW_ALREADY'):self.open()
        with patch('transfer_gate.accept_result',return_value={}):gate=self.open('execute')
        gate.close();self.grant['max_dispatches']=7
        with self.assertRaisesRegex(ValueError,'NO_REPLACEMENT'):self.open('execute')
    def test_stale_wrong_host_or_code_preflight(self):
        for key,value in [('checked_at','2020-01-01T00:00:00+00:00'),('actual_hostname','tongji-Precision-3680'),('source_hashes',{})]:
            previous=self.check[key];self.check[key]=value
            with self.assertRaises(ValueError):self.open()
            self.check[key]=previous
    def test_budget_exhaustion_is_not_reset(self):
        s=json.loads((self.root/'ledger.json').read_text())
        s.update(shadow_validated=True,reserved_budget=8,runs=[{'index':i+1,'stage':'shadow' if i==0 else 'execute','status':'VALID','artifact':'fixture/'+str(i)} for i in range(8)])
        g.original.save(self.root/'ledger.json',s)
        with patch('transfer_gate.accept_result',return_value={}):gate=self.open('execute')
        with self.assertRaisesRegex(ValueError,'BUDGET_EXHAUSTED'):gate.reserve(self.root/'extra',{})
        gate.close();self.assertEqual(json.loads((self.root/'ledger.json').read_text())['reserved_budget'],8)


def rows_fixture():
    ready=CRITERIA['nominal_initial_right_ready_world_wxyz'];left=CRITERIA['left_goal_world_wxyz'];right=CRITERIA['right_goal_world_wxyz']
    rows=[]
    def state(goal):return {'actual_grasp_center_world':goal[:3], 'flange_pose_world':goal, 'actual_pad_gap_m':.09}
    for lg,rg,n in [(left,ready,8),([.1,0,.3,1,0,0,0],right,6),(left,ready,26)]:
        for _ in range(n):rows.append({'step':len(rows)+1,'arms':{'left':state(lg),'right':state(rg)},'contacts':[]})
    return rows


class PhysicalScoring(unittest.TestCase):
    def score(self,rows,**kwargs):return assess(rows,.1,policy(CRITERIA['nominal_initial_right_ready_world_wxyz']),**kwargs)
    def test_order_and_full_terminal_window(self):
        rows=rows_fixture();self.assertTrue(self.score(rows)['pass'])
        rows[-10]['arms']['right']['actual_grasp_center_world']=[.1,.1,.1]
        self.assertFalse(self.score(rows)['checks']['final_goals_continuous_2s'])
    def test_initial_left_occupancy_is_not_later_credit(self):
        rows=rows_fixture()[:14];self.assertFalse(self.score(rows)['checks']['subsequent_left_dwell_0_5s'])
    def test_short_dwell_is_not_valid(self):
        rows=rows_fixture();del rows[8:10]
        self.assertFalse(self.score(rows)['checks']['right_dwell_0_5s'])
    def test_contacts_opening_and_protection_are_required(self):
        for names,key in [(['L__Link6','R__Link6'],'no_interarm_contact'),(['L__Link6','table'],'no_unexpected_arm_table_contact')]:
            rows=rows_fixture();rows[0]['contacts']=[{'names':names}]
            self.assertFalse(self.score(rows)['checks'][key])
        rows=rows_fixture();rows[0]['arms']['left']['actual_pad_gap_m']=.06
        self.assertFalse(self.score(rows)['pass'])
        self.assertFalse(self.score(rows_fixture(),safety_stop=True)['pass'])


if __name__=='__main__':unittest.main(verbosity=2)
