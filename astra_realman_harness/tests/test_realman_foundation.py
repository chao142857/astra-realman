"""Preparation-only tests using existing fake adapters. Hardware/model calls=0."""
import importlib.util,json,sys,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.audit_realman_foundation import audit
import test_arm_mirror as mirror_fixture

class PreparationTests(unittest.TestCase):
    def test_static_audit_never_loads_sdk_or_opens_socket(self):
        with patch('socket.create_connection',side_effect=AssertionError('NO_NETWORK')),patch('importlib.util.spec_from_file_location',side_effect=AssertionError('NO_DRIVER_IMPORT')):
            a=audit()
        self.assertEqual(a['sdk_imports'],0);self.assertFalse(a['hardware_ready'])
        self.assertEqual(a['hardware_calls'],0);self.assertEqual(a['model_calls'],0)
        self.assertTrue(a['source_hashes']);self.assertEqual(len(a['differences']),5)
    def test_blocking_move_STOP_is_not_reported_as_inflight_hardware_stop(self):
        f=mirror_fixture.Tests();f.setUp()
        try:
            stop=threading.Event();adapter=f.adapter('left');adapter.stop=stop
            robot=f.robots['left'];original=robot.rm_movej_p
            def blocking_call(pose,*args):
                # Models STOP arrival after dispatch, before the blocking API returns.
                stop.set();return original(pose,*args)
            robot.rm_movej_p=blocking_call
            with self.assertRaisesRegex(RuntimeError,'HUMAN_STOP'):adapter.run(f.proposal('left'),'stop-during-call')
            self.assertEqual(len(robot.moves),1);self.assertEqual(f.grip_calls,[])
            # Existing route cannot claim it stopped the in-flight command.
            self.assertFalse(hasattr(robot,'hardware_stop_called'))
        finally:f.doCleanups()

if __name__=='__main__':unittest.main(verbosity=2)
