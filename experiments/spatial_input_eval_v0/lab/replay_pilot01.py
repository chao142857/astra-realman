#!/usr/bin/env python3
"""Private offline diagnostic replay. No model adapter, network, or hardware imports.

Source RGB and Pilot 01 scores remain immutable. Image overlays use simulator
camera calibration; orthographic panels are explicitly diagnostic drawings.
"""
import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path

from spatial_eval.geometry import axes, corners, dot, norm, sub, swept_collision
from spatial_eval.scoring import evaluate

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / 'evidence/pilot01_parallel180_20261013/primary_results.json'
SUITE = ROOT / 'evidence/lab_20261013/sim_suite_initial'
EDGES = [(i, j) for i in range(8) for j in range(i + 1, 8)
         if bin(i ^ j).count('1') == 1]
COLORS = dict(target='#f04438', other='#4388ff', obstacle='#ecac55',
              region='#03adad', landing='#19e586', path='#fd64f1')


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def face_margins(region, held):
    """Exact signed corner-to-region-plane distances for convex oriented boxes."""
    values = []
    for i, axis in enumerate(axes(region['quaternion_wxyz'])):
        projections = [dot(sub(p, region['center_m']), axis) for p in corners(held)]
        values.extend([
            dict(face='local_' + 'xyz'[i] + '-', margin_m=min(projections) + region['size_m'][i]/2),
            dict(face='local_' + 'xyz'[i] + '+', margin_m=region['size_m'][i]/2 - max(projections)),
        ])
    return dict(minimum_m=min(v['margin_m'] for v in values), faces=values)


def sat_threshold(held, points, obstacle):
    """Bracket the first collision under the ORIGINAL SAT projection inflation.

    This scalar is NOT exact Euclidean object separation: clearance is added
    independently to each tested normalized SAT-axis projection radius.
    Continuous translation at the output's fixed orientation is checked.
    """
    segments = list(zip(points, points[1:])) if len(points) > 1 else [(points[0], points[0])]

    def collides(clearance):
        for start, end in segments:
            moving = dict(held, center_m=start)
            if swept_collision(moving, end, obstacle, clearance):
                return True
        return False

    if collides(0):
        return dict(noncollision_lower_m=None, collision_upper_m=0., collision_at_zero=True)
    low, high = 0., .001
    while not collides(high):
        high *= 2
        if high > 1e6:
            raise ValueError('SAT_THRESHOLD_UNBOUNDED')
    for _ in range(60):
        mid = (low + high)/2
        if collides(mid):
            high = mid
        else:
            low = mid
    return dict(noncollision_lower_m=low, collision_upper_m=high, collision_at_zero=False)


def margins_for(snapshot, task, prediction):
    truth = snapshot['ground_truth']
    objects = {b['id']: b for b in truth['objects']}
    regions = {b['id']: b for b in truth['regions']}
    c = task['constraints']
    held = copy.deepcopy(objects[prediction['object_id']])
    held.update(center_m=prediction['position_m'], quaternion_wxyz=prediction['quaternion_wxyz'])
    obstacles = {b['id']: b for b in truth['obstacles'] if b['id'] != held['id']}
    obstacles.update({k: b for k, b in objects.items() if k != held['id']})
    points = [c['start_position_m'], *prediction['waypoints_m']] if task['kind'] == 'path' else [held['center_m']]
    placement_sat = {k: sat_threshold(held, [held['center_m']], b) for k, b in obstacles.items()}
    path_sat = {k: sat_threshold(held, points, b) for k, b in obstacles.items()} if task['kind'] == 'path' else None

    def summarize_sat(details):
        if details is None:
            return None
        name, nearest = min(details.items(), key=lambda kv: kv[1]['collision_upper_m'])
        low = nearest['noncollision_lower_m']
        return dict(limiting_obstacle_id=name, **nearest,
                    excess_over_required_projection_clearance_m=None if low is None else low - c['clearance_m'],
                    per_obstacle=details)

    workspace = None
    if task['kind'] == 'path':
        vertex_margins = [face_margins(regions[c['workspace_region_id']], dict(held, center_m=p)) for p in points]
        workspace = dict(minimum_m=min(m['minimum_m'] for m in vertex_margins), at_vertices=vertex_margins,
                         method='Minimum over endpoints is sufficient for fixed-orientation translation in a convex box.')
    return dict(placement_region_face_margin=face_margins(regions[c['allowed_region_id']], held),
                required_sat_projection_clearance_m=c['clearance_m'],
                placement_sat_projection_clearance_threshold=summarize_sat(placement_sat),
                path_sat_projection_clearance_threshold=summarize_sat(path_sat),
                path_workspace_region_face_margin=workspace,
                path_length_m=sum(norm(sub(b, a)) for a, b in zip(points, points[1:])) if task['kind'] == 'path' else None,
                start_to_landing_displacement_m=norm(sub(points[-1], points[0])) if task['kind'] == 'path' else None,
                maximum_center_height_m=max(p[2] for p in points) if task['kind'] == 'path' else None,
                points_m=points, held_box_at_landing=held)


