import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from real_hardware_gui import HardwareConsole
from astra_gui import Console
from experiment_launch import runner_args
class HardwareGUI(unittest.TestCase):
    def test_binding_does_not_dispatch(self):
        c=HardwareConsole(demo=True,demo_count=0)
        try:
            self.assertFalse(c.active);self.assertIsNone(c.process)
            self.assertTrue(c.state()['hardware_gui'])
            with patch.object(Console,'start',return_value={'started':True}) as start:
                c.start({'profile':'parallel','mode':'execute','task':'test','max_steps':1})
                self.assertEqual(start.call_args.args[0]['mode'],'execute')
            with self.assertRaises(ValueError):c.start({'profile':'legacy1','task':'test'})
        finally:c.close()
    def test_original_runner_and_execute_flag(self):
        s={'profile':'parallel','task':'test','max_steps':1,'mode':'shadow'}
        a=runner_args(s);self.assertTrue(a[0].endswith('run_parallel_arms.py'));self.assertNotIn('--execute',a)
        s['mode']='execute';self.assertIn('--execute',runner_args(s))
