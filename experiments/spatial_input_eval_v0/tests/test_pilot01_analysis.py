"""Analysis guards: preserve archived judgments and keep different metrics apart."""
import importlib.util
import json
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "lab/analyze_pilot01.py"
SPEC = importlib.util.spec_from_file_location("pilot01_analysis_test_module", PATH)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


class Pilot01AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.primary = json.loads(analysis.PRIMARY.read_text())
        cls.questions = analysis.question_rows(cls.primary)

    def test_original_scores_preserved_and_four_boundary_items(self):
        a = [q for q in self.questions if q["condition"] == "A"]
        c = [q for q in self.questions if q["condition"] == "C"]
        self.assertEqual((len(a), sum(q["original_correct"] for q in a)), (54, 45))
        self.assertEqual(sum(q["sensitivity_correct_uniform_10nm"] for q in a), 49)
        changed = [q for q in a if q["sensitivity_correct_uniform_10nm"] != q["original_correct"]]
        self.assertEqual(len(changed), 4)
        self.assertTrue(all(0 < q["error_m"]-.005 < analysis.SLACK_M for q in changed))
        self.assertEqual(sum(q["original_correct"] for q in c), 54)

    def test_threshold_uniform_and_separate_metrics(self):
        rows = analysis.threshold_rows(self.questions)
        self.assertEqual(len(rows), 4*2*4*2)
        self.assertEqual({r["metric"] for r in rows}, set(analysis.ERROR_METRICS.values()))
        self.assertTrue(all(r["n"] == 6 for r in rows))
        self.assertFalse(analysis.numeric_pass(.005000002, .005))
        self.assertTrue(analysis.numeric_pass(.005000002, .005, analysis.SLACK_M))
        self.assertFalse(analysis.numeric_pass(.00502, .005, analysis.SLACK_M))
        with self.assertRaisesRegex(ValueError, "DO_NOT_POOL_DIFFERENT_METRICS"):
            analysis.grouped(self.questions, ("condition",), include_error=True)

    def test_answer_operation_is_not_model_reasoning_label(self):
        self.assertEqual(analysis.category({"type": "position"}), "direct_numeric_read")
        self.assertEqual(analysis.category({"type": "size"}), "direct_numeric_read")
        self.assertEqual(analysis.category({"type": "height", "reference": "center"}), "direct_numeric_read")
        self.assertEqual(analysis.category({"type": "height", "reference": "top"}), "geometric_calculation")
        self.assertEqual(analysis.category({"type": "gap"}), "geometric_calculation")
        self.assertEqual(analysis.category({"type": "fit"}), "relation_and_fit_judgment")

    def test_cached_pair_excluded_as_whole_pair_and_output_not_double_counted(self):
        records = [analysis.token_record(row) for row in self.primary if row["task_id"] == "understand"]
        pairs, stats = analysis.paired_tokens(records)
        self.assertEqual(stats["all_six_pairs"]["n_pairs"], 6)
        self.assertEqual(stats["no_cache_hit_in_either_member"]["n_pairs"], 5)
        self.assertEqual([p["scene_id"] for p in pairs if p["exclude_from_no_cache_subset"]], ["lab_s2_occlusion"])
        self.assertTrue(all(r["reasoning_output_tokens"] + r["other_output_tokens"] == r["output_tokens"] for r in records))
        self.assertEqual({r["phase"] for r in records}, {"180s_four_worker"})
        self.assertEqual(sum(r["cached_input_tokens"] for r in records), 7040)

    def test_refuses_writing_old_artifacts(self):
        for path in (analysis.OLD, analysis.NEW / "test", analysis.SUITE):
            with self.assertRaisesRegex(ValueError, "OUTPUT_MUST_BE_NEW_ANALYSIS_DIRECTORY"):
                analysis.run(path)


if __name__ == "__main__":
    unittest.main()