def project(point, calibration, cv_to_base):
    """Project base-frame point using archived OpenCV camera-to-base matrix."""
    delta = [point[i] - cv_to_base[i][3] for i in range(3)]
    cv = [sum(cv_to_base[i][j]*delta[i] for i in range(3)) for j in range(3)]
    if cv[2] <= 0:
        return None
    k = calibration['intrinsic']
    p = [dot(row, cv) for row in k]
    return (p[0]/p[2], p[1]/p[2])


def verify_projection(snapshot, matrices):
    """Cross-check private CV matrix against independently exported public pose."""
    errors = []
    points = [p for group in ('objects', 'regions', 'obstacles')
              for b in snapshot['ground_truth'][group] for p in corners(b)]
    for name, cal in snapshot['observations']['calibration'].items():
        pose = cal['pose_base_xyz_wxyz']
        forward, left, up = axes(pose[3:])
        for point in points:
            delta = sub(point, pose[:3])
            cv = [-dot(delta, left), -dot(delta, up), dot(delta, forward)]
            if cv[2] <= 0:
                continue
            p = [dot(row, cv) for row in cal['intrinsic']]
            uv = project(point, cal, matrices[name]['camera_cv_to_base'])
            errors.append(math.hypot(uv[0] - p[0]/p[2], uv[1] - p[1]/p[2]))
    maximum = max(errors)
    if maximum >= .01:
        raise ValueError('CAMERA_POSE_MATRIX_DISAGREEMENT')
    return dict(corner_projection_checks=len(errors), maximum_difference_px=maximum, threshold_px=.01,
                note='A consistency check of two exported camera representations, not a new calibration estimate.')


def fonts():
    from PIL import ImageFont
    for filename in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/Library/Fonts/Arial.ttf'):
        if Path(filename).exists():
            return (ImageFont.truetype(filename, 16), ImageFont.truetype(filename, 20))
    return ImageFont.load_default(), ImageFont.load_default()


def label(draw, position, text, color, font):
    x, y = position
    x = max(2, min(x, draw.im.size[0] - max(70, len(text)*9)))
    y = max(2, min(y, draw.im.size[1] - 22))
    bounds = draw.textbbox((x, y), text, font=font)
    draw.rectangle((bounds[0] - 2, bounds[1] - 2, bounds[2] + 2, bounds[3] + 2), fill='#111923')
    draw.text((x, y), text, fill=color, font=font)


def wire(draw, b, projection, color, width=2):
    vertices = [projection(p) for p in corners(b)]
    for i, j in EDGES:
        if vertices[i] is not None and vertices[j] is not None:
            draw.line([vertices[i], vertices[j]], fill=color, width=width)


