import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parallel_diagnostics import decision_schema,decode_decision
from history_diagnostics import DIAGNOSTIC_FIELDS
from test_parallel_arms import states,group
from parallel_gui_evidence import group_evidence
from io_utils import write_json,ROOT
class PublicSummary(unittest.TestCase):
    def sample(self):return {'diagnostics':dict.fromkeys(DIAGNOSTIC_FIELDS,'证据不足，保持不确定。'),'action':group()}
    def test_unchanged_action(self):
        x=self.sample();d,g=decode_decision(json.dumps(x),states())
        self.assertEqual(g,x['action']);self.assertEqual(d,x['diagnostics'])
        self.assertEqual(decision_schema(states())['properties']['diagnostics']['required'],list(DIAGNOSTIC_FIELDS))
    def test_bad_summary_and_action_rejected(self):
        for v in ['', ' '*3,'x'*601,4]:
            x=self.sample();x['diagnostics']['scene_assessment']=v
            with self.assertRaises(ValueError):decode_decision(x,states())
        x=self.sample();x['action']['actions'][0]['frame']='shared_world'
        with self.assertRaises(ValueError):decode_decision(x,states())
    def test_gui_retains_raw_summary_without_action_execution(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"logs") as d:
            p=Path(d);x=self.sample();raw=json.dumps(x)
            (p/'raw_proposal.txt').write_text(raw)
            write_json(p/'parsed_group.json',x['action']);write_json(p/'diagnostics.json',x['diagnostics'])
            e=group_evidence(p)
            self.assertEqual(e['diagnostics'],x['diagnostics']);self.assertEqual(e['raw_proposal'],raw)
            self.assertIsNone(e['hardware_commands_sent']) # no execution receipt: preserve unknown
