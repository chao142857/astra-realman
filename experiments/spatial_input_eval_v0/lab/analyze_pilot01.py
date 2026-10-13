#!/usr/bin/env python3
"""Read-only Pilot 01 analysis. No adapter, dispatcher, or model imports.

The old scores are inputs, never rewritten. Numeric sensitivity is a separate
post-hoc view. Running this script does not authorize or dispatch any request.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "evidence/pilot01_parallel180_20261013/primary_results.json"
OLD = ROOT / "evidence/pilot01_20261013"
NEW = ROOT / "evidence/pilot01_parallel180_20261013"
SUITE = ROOT / "evidence/lab_20261013/sim_suite_initial"
DEFAULT_OUTPUT = ROOT / "evidence/pilot01_analysis_20261013"
SLACK_M = 1e-8  # Uniform 10 nm analysis-only allowance, not a changed scorer.
THRESHOLDS_MM = (2, 5, 10, 20)
CONDITIONS = {"RGB_MULTI_VIEW": "A", "RGB_ORACLE_3D": "C"}
ERROR_METRICS = {
    "position": "position_vector_L2_m",
    "size": "size_vector_L2_m",
    "height": "height_scalar_absolute_m",
    "gap": "gap_scalar_absolute_m",
}


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def csv_save(path, rows):
    if not rows:
        path.write_text("")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def describe(values):
    values = list(values)
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def category(question):
    """Classifies required answer operation, not inaccessible model reasoning.

    Position/size are fields that C can directly read from Oracle geometry.
    A still has to infer them from RGB. Top/bottom height and gap are derived.
    """
    if question["type"] in ("relation", "fit"):
        return "relation_and_fit_judgment"
    if question["type"] in ("position", "size") or (
            question["type"] == "height" and question.get("reference") == "center"):
        return "direct_numeric_read"
    return "geometric_calculation"


def numeric_pass(error_m, threshold_m, slack_m=0):
    return error_m <= threshold_m + slack_m


def question_rows(primary):
    result = []
    for row in primary:
        if row["task_id"] != "understand":
            continue
        snapshot = read(SUITE / row["scene_id"] / "snapshot.json")
        task = next(task for task in snapshot["task"] if task["task_id"] == "understand")
        questions = {q["question_id"]: q for q in task["questions"]}
        for detail in row["evaluation"]["details"]:
            q = questions[detail["question_id"]]
            error = detail["geometric_error_m"]
            actual, expected = detail["actual"], detail["expected"]
            component = ([a - e for a, e in zip(actual, expected)]
                         if detail["type"] in ("position", "size") else None)
            # Recompute only the metric as an archive-integrity check; do not rescore.
            if error is not None:
                recomputed = math.sqrt(sum(x*x for x in component)) if component is not None else abs(actual-expected)
                if not math.isclose(error, recomputed, rel_tol=1e-12, abs_tol=1e-15):
                    raise ValueError("ARCHIVED_NUMERIC_METRIC_MISMATCH")
            result.append({
                "scene_id": row["scene_id"], "condition": CONDITIONS[row["condition"]],
                "question_id": detail["question_id"], "question_type": detail["type"],
                "answer_operation": category(q), "reference": q.get("reference"),
                "metric": ERROR_METRICS.get(detail["type"], "categorical_exact_match"),
                "expected": expected, "actual": actual, "signed_vector_error_m": component,
                "absolute_vector_component_error_m": [abs(x) for x in component] if component else None,
                "signed_scalar_error_m": actual-expected if error is not None and component is None else None,
                "error_m": error, "error_mm": error*1000 if error is not None else None,
                "original_tolerance_m": task["tolerance_m"],
                "original_correct": detail["within_tolerance"],
                "sensitivity_correct_uniform_10nm": (numeric_pass(error, task["tolerance_m"], SLACK_M)
                                                      if error is not None else detail["within_tolerance"]),
                "phase": "180s_four_worker" if row["deadline_s"] == 180 else "90s_serial",
                "artifact": str((NEW / row["artifact"]).resolve().relative_to(ROOT)),
            })
    return sorted(result, key=lambda row: (row["scene_id"], row["condition"], row["question_id"]))


def grouped(rows, keys, *, include_error=False):
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[k] for k in keys), []).append(row)
    result = []
    for group, members in sorted(groups.items()):
        correct = sum(r["original_correct"] for r in members)
        slack = sum(r["sensitivity_correct_uniform_10nm"] for r in members)
        item = dict(zip(keys, group))
        item.update(n=len(members), original_correct=correct,
                    original_accuracy=correct/len(members),
                    sensitivity_correct_uniform_10nm=slack,
                    sensitivity_accuracy_uniform_10nm=slack/len(members),
                    failed_questions=[r["scene_id"] + ":" + r["question_id"] for r in members if not r["original_correct"]])
        if include_error:
            metrics = {r["metric"] for r in members}
            if len(metrics) != 1:
                raise ValueError("DO_NOT_POOL_DIFFERENT_METRICS")
            errors = [r["error_mm"] for r in members if r["error_mm"] is not None]
            item.update({"error_mm_" + key: value for key, value in describe(errors).items()})
        result.append(item)
    return result


def threshold_rows(questions):
    rows = []
    for metric in ERROR_METRICS.values():
        for condition in ("A", "C"):
            members = [q for q in questions if q["metric"] == metric and q["condition"] == condition]
            for threshold in THRESHOLDS_MM:
                for name, slack in (("exact", 0), ("uniform_10nm", SLACK_M)):
                    correct = sum(numeric_pass(q["error_m"], threshold/1000, slack) for q in members)
                    rows.append(dict(metric=metric, condition=condition, threshold_mm=threshold,
                                     sensitivity=name, slack_m=slack, n=len(members), correct=correct,
                                     accuracy=correct/len(members)))
    return rows


def token_record(row):
    usage = row["token_usage"]
    if usage["reasoning_output_tokens"] > usage["output_tokens"]:
        raise ValueError("REASONING_IS_NOT_A_SUBSET_OF_OUTPUT")
    return {
        "scene_id": row["scene_id"], "task_id": row["task_id"],
        "condition": CONDITIONS[row["condition"]], "status": "VALID",
        "phase": "180s_four_worker" if row["deadline_s"] == 180 else "90s_serial",
        "deadline_s": row["deadline_s"], "worker_count": row["concurrency"],
        "input_tokens": usage["input_tokens"], "cached_input_tokens": usage["cached_input_tokens"],
        "cache_write_input_tokens": usage.get("cache_write_input_tokens"),
        "cached_input_fraction": usage["cached_input_tokens"]/usage["input_tokens"],
        "cache_hit": usage["cached_input_tokens"] > 0,
        "output_tokens": usage["output_tokens"], "reasoning_output_tokens": usage["reasoning_output_tokens"],
        "other_output_tokens": usage["output_tokens"]-usage["reasoning_output_tokens"],
        "client_wall_latency_s": row["latency_s"],
        "bridge_native_latency_s": row.get("audit", {}).get("native_latency_s"),
        "original_score": row["score"], "origin": row["origin"],
    }


TOKEN_METRICS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
                 "other_output_tokens", "client_wall_latency_s", "original_score")


def paired_tokens(records):
    scenes = sorted({r["scene_id"] for r in records})
    pairs = []
    for scene in scenes:
        by_condition = {r["condition"]: r for r in records if r["scene_id"] == scene}
        if set(by_condition) != {"A", "C"}:
            raise ValueError("PAIR_INCOMPLETE")
        a, c = by_condition["A"], by_condition["C"]
        pair = {"scene_id": scene, "phase_A": a["phase"], "phase_C": c["phase"],
                "cache_hit_A": a["cache_hit"], "cache_hit_C": c["cache_hit"],
                "exclude_from_no_cache_subset": a["cache_hit"] or c["cache_hit"]}
        for metric in TOKEN_METRICS:
            pair[metric + "_A"] = a[metric]
            pair[metric + "_C"] = c[metric]
            pair[metric + "_C_minus_A"] = c[metric]-a[metric]
        pairs.append(pair)
    stats = {}
    for subset, selected in (("all_six_pairs", pairs),
                             ("no_cache_hit_in_either_member", [p for p in pairs if not p["exclude_from_no_cache_subset"]])):
        stats[subset] = {"n_pairs": len(selected), "scenes": [p["scene_id"] for p in selected],
                         "metrics": {metric: {suffix: describe(p[metric + "_" + suffix] for p in selected)
                                               for suffix in ("A", "C", "C_minus_A")}
                                     for metric in TOKEN_METRICS}}
    return pairs, stats


def markdown_table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows])


def write_report(output, summary, types, scenes, boundary, stats):
    def type_total(kinds, condition):
        rows = [r for r in types if r["question_type"] in kinds and r["condition"] == condition]
        return f"{sum(r['original_correct'] for r in rows)}/{sum(r['n'] for r in rows)}"

    operation_display = [[label, type_total(kinds, "A"), type_total(kinds, "C"), unit]
                         for label, kinds, unit in (
                             ("关系 / 容纳判断", ("relation", "fit"), "判断题"),
                             ("直接数值读取（位置 / 尺寸）", ("position", "size"), "向量答案"),
                             ("几何计算（顶高 / 间隙）", ("height", "gap"), "标量答案"))]
    operation_display.append(["任务规划"] + [f"{summary['planning'][c]['valid']}/{summary['planning'][c]['n']}" for c in ("A", "C")] + ["完整规划几何合法性"])
    lines = ["# Pilot 01 离线分析（源提交 b103ee5）", "",
             "本目录只读取旧结果，真实生成请求为 **0**。旧 ledger、原始响应和评分均未改写。",
             "原始理解正确数保留为 **A 45/54，C 54/54**；规划几何合法率为 A 6/6、C 6/6。", "",
             "## 题型与场景", "",
             "“直接数值读取”按所需答案操作分类：位置和尺寸可直接由 C 的几何字段读取；A 仍需从 RGB 估计。"
             "这不是对模型内部推理过程的观察。顶面高度和物体间隙属于几何计算；关系和指定姿态容纳属于判断。", "",
             markdown_table(["操作类别", "A 原始", "C 原始", "计分单位"], operation_display), "",
             markdown_table(["题型", "A 原始", "C 原始", "误差定义"],
                 [[kind, next(f"{r['original_correct']}/{r['n']}" for r in types if r['question_type']==kind and r['condition']=='A'),
                   next(f"{r['original_correct']}/{r['n']}" for r in types if r['question_type']==kind and r['condition']=='C'),
                   ERROR_METRICS.get(kind, "分类完全匹配")] for kind in ("relation", "fit", "position", "size", "height", "gap")]), "",
             "[逐题误差](question_errors.csv)、[按操作类别](operation_accuracy.csv)、[按场景及类别](scene_operation_accuracy.csv)、"
             "[按场景及题型](scene_type_errors.csv)保留向量分量、L2 误差或标量误差。"
             "没有把位置、尺寸、顶面高度、间隙混成一个数值精度。", "",
             "![按场景分列的四种数值误差](numeric_errors_by_scene.png)", "",
             markdown_table(["场景", "A 原始", "C 原始", "A +10 nm 敏感性"],
               [[s, next(f"{r['original_correct']}/{r['n']}" for r in scenes if r['scene_id']==s and r['condition']=='A'),
                 next(f"{r['original_correct']}/{r['n']}" for r in scenes if r['scene_id']==s and r['condition']=='C'),
                 next(f"{r['sensitivity_correct_uniform_10nm']}/{r['n']}" for r in scenes if r['scene_id']==s and r['condition']=='A')]
                for s in sorted({r['scene_id'] for r in scenes})]), "",
             "## 浮点敏感性（分析视图，不替换评分）", "",
             "四个失败项的误差仅高于 5 mm 约 2–4 nm。统一采用 **10 nm（1e-8 m）** 的比较余量，"
             "它覆盖这四项的纳米级边界偏差，且比原 5 mm 阈值小 500,000 倍。"
             "余量对所有数值题、A/C 条件和阈值一视同仁；不四舍五入答案或 GT，不改变类别判断。"
             "这是观察数据后指定的数值敏感性分析，不是预注册评分，也不是普遍适用的模拟器误差上界。", "",
             f"在原 5 mm 阈值加统一余量后，独立敏感性视图为 **A {summary['sensitivity_uniform_10nm']['A']['correct']}/54，C 54/54**。"
             "原始 A 45/54 仍是冻结结果。", "",
             markdown_table(["场景", "题目", "误差 (mm)", "超出 5 mm (nm)"],
                [[r['scene_id'], r['question_id'], f"{r['error_mm']:.12f}", f"{r['excess_over_5mm_nm']:.6f}"] for r in boundary]), "",
             "[阈值曲线表](threshold_curves.csv)列出 2/5/10/20 mm，分别报告位置 L2、尺寸 L2、"
             "高度绝对误差和间隙绝对误差，每种指标每条件 n=6。严格阈值和 +10 nm 结果同时保存；"
             "类别判断未被加入数值误差曲线的分母。", "",
             "![严格阈值与统一数值余量的曲线](threshold_curves.png)", "",
             "## 理解请求的 token、缓存与耗时", "",
             "全部六对有效理解请求均来自 **180 秒、四 worker** 阶段。90 秒串行阶段仅有 S2 A "
             "理解请求超时，客户端等待 90.097 秒，token usage 未知，没有有效 A/C 对。"
             "因此不能用本数据估计并发或截止时间变更的因果效应，也没有将超时当零 token。", "",
             "S2 C 的 cached_input_tokens=7,040（input_tokens=12,298，约 57.25%）；其余有效理解请求缓存命中为 0。"
             "排除任一成员命中缓存的整个配对后剩 5 对，排除场景为 S2。缓存排除是一项描述性分层，不是随机对照。", ""]
    for label, key in (("全部六对", "all_six_pairs"), ("排除缓存命中配对，五对", "no_cache_hit_in_either_member")):
        m = stats[key]["metrics"]
        lines += ["### " + label, "", markdown_table(["指标（每请求均值）", "A", "C", "配对 C−A 均值"],
            [[metric, f"{m[metric]['A']['mean']:.3f}", f"{m[metric]['C']['mean']:.3f}", f"{m[metric]['C_minus_A']['mean']:.3f}"]
             for metric in ("input_tokens", "reasoning_output_tokens", "other_output_tokens", "client_wall_latency_s")]), ""]
    lines += ["[全部六对详情](understanding_pairs.csv)、[逐请求 token/cache/时间](understanding_requests.csv)、"
              "[各阶段请求计数](phase_counts.csv)和 [JSON 描述统计](token_descriptive_statistics.json)提供均值、中位数和范围。", "",
              "reasoning output 是报告的 output_tokens 的子集；其余输出=output−reasoning，缓存输入是 input 的子集。"
              "token 数是服务端报告的使用量，不代表精确内部计算量；0 reasoning tokens 不证明没有内部推理。"
              "客户端耗时包含传输、排队、并发资源竞争、服务与后处理等，不是纯模型计算时间。"
              "bridge native latency 也不能当作纯计算时间。单个请求/条件/场景，没有重复测量，只有探索性描述统计。", "",
              "## 规划", "",
              "[planning_results.csv](planning_results.csv)单独列出 12 份冻结规划结果及原约束评分，全部合法；"
              "这不证明最优路径或所有空间任务已解决。S4 规定目标姿态，不能视作自主朝向规划能力。"
              "原图与独立几何视图的回放、路径长度和余量见同一交付中的规划回放目录。", "",
              "## 复现", "", "```bash", "python3 experiments/spatial_input_eval_v0/lab/analyze_pilot01.py", "```", "",
              "该脚本不导入 adapter 或批次控制器，不执行 next/wave，不写旧 ledger。"
              "source_manifest.json 保存所读源文件 SHA256，并在输出完成后再次验证源文件未改变。", "",
              "绘图使用独立 matplotlib 3.10.7 环境，PNG/SVG/PDF 从 CSV 生成；"
              "复现命令和输入校验和见 [plot_manifest.json](plot_manifest.json)。主分析不需要额外 Python 依赖。", ""]
    (output / "REPORT.md").write_text("\n".join(lines))


def run(output):
    output = Path(output).resolve()
    protected = (OLD.resolve(), NEW.resolve(), SUITE.resolve())
    if any(output == path or path in output.parents for path in protected):
        raise ValueError("OUTPUT_MUST_BE_NEW_ANALYSIS_DIRECTORY")
    primary = read(PRIMARY)
    sources = [PRIMARY, OLD / "ledger.json", NEW / "ledger.json", OLD / "nonvalid_results.json",
               OLD / "runs/04_lab_s2_occlusion_understand_A/sample-0000/response.json"]
    sources += [SUITE / scene / "snapshot.json" for scene in sorted({r["scene_id"] for r in primary})]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    questions = question_rows(primary)
    if len(primary) != 24 or len(questions) != 108:
        raise ValueError("UNEXPECTED_FROZEN_PILOT01_SIZE")
    original = {c: {"correct": sum(r["original_correct"] for r in questions if r["condition"] == c), "n": 54} for c in ("A", "C")}
    if original != {"A": {"correct": 45, "n": 54}, "C": {"correct": 54, "n": 54}}:
        raise ValueError("FROZEN_ORIGINAL_SCORE_CHANGED")
    slack = {c: {"correct": sum(r["sensitivity_correct_uniform_10nm"] for r in questions if r["condition"] == c), "n": 54} for c in ("A", "C")}
    boundary = [dict(q, excess_over_5mm_nm=(q["error_m"]-0.005)*1e9) for q in questions
                if q["error_m"] is not None and not q["original_correct"] and q["sensitivity_correct_uniform_10nm"]]
    if len(boundary) != 4:
        raise ValueError("EXPECTED_FOUR_BOUNDARY_CASES")
    types = grouped(questions, ("question_type", "metric", "condition"), include_error=True)
    scenes = grouped(questions, ("scene_id", "condition"))
    records = [token_record(r) for r in primary if r["task_id"] == "understand"]
    pairs, stats = paired_tokens(records)
    timeout = read(sources[4])
    failed_request = {"scene_id": "lab_s2_occlusion", "task_id": "understand", "condition": "A",
                      "status": "TIMEOUT_NO_VALID_OUTPUT", "phase": "90s_serial", "deadline_s": 90, "worker_count": 1,
                      "input_tokens": None, "cached_input_tokens": None, "cache_write_input_tokens": None,
                      "cached_input_fraction": None, "cache_hit": None, "output_tokens": None,
                      "reasoning_output_tokens": None, "other_output_tokens": None,
                      "client_wall_latency_s": timeout["wall_latency_s"], "bridge_native_latency_s": None,
                      "original_score": None, "origin": "pilot01_new", "usage_status": "UNKNOWN"}
    phase_counts = [{"phase": "90s_serial", "condition": c, "valid_understanding": 0,
                     "infra_failure_understanding": int(c == "A"), "known_usage_requests": 0,
                     "cache_hit_requests": None, "completed_understanding_pairs": 0} for c in ("A", "C")]
    phase_counts += [{"phase": "180s_four_worker", "condition": c, "valid_understanding": 6,
                      "infra_failure_understanding": 0, "known_usage_requests": 6,
                      "cache_hit_requests": sum(r["cache_hit"] for r in records if r["condition"] == c),
                      "completed_understanding_pairs": 6} for c in ("A", "C")]
    planning = [{"scene_id": r["scene_id"], "condition": CONDITIONS[r["condition"]], "task_kind":
                 next(t["kind"] for t in read(SUITE / r["scene_id"] / "snapshot.json")["task"] if t["task_id"] == "plan"),
                 "original_score": r["score"], "original_success": r["evaluation"]["success"],
                 "constraints": r["evaluation"]["constraints"], "prediction": r["prediction"],
                 "phase": "180s_four_worker" if r["deadline_s"] == 180 else "90s_serial",
                 "artifact": str((NEW / r["artifact"]).resolve().relative_to(ROOT))}
                for r in primary if r["task_id"] == "plan"]
    summary = {"source_commit": "b103ee5577f6a3805ae18984dee9157ffa328849", "real_generation_requests": 0,
               "analysis_only": True, "original_understanding": original, "sensitivity_uniform_10nm": slack,
               "uniform_numeric_slack_m": SLACK_M, "boundary_cases": len(boundary),
               "planning": {c: {"valid": sum(r["original_success"] for r in planning if r["condition"] == c), "n": 6} for c in ("A", "C")},
               "valid_understanding_phase": "180s_four_worker", "valid_understanding_pairs": 6,
               "no_cache_understanding_pairs": stats["no_cache_hit_in_either_member"]["n_pairs"],
               "unknown_token_attempts": 1, "source_files_unchanged": True,
               "metric_definitions": ERROR_METRICS,
               "warnings": ["Sensitivity is post-hoc, original score unchanged", "Do not average different numerical error metrics",
                            "No inference about latent reasoning from answer-operation labels", "Tokens are not exact internal compute",
                            "Client/bridge wall latency is not pure model compute", "No significance or generalization claims"]}
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("question_errors", questions), ("type_errors", types), ("scene_accuracy", scenes),
        ("operation_accuracy", grouped(questions, ("answer_operation", "condition"))),
        ("scene_operation_accuracy", grouped(questions, ("scene_id", "answer_operation", "condition"))),
        ("scene_type_errors", grouped(questions, ("scene_id", "question_type", "metric", "condition"), include_error=True)),
        ("boundary_cases", boundary), ("threshold_curves", threshold_rows(questions)),
        ("understanding_requests", [failed_request] + records), ("understanding_pairs", pairs),
        ("phase_counts", phase_counts), ("planning_results", planning)):
        csv_save(output / (name + ".csv"), rows)
    save(output / "analysis_summary.json", summary)
    save(output / "token_descriptive_statistics.json", stats)
    save(output / "source_manifest.json", {"source_commit": summary["source_commit"], "sha256": hashes})
    write_report(output, summary, types, scenes, boundary, stats)
    if any(digest(ROOT / name) != checksum for name, checksum in hashes.items()):
        raise ValueError("SOURCE_CHANGED_DURING_ANALYSIS")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run(parser.parse_args().output)