def decorate(draw, snapshot, task, metrics, projection, font, show_labels=True):
    truth = snapshot['ground_truth']
    container_centers = []
    for region in truth['regions']:
        if region['id'] == task['constraints']['allowed_region_id']:
            wire(draw, region, projection, COLORS['region'], 2)
    for group in ('obstacles', 'objects'):
        for b in truth[group]:
            if b['id'] == 'table':
                continue
            color = COLORS.get(b['id'], COLORS['obstacle'])
            wire(draw, b, projection, color, 2)
            pos = projection(b['center_m'])
            if b['id'].startswith('container_'):
                container_centers.append(b['center_m'])
            elif pos and show_labels:
                label(draw, (pos[0] + 4, pos[1] + 4), b['id'], color, font)
    # Group the five container solids into one callout, keeping the RGB visible.
    if container_centers and show_labels:
        center = [sum(p[i] for p in container_centers)/len(container_centers) for i in range(3)]
        pos = projection(center)
        if pos:
            draw.line((pos[0], pos[1], pos[0] + 50, pos[1] - 32), fill=COLORS['obstacle'], width=1)
            label(draw, (pos[0] + 50, pos[1] - 50), 'container', COLORS['obstacle'], font)
    held = metrics['held_box_at_landing']
    wire(draw, held, projection, COLORS['landing'], 4)
    projected = [projection(p) for p in metrics['points_m']]
    for a, b in zip(projected, projected[1:]):
        if a and b:
            draw.line([a, b], fill=COLORS['path'], width=4)
    for i, point in enumerate(projected):
        if point:
            x, y = point
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=COLORS['path'])
            if len(projected) > 1 and show_labels:
                label(draw, (x + 5, y - 20), 'start' if i == 0 else 'P' + str(i), COLORS['path'], font)
    pos = projection(held['center_m'])
    if pos and show_labels:
        label(draw, (pos[0] + 6, pos[1] + 18), 'landing', COLORS['landing'], font)


def rgb_overlay(snapshot, scene_dir, task, metrics, camera, matrices, title):
    from PIL import Image, ImageDraw
    font, heading = fonts()
    original = next(a for a in snapshot['observations']['rgb'] if a['camera_id'] == camera)
    base = Image.open(scene_dir / original['path']).convert('RGB')
    canvas = Image.new('RGB', (640, 574), '#111923')
    canvas.paste(base, (0, 60))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 7), title + ' / ' + camera, font=heading, fill='white')
    draw.text((12, 34), 'Archived RGB + calibrated GT/output projections', font=font, fill='#e2e7ef')
    cal = snapshot['observations']['calibration'][camera]
    matrix = matrices[camera]['camera_cv_to_base']
    def projection(p):
        uv = project(p, cal, matrix)
        return None if uv is None else (uv[0], uv[1] + 60)
    decorate(draw, snapshot, task, metrics, projection, font)
    draw.rectangle((0, 540, 640, 574), fill='#111923')
    draw.text((12, 546), 'GT edges may be hidden in RGB; overlay is NOT model input.', font=font, fill='#d1d6df')
    return canvas


def geometry_view(snapshot, task, metrics, title):
    from PIL import Image, ImageDraw
    font, heading = fonts()
    canvas = Image.new('RGB', (640, 574), '#f5f7fb')
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 9), title + ' / independent geometry', font=heading, fill='#111923')
    draw.text((12, 38), 'Orthographic diagnostic; not a simulation RGB render', font=font, fill='#334155')
    # Identical metric scale in both views; fixed bounds across all six scenes.
    for view, origin, indices, low, high in [
        ('Top XY: x right, y up', (35, 85), (0, 1), (-.05, -.50), (.97, .48)),
        ('Side XZ: x right, z up', (345, 85), (0, 2), (-.05, -.03), (.97, .80)),
    ]:
        ox, oy = origin; width = 265; height = 360; scale = min(width/(high[0] - low[0]), height/(high[1] - low[1]))
        draw.rectangle((ox, oy, ox + width, oy + height), fill='white', outline='#ccd4df')
        def projection(p):
            return (ox + (p[indices[0]] - low[0])*scale, oy + height - (p[indices[1]] - low[1])*scale)
        for axis in (0, 1):
            for integer in range(-5, 11):
                v = integer*.1
                if not low[axis] <= v <= high[axis]:
                    continue
                if axis == 0:
                    x = ox + (v - low[0])*scale
                    draw.line((x, oy, x, oy + height), fill='#edf0f6')
                else:
                    y = oy + height - (v - low[1])*scale
                    draw.line((ox, y, ox + width, y), fill='#edf0f6')
        decorate(draw, snapshot, task, metrics, projection, font, show_labels=False)
        draw.text((ox - 8, oy + height + 9), view, font=font, fill='#334155')
        draw.text((ox - 8, oy + height + 30), 'Grid 0.1 m; identical scale', font=font, fill='#334155')
    draw.text((12, 515), 'Red=initial target; blue=other; amber=solid; teal=region', font=font, fill='#334155')
    draw.text((12, 540), 'Green=predicted landing box; magenta=center path', font=font, fill='#334155')
    return canvas


