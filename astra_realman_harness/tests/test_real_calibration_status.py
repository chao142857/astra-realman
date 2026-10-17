import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from real_calibration_status import inventory
from real_chunk_gui import OfflineChunkConsole

class CalibrationTests(unittest.TestCase):
    def test_missing_does_not_enable_execution(self):
        result=inventory('/missing/three.json')
        self.assertEqual(result['loaded_count'],1)
        self.assertTrue(result['errors'])
        self.assertFalse(result['real_execution_ready'])
    def test_tampered_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'three.json';p.write_text('{}')
            result=inventory(p)
            self.assertIn('SOURCE_HASH_MISMATCH',result['errors'][0])
    def test_console_remains_fake(self):
        c=OfflineChunkConsole()
        try:
            s=c.state();self.assertFalse(s['real_execution_ready'])
            self.assertFalse(s['live_readonly_cameras'])
            self.assertIn('calibration_inventory',s)
            self.assertTrue(c.preflight({})['offline_only'])
        finally:c.close()
