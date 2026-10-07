import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiment_launch import runner_args, validate
from astra_gui import step_evidence, Console, terminal_step
from io_utils import ROOT, write_json
from fixtures.synthetic_history import action

class ParallelGUI(unittest.TestCase):
    def setUp(self):
        (ROOT/'logs').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'logs');self.addCleanup(self.tmp.cleanup);self.step=Path(self.tmp.name)
        a=action();b=dict(a,arm='right',frame='realman:right:work:World',tool_frame='realman:right:tool:Arm_Tip')
        self.group={'done':False,'execution':'parallel','actions':[a,b]}
        write_json(self.step/'parsed_group.json',self.group)
    def test_launch_mapping_and_limits(self):
        s={'profile':'parallel','task':'unchanged $task','mode':'execute','max_steps':100,'wall_budget_s':7200}
        argv=runner_args(s,no_preview=True,lock_path='/tmp/gui-test.lock')
        self.assertTrue(argv[0].endswith('run_parallel_arms.py'));self.assertIn('--execute',argv)
        self.assertEqual(argv[argv.index('--time-budget-s')+1],'7200');self.assertNotIn('--model',argv)
        self.assertEqual(argv[argv.index('--task')+1],s['task'])
        with self.assertRaises(ValueError):validate(dict(s,max_steps=101))
        with self.assertRaises(ValueError):validate(dict(s,profile='legacy1'))
    def test_group_readback_not_conflated(self):
        for arm,code in [('left',0),('right',1)]:
            d=self.step/arm;d.mkdir();write_json(d/'worker_result.json',{'status':'EXECUTED' if code==0 else 'FAULT','hardware_commands_sent':1,'sdk_result':{'arm':code},'after_state':{'arm':arm}})
        row=step_evidence(self.step)
        self.assertEqual(row['arms']['left']['sdk_result']['arm'],0)
        self.assertEqual(row['arms']['right']['sdk_result']['arm'],1)
        self.assertEqual(row['action'],self.group)
        self.assertTrue(row['dispatch_started'])
    def test_claim_is_pending_not_success(self):
        d=self.step/'left';d.mkdir();write_json(d/'arm-dispatch.claim.json',{'command':'test'})
        row=step_evidence(self.step)
        self.assertEqual(row['arms']['left']['status'],'DISPATCH_STARTED_OUTCOME_PENDING')
        self.assertFalse(row['arms']['left']['sdk_result']);self.assertEqual(row['status'],'EXECUTING')
    def test_rejection_and_hold(self):
        self.group['actions']=self.group['actions'][:1];(self.step/'parsed_group.json').unlink();write_json(self.step/'parsed_group.json',self.group)
        write_json(self.step/'group_result.json',{'status':'REJECTED_IK','arms':{}})
        row=step_evidence(self.step)
        self.assertEqual(row['hardware_commands_sent'],0);self.assertFalse(row['dispatch_started'])
        self.assertEqual(row['arms']['right']['status'],'HELD')
    def test_new_pending_step_and_stop_error(self):
        (self.step/'parsed_group.json').unlink();write_json(self.step/'action_schema.json',{'properties':{'actions':{}}})
        row=step_evidence(self.step);self.assertFalse(row['model_output_valid'])
        row=terminal_step(row,{'status':'STOPPED','error':'SDK fault'})
        self.assertEqual(row['failure_reason'],'SDK fault')
    def test_requires_four_views_without_connecting_hardware(self):
        c=Console(demo=True);self.addCleanup(c.close)
        with patch.object(c.camera,'status',return_value=[{'available':True}]*3+[{'available':False}]):
            pre=c.preflight({'profile':'parallel','task':'test'})
            self.assertEqual(pre['required_camera_count'],4);self.assertFalse(pre['required_cameras_ready'])

if __name__=='__main__':unittest.main()