def render(output):
    from PIL import Image
    output.mkdir(parents=True, exist_ok=False)
    source_hashes = {str(PRIMARY.relative_to(ROOT)): sha(PRIMARY)}
    rows = [r for r in read(PRIMARY) if r['task_id'] == 'plan']
    assert len(rows) == 12
    records = []
    for row in sorted(rows, key=lambda r: (r['scene_id'], r['condition'])):
        scene = row['scene_id']; condition = 'A' if row['condition'] == 'RGB_MULTI_VIEW' else 'C'
        scene_dir = SUITE / scene; snapshot_path = scene_dir / 'snapshot.json'
        snapshot = read(snapshot_path); task = next(t for t in snapshot['task'] if t['task_id'] == 'plan')
        matrices_path = scene_dir / 'private/camera_matrices.json'; matrices = read(matrices_path)
        assert json.loads(row['raw_output']) == row['prediction'], 'RAW_PREDICTION_MISMATCH'
        assert evaluate(snapshot, task, row['prediction']) == row['evaluation'], 'FROZEN_SCORE_MISMATCH'
        projection_check = verify_projection(snapshot, matrices)
        metrics = margins_for(snapshot, task, row['prediction'])
        folder = output / (scene + '_' + condition); folder.mkdir()
        title = scene.replace('lab_', '') + ' / ' + condition
        panels = []
        for name in ('front', 'side', 'overhead'):
            panel = rgb_overlay(snapshot, scene_dir, task, metrics, name, matrices, title)
            panel.save(folder / (name + '_rgb_overlay.png')); panels.append(panel)
        panel = geometry_view(snapshot, task, metrics, title)
        panel.save(folder / 'independent_geometry.png'); panels.append(panel)
        sheet = Image.new('RGB', (1280, 1148), 'white')
        for i, panel in enumerate(panels):
            sheet.paste(panel, ((i % 2)*640, (i // 2)*574))
        sheet.save(folder / 'replay.png')
        source_files = [snapshot_path, matrices_path, *[scene_dir/a['path'] for a in snapshot['observations']['rgb']]]
        for source in source_files:
            source_hashes[str(source.relative_to(ROOT))] = sha(source)
        record = dict(scene_id=scene, condition=row['condition'], task_kind=task['kind'],
                      original_score=row['score'], original_evaluation=row['evaluation'],
                      prediction_unchanged=row['prediction'], original_artifact=row['artifact'],
                      calibration_consistency=projection_check, metrics=metrics,
                      replay=str((folder/'replay.png').relative_to(output)))
        write(folder/'replay.json', record); records.append(record)
    # Verify no source used by this operation was altered, including original RGB.
    assert all(sha(ROOT/p) == digest for p, digest in source_hashes.items())
    write(output/'source_hashes.json', source_hashes)
    write(output/'metrics.json', records)
    fields = ['scene_id', 'condition', 'original_score', 'task_kind', 'path_length_m',
              'placement_region_face_margin_m', 'placement_sat_projection_threshold_lower_m',
              'path_sat_projection_threshold_lower_m', 'path_workspace_region_face_margin_m']
    with (output/'planning_metrics.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for r in records:
            m = r['metrics']; path_sat = m['path_sat_projection_clearance_threshold']; workspace = m['path_workspace_region_face_margin']
            writer.writerow(dict(scene_id=r['scene_id'], condition=r['condition'], original_score=r['original_score'],
                                 task_kind=r['task_kind'], path_length_m=m['path_length_m'],
                                 placement_region_face_margin_m=m['placement_region_face_margin']['minimum_m'],
                                 placement_sat_projection_threshold_lower_m=m['placement_sat_projection_clearance_threshold']['noncollision_lower_m'],
                                 path_sat_projection_threshold_lower_m=None if path_sat is None else path_sat['noncollision_lower_m'],
                                 path_workspace_region_face_margin_m=None if workspace is None else workspace['minimum_m']))
    lines = ['# Pilot 01 私有规划回放与几何描述', '',
             '基线 b103ee5；12 份真实规划输出全部重评分与归档原评分逐字段一致，原始 12/12 成功保持不变。生成请求为 0。', '',
             '本目录只用于人类分析，包含独立 GT，不是模型输入。原图保持不变，叠加图由原始 RGB、冻结标定和原始模型输出离线生成。', '',
             '每份输出含三个原始相机视图的标注、一个独立正交几何诊断图和四面板回放。叠加的 GT 边可以穿过遮挡物；它们不是模型实际看见的像素。正交图不是 SAPIEN 渲染。', '',
             '## 指标定义', '',
             '- **区域面余量**：物体八个角点到允许区域六个内侧平面的最小有符号距离，单位 mm；正值表示完全位于区域内。这是区域面的几何量。',
             '- **SAT 投影阈值**：保持原 `swept_collision` 算法，寻找向每个单位 SAT 轴的投影半径和增加相同标量后，首次发生接触/碰撞的阈值。报告 60 次二分的无碰撞下界和碰撞上界；它**不是精确欧氏障碍距离**。下界减任务规定的 2 mm 是该同一投影规则下的附加余量。',
             '- **路径余量**：SAT 对全部连续线段检验，没有按稀疏点采样；固定姿态下，凸工作空间的区域面余量最小值出现在路径端点或折点。',
             '- **路径长度**：从题目给定起点、依次经过原始 waypoints 的中心折线长度。无路径任务记为不适用，不虚构搬运轨迹。不声称最优路径。', '',
             '| 场景 | 条件 | 原分数 | 路径 m | 落点区域面 mm | 落点 SAT 投影阈值 mm | 全路径 SAT 投影阈值 mm | 工作空间面 mm |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    def mm(v):
        return '—' if v is None else f'{v*1000:.6f}'
    for r in records:
        m = r['metrics']; path_sat = m['path_sat_projection_clearance_threshold']; workspace = m['path_workspace_region_face_margin']
        lines.append('| [{scene}]({link}) | {c} | {score:.1f} | {length} | {face} | {place} | {path} | {space} |'.format(
            scene=r['scene_id'], link=r['replay'], c=r['condition'], score=r['original_score'],
            length='—' if m['path_length_m'] is None else f"{m['path_length_m']:.3f}",
            face=mm(m['placement_region_face_margin']['minimum_m']), place=mm(m['placement_sat_projection_clearance_threshold']['noncollision_lower_m']),
            path=mm(None if path_sat is None else path_sat['noncollision_lower_m']), space=mm(None if workspace is None else workspace['minimum_m'])))
    lines += ['', 'S5 A/C 落点 y 分别为 0.145/0.150 m，均满足原任务。S6 A/C 均采用抬高绕障，最高中心 z 分别为 0.46/0.35 m，路径分别为 1.22/1.00 m；原任务没有最短路径或能耗目标。较短路径不等于已证明最优，二元合法率相同也不意味着几何信息无效。', '',
              'S4 的四元数由题目给定；该成功不作为自主朝向选择能力证据。规划任务不检查机器人可达性、动力学、抓取稳定性或支撑条件。', '',
              '## 复现', '',
              '在仓库根目录，使用包含 Pillow 的离线 Python：', '',
              '```bash', 'export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0"',
              'python experiments/spatial_input_eval_v0/lab/replay_pilot01.py --output /tmp/pilot01-replay-new', '```', '',
              '输出目录必须不存在。脚本只读取冻结数据和原始结果；不导入模型 adapter，不接触任何 ledger。源文件 SHA 和相机投影交叉校验记录见 JSON。', '']
    (output/'README.md').write_text('\n'.join(lines))
    write(output/'acceptance.json', dict(status='PASS', replay_count=12, original_rgb_overlay_count=36,
                                        independent_geometry_view_count=12, original_scores_unchanged=12,
                                        source_files_unchanged=len(source_hashes), new_generation_requests=0,
                                        hardware_connections=0, script_sha256=sha(__file__)))
    print(json.dumps(dict(status='PASS', outputs=12, original_scores_unchanged=12, new_generation_requests=0)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render(args.output)


if __name__ == '__main__':
    main()
