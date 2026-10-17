"""Zero generation/zero hardware migration acceptance."""
import copy
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from real_chunk_adapter import *
from real_chunk_gui import fixture, OfflineChunkConsole, chunk_evidence
from astra_gui import step_evidence


class ChunkMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def run_chunk(self, chunk=None, backend=None):
        return OfflineChunkAdapter(backend or FakeBackend()).run(json.dumps(chunk or fixture()),self.root/'step-001')
    def test_sequential_same_arm_measured_start_order_and_no_mutation(self):
        value=fixture();raw=json.dumps(value);result=self.run_chunk(value)
        a,b=result['operations'][:2]
        self.assertEqual(b['before'],a['after']);self.assertEqual(b['before']['sequence'],2)
        self.assertEqual([r['operation_index'] for r in result['operations']],[0,1,0,1])
        self.assertEqual((self.root/'step-001/raw_proposal.txt').read_text(),raw)
        self.assertEqual(result['hardware_commands_sent'],0)
        self.assertEqual(result['task_success'],'NOT_ASSESSED')
    def test_parallel_logical_batch(self):
        backend=FakeBackend();result=self.run_chunk(backend=backend)
        self.assertEqual(len(backend.calls[-1]),2)
        self.assertEqual([x[0] for x in backend.calls[-1]],['left','right'])
    def test_parallel_duplicate_rejects_before_any_dispatch(self):
        value=fixture();value['stages'][0]['mode']='parallel';backend=FakeBackend()
        result=self.run_chunk(value,backend)
        self.assertEqual(result['status'],'STOPPED');self.assertEqual(backend.calls,[])
        self.assertIn('DUPLICATE_ARM',result['reason'])
    def test_position_is_not_contact_or_grasp(self):
        result=self.run_chunk();receipt=result['operations'][2]['nodes'][0]['receipt']
        self.assertEqual(receipt['contact_hold_state'],'UNKNOWN')
        self.assertEqual(receipt['stable_grasp'],'NOT_ASSESSED')
    def test_hold_not_silently_downgraded(self):
        value=fixture();value['stages'][0]['actions']=[{'arm':'left','kind':'gripper','opening_fraction':.15,'contact_mode':'bilateral_hold'}]
        backend=FakeBackend();r=self.run_chunk(value,backend)
        self.assertEqual(r['status'],'REJECTED');self.assertEqual(backend.calls,[])
        self.assertEqual(r['operations'][0]['proposal']['opening_fraction'],.15)
    def test_unknown_stops_without_retry(self):
        class Unknown(FakeBackend):
            def execute_batch(self,batch):
                super().execute_batch(batch);return {'status':'UNKNOWN'}
        backend=Unknown();r=self.run_chunk(backend=backend)
        self.assertEqual(r['status'],'STOPPED');self.assertEqual(len(backend.calls),1)
        self.assertEqual(len(list((self.root/'step-001').glob('*-fake-dispatch.claim.json'))),1)
    def test_backend_stopiteration_is_unknown_not_completed(self):
        class Broken(FakeBackend):
            def execute_batch(self,batch):raise StopIteration('backend terminated')
        result=self.run_chunk(backend=Broken())
        self.assertEqual(result['status'],'STOPPED')
        self.assertEqual(result['operations'][0]['status'],'DISPATCH_RESERVED_OUTCOME_UNKNOWN')
    def test_actual_readback_not_nominal_endpoint(self):
        class Readback(FakeBackend):
            def execute_batch(self,batch):
                reply=super().execute_batch(batch)
                self.states['left']['tcp_world_wxyz'][2]=.299
                return reply
        result=self.run_chunk(backend=Readback())
        self.assertEqual(result['operations'][1]['before']['tcp_world_wxyz'][2],.299)
    def test_public_schema_is_exposed(self):
        self.assertEqual(SCHEMA['properties']['stages']['items']['properties']['actions']['maxItems'],2)
        self.assertIn('same arm may occur more than once',SCHEMA['properties']['stages']['items']['description'])
    def test_gui_controls_exist(self):
        from io_utils import ROOT
        html=(ROOT/'gui/index.html').read_text()
        for key in ('chunk-offline-controls','chunk-proposal','chunk-run','chunk-timeline','chunk-blockers'):
            self.assertEqual(html.count('id="'+key+'"'),1)
    def test_exception_after_dispatch_preserved(self):
        class Timeout(FakeBackend):
            def execute_batch(self,batch):
                super().execute_batch(batch);raise TimeoutError('completion unknown')
        backend=Timeout();r=self.run_chunk(backend=backend)
        self.assertEqual(r['status'],'STOPPED');self.assertEqual(len(backend.calls),1)
        self.assertIn('TimeoutError',r['reason'])
    def test_step_cannot_resume_or_overwrite(self):
        self.run_chunk()
        with self.assertRaises(FileExistsError):self.run_chunk()
    def test_hardware_mode_blocked_before_backend_read(self):
        with self.assertRaisesRegex(ValueError,'REAL_EXECUTION_BLOCKED'):OfflineChunkAdapter(FakeBackend(),mode='execute')
        with self.assertRaisesRegex(ValueError,'REAL_EXECUTION_BLOCKED'):OfflineChunkAdapter(object())
    def test_strict_json(self):
        for raw in ['{"done":true,"done":true,"stages":[]}','{"done":NaN,"stages":[]}','```json\n{}\n```']:
            with self.assertRaises(ValueError):parse_chunk(raw)
    def test_schema_shapes(self):
        for mutate in [lambda v:v.update(done=1),lambda v:v.update(extra=1),
                       lambda v:v['stages'][0].update(observe_s=-1),
                       lambda v:v['stages'][0]['actions'][0]['waypoints_world_wxyz'][0].__setitem__(3,0),
                       lambda v:v['stages'][1]['actions'][0].update(opening_fraction=True)]:
            v=fixture();mutate(v)
            with self.assertRaises(ValueError):parse_chunk(json.dumps(v))
    def test_done_not_success(self):
        r=self.run_chunk({'done':True,'stages':[]})
        self.assertEqual(r['status'],'MODEL_DONE_NOT_TASK_SUCCESS');self.assertEqual(r['task_success'],'NOT_ASSESSED')
    def test_observe_only(self):
        r=self.run_chunk({'done':False,'stages':[{'mode':'sequential','actions':[],'observe_s':.5}]})
        self.assertEqual(r['status'],'FAKE_COMPLETED');self.assertEqual(r['operations'],[])
    def test_subdivision_preserves_waypoints_and_caps(self):
        start=[0,0,0,1,0,0,0];end=[.02,0,0,math.cos(.05),0,0,math.sin(.05)]
        nodes=subdivide(start,[end]);self.assertEqual(nodes[-1]['target_world_wxyz'],end)
        previous=start
        for n in nodes:
            p=n['target_world_wxyz'];self.assertLessEqual(math.dist(previous[:3],p[:3]),.00500001);previous=p
        with self.assertRaisesRegex(ValueError,'SUBDIVISION_LIMIT'):subdivide(start,[[10,0,0,1,0,0,0]])
    def test_calibration_no_defaults_and_nonidentity_transform(self):
        q=[math.sqrt(.5),0,0,math.sqrt(.5)]
        # world_work rotated 90 degrees and translated; TCP 10 cm beyond tool.
        world_work=[1,2,0]+q;tool_tcp=[.1,0,0,1,0,0,0]
        world_tcp=compose(compose(world_work,[.3,.2,.4,1,0,0,0]),tool_tcp)
        result=sdk_target(world_tcp,world_work,tool_tcp)
        for a,b in zip(result,[.3,.2,.4,0,0,0]):self.assertAlmostEqual(a,b)
        with self.assertRaises(ValueError):sdk_target(world_tcp,None,tool_tcp)
    def test_singularity_rejected_not_reoriented(self):
        identity=[0,0,0,1,0,0,0]
        with self.assertRaisesRegex(ValueError,'SINGULARITY'):sdk_target([0,0,0,math.sqrt(.5),0,math.sqrt(.5),0],identity,identity)
    def test_gui_projects_all_operations_not_first_per_arm(self):
        self.run_chunk();r=step_evidence(self.root/'step-001')
        self.assertEqual(len(r['operations']),4)
        self.assertEqual([o['arm'] for o in r['operations']],['left','left','left','right'])
        self.assertEqual(r['hardware_commands_sent'],0)
    def test_gui_unknown_archive_does_not_claim_completion(self):
        step=self.root/'step-001';step.mkdir();save(step/'migration.json',{})
        self.assertEqual(chunk_evidence(step)['status'],'OUTCOME_UNKNOWN')
    def test_console_cannot_launch_hardware_or_model_even_mode_execute(self):
        console=OfflineChunkConsole();self.addCleanup(console.close);self.addCleanup(lambda:shutil.rmtree(console.session))
        with patch('astra_gui.subprocess.Popen',side_effect=AssertionError('no process')):
            result=console.start({'mode':'execute','profile':'parallel','raw_proposal':json.dumps(fixture())})
        self.addCleanup(lambda:shutil.rmtree(console.current_run))
        state=console.state();self.assertTrue(state['offline_chunk']);self.assertEqual(state['summary']['model_calls'],0)
        self.assertFalse(state['real_execution_ready'])
        self.assertFalse(any(c['available'] for c in state['camera_status']))
        self.assertFalse(load_json(console.current_run/'offline_manifest.json')['generation_authorized'])


def load_json(path):return json.loads(path.read_text())

if __name__=='__main__':unittest.main()
