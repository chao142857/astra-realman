#!/usr/bin/env python3
"""Descriptive reporting from archived bytes only. No imports of inference code."""
import csv
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]/'evidence/pilot01_20261013'
A, C = 'RGB_MULTI_VIEW', 'RGB_ORACLE_3D'


def read(path): return json.loads(path.read_text())
def save(path, value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def mean(values): return sum(values)/len(values) if values else None
def fmt(value): return '—' if value is None else f'{value:.3f}'


def main():
    state=read(ROOT/'ledger.json'); primary=read(ROOT/'primary_results.json'); repeats=read(ROOT/'repeat_results.json')
    summary=read(ROOT/'summary.json'); attempted=[]; counts=Counter()
    for reservation in state['reservations']:
        folder=ROOT/reservation['directory']/'sample-0000'
        response=read(folder/'response.json') if (folder/'response.json').exists() else {}
        transport=read(folder/'transport.json') if (folder/'transport.json').exists() else {}
        if reservation['status']=='VALID': classification='valid'
        elif reservation['status']=='IN_FLIGHT': classification='in_flight'
        elif str(response.get('error','')).startswith('LOCAL_OUTPUT_VALIDATION:'): classification='invalid_output'
        elif response.get('return_code')==0 and not response.get('error') and response.get('raw'):
            rows=read(folder.parent/'results.json') if (folder.parent/'results.json').exists() else []
            classification='invalid_output' if rows and rows[0]['parse_status']=='INVALID' else 'protocol_or_completion_failure'
        else: classification='infrastructure_failure'
        counts[classification]+=1
        attempted.append(dict(index=reservation['index'], classification=classification,
            dispatched=transport.get('dispatch_attempts'), latency_s=response.get('wall_latency_s'),
            token_usage=response.get('usage'), failure=reservation.get('failure'), artifact=str(folder.relative_to(ROOT))))
    totals={}
    for label, rows in [('new_dispatches',attempted),('primary',primary),('independent_repeat',repeats)]:
        usages=[r.get('token_usage') for r in rows if isinstance(r.get('token_usage'),dict)]
        latencies=[r['latency_s'] for r in rows if r.get('latency_s') is not None]
        totals[label]=dict(samples=len(rows), known_usage_samples=len(usages),
            token_totals={k:sum(u.get(k,0) for u in usages) for k in ('input_tokens','output_tokens','reasoning_output_tokens','cached_input_tokens')},
            summed_client_latency_s=sum(latencies), mean_client_latency_s=mean(latencies))
    paired=[]; questions=[]
    for row in primary:
        for d in row['evaluation'].get('details',[]):
            questions.append(dict(scene_id=row['scene_id'],task_id=row['task_id'],condition=row['condition'],**d))
    for p in sorted((ROOT/'pairs').glob('*.json')) if (ROOT/'pairs').exists() else []:
        pair=read(p); a,c=pair['A'],pair['C']
        item=dict(scene_id=pair['scene_id'],task_id=pair['task_id'],score_A=a['score'],score_C=c['score'],
            **pair['delta_C_minus_A'],mean_numeric_error_m_A=a['evaluation'].get('mean_geometric_error_m'),
            mean_numeric_error_m_C=c['evaluation'].get('mean_geometric_error_m'))
        item['delta_numeric_error_m_C_minus_A']=(item['mean_numeric_error_m_C']-item['mean_numeric_error_m_A']
            if item['mean_numeric_error_m_C'] is not None and item['mean_numeric_error_m_A'] is not None else None)
        paired.append(item)
    pair_summary={}
    for task in ('understand','plan'):
        rows=[r for r in paired if r['task_id']==task]
        pair_summary[task]=dict(n=len(rows), C_higher=sum(r['score']>0 for r in rows), equal=sum(r['score']==0 for r in rows),
            A_higher=sum(r['score']<0 for r in rows),mean_score_delta_C_minus_A=mean([r['score'] for r in rows]),
            mean_latency_delta_s_C_minus_A=mean([r['latency_s'] for r in rows]),
            mean_input_token_delta_C_minus_A=mean([r['input_tokens'] for r in rows]),
            mean_output_token_delta_C_minus_A=mean([r['output_tokens'] for r in rows]))
    prior=state.get('prior_budget_consumed',0)
    metrics=dict(batch_status=state['status'], new_budget_reserved=len(state['reservations']),prior_budget_consumed=prior,
        cumulative_budget_reserved=prior+len(state['reservations']),
        known_http_dispatches=sum(r['dispatched'] or 0 for r in attempted),new_budget_remaining=24-prior-len(state['reservations']),
        new_sample_classifications=dict(counts),primary_valid=len(primary),completed_pairs=len(paired),
        totals=totals,paired_descriptive_statistics=pair_summary,attempts=attempted,paired_details=paired)
    save(ROOT/'research_metrics.json',metrics)
    with (ROOT/'understanding_questions.csv').open('w',newline='') as f:
        fields=['scene_id','task_id','condition','question_id','type','expected','actual','within_tolerance','geometric_error_m']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in questions:
            w.writerow({k:json.dumps(row[k],ensure_ascii=False) if k in ('expected','actual') else row[k] for k in fields})
    lines=['# Pilot 01 实际 A/C 评测','',
        f'批次状态：**{state["status"]}**。累计预算已保留 {prior+len(state["reservations"])}/24（前阶段 {prior} 次）；本阶段确认 HTTP 派发 {metrics["known_http_dispatches"]} 次。',
        f'新增结果分类：{json.dumps(dict(counts),ensure_ascii=False)}。主实验有效样本 {len(primary)}/24，完整配对 {len(paired)}/12；独立 S5 A 复测 {len(repeats)}/1。',
        '历史 S5 A（0091de8）原始文件未修改，不计新增预算。复测独立报告，不替换主配对。','',
        '| 类别 | 输入 | 有效任务 | 全部约束通过 | 平均任务分 | 数值题平均误差 m | 平均耗时 s |',
        '|---|---|---:|---:|---:|---:|---:|']
    for task in ('understand','plan'):
        for condition in (A,C):
            g=summary['groups'][task+'/'+condition]
            lines.append(f'| {task} | {"A" if condition==A else "C"} | {g["n"]} | {g["all_constraints_passed"]}/{g["n"]} | {fmt(g["mean_task_score"])} | {fmt(g.get("mean_numeric_error_m"))} | {fmt(g["mean_latency_s"])} |')
    lines+=['','空间理解题目正确率：','']
    for condition in (A,C):
        g=summary['groups']['understand/'+condition]
        lines.append(f'- {"A" if condition==A else "C"}：{g["correct_questions"]}/{g["questions"]}；按题型和米制误差见 summary.json、understanding_questions.csv。')
    lines+=['','| 场景 | 任务 | A 分数 | C 分数 | C−A 分数 | C−A 输入 token | C−A 输出 token | C−A 耗时 s |',
            '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in paired:
        lines.append(f'| {r["scene_id"]} | {r["task_id"]} | {fmt(r["score_A"])} | {fmt(r["score_C"])} | {fmt(r["score"])} | {r["input_tokens"]} | {r["output_tokens"]} | {fmt(r["latency_s"])} |')
    lines+=['','几何失败（完整原始答案与逐题 / 逐约束评分保存在各 sample-0000）：','']
    failures=[r for r in primary+repeats if r['error_types']]
    for r in failures:
        lines.append(f'- {r["scene_id"]}/{r["task_id"]}/{r["condition"]}：{", ".join(r["error_types"])}；score={r["score"]}。')
    if not failures: lines.append('- 已完成的有效样本中暂无几何失败。')
    lines+=['','独立 S5 A 复测：','']
    for r in repeats: lines.append(f'- score={r["score"]}；耗时 {r["latency_s"]:.3f}s；原始预测 `{json.dumps(r["prediction"],ensure_ascii=False)}`。')
    if not repeats: lines.append('- 尚未执行。')
    new=totals['new_dispatches']
    lines+=['',f'本阶段新增派发的已知 token 合计：input={new["token_totals"]["input_tokens"]}，output={new["token_totals"]["output_tokens"]}（reasoning 是 output 的子集，不重复相加）。已知客户端等待耗时合计 {new["summed_client_latency_s"]:.3f}s；并发时该值是各请求等待之和，并非批次墙钟耗时。包括历史样本的主实验统计另列于 research_metrics.json。',
        '', '所有 A/C 输入与历史配对均经冻结 payload、图像 SHA、任务、schema 和模型参数一致性核验。每个有效新样本均有独立 ephemeral thread、turn.completed、完整 CLI command、usage 与离线重评分审计。',
        '', 'S5/S6 为主要规划任务；S4 朝向由任务规定，不代表自主选择朝向。S5 历史 A 已满分，同分不等于几何信息无效。六个静态场景及其相关任务只支持探索性描述；不做统计显著性或总体泛化结论。评分不涵盖动力学、支撑稳定性、IK 或真实硬件。']
    if prior:
        lines+=['','用户在第 4 次（S2 A）90 秒超时后明确选择四个隔离 worker、180 秒的新阶段。累计预算未增加；先前超时保留且消耗一次。S2 A 新请求是明确授权后的独立重测。S5/S6 plan 的原 90 秒串行配对作为 carryover 保留，其他任务在 180 秒四并发阶段执行；各行保留 deadline_s/concurrency。不能把跨阶段延迟变化单独归因为几何信息。剩余 20 次若全部用于补齐主矩阵，则没有额外 S5 A 复测预算。']
    (ROOT/'research_report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:metrics[k] for k in ('batch_status','new_budget_reserved','known_http_dispatches','new_sample_classifications','completed_pairs')}))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['pilot01_20261013','pilot01_parallel180_20261013'],default='pilot01_20261013')
    args=parser.parse_args()
    ROOT=Path(__file__).resolve().parents[1]/'evidence'/args.phase
    main()
