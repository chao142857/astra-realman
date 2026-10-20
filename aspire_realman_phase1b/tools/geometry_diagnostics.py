"""Independent standard preprocessing sensitivity on a sealed SAM3 RGB-D mask.

No model calls, hardware, object dimensions, location/depth priors, or automatic
target-component selection. Every connected component, including failures, stays
in the report. Uses NumPy plus the unchanged ASPIRE PCA OBB implementation.
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from rgbd_evidence import artifact, camera_points, load_snapshot


def distribution(values):
    values = np.asarray(values)
    if not len(values):
        return {"count": 0, "percentiles_m": None, "largest_adjacent_gaps_m": []}
    ordered = np.sort(values)
    gaps = np.diff(ordered)
    indices = np.argsort(-gaps, kind="stable")[:5]
    return {"count": len(values), "percentile_levels": [0, 1, 5, 25, 50, 75, 95, 99, 100],
            "percentiles_m": np.percentile(values, [0, 1, 5, 25, 50, 75, 95, 99, 100]).tolist(),
            "largest_adjacent_gaps_m": [{"lower_m": float(ordered[i]),
                "upper_m": float(ordered[i + 1]), "gap_m": float(gaps[i])} for i in indices]}


def erode_square(mask, iterations):
    result = mask.copy()
    h, w = mask.shape
    for _ in range(iterations):
        pad = np.pad(result, 1, constant_values=False)
        result = np.logical_and.reduce([pad[y:y+h, x:x+w] for y in range(3) for x in range(3)])
    return result


def components(adjacency):
    """All components in first-original-pixel order; no minimum-size deletion."""
    labels = np.zeros(len(adjacency), np.int32)
    group = 0
    for start in range(len(adjacency)):
        if labels[start]:
            continue
        group += 1
        labels[start] = group
        pending = deque([start])
        while pending:
            node = pending.popleft()
            neighbors = np.flatnonzero(adjacency[node] & (labels == 0))
            labels[neighbors] = group
            pending.extend(neighbors.tolist())
    return labels


def depth_components(z, v, u, max_jump_m):
    index = np.full(z.shape, -1, np.int32)
    index[v, u] = np.arange(len(v))
    labels = np.zeros(len(v), np.int32)
    h, w = z.shape
    group = 0
    for start in range(len(v)):
        if labels[start]:
            continue
        group += 1
        labels[start] = group
        pending = deque([start])
        while pending:
            i = pending.popleft()
            y, x = int(v[i]), int(u[i])
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if not (0 <= yy < h and 0 <= xx < w):
                        continue
                    j = int(index[yy, xx])
                    if j >= 0 and not labels[j] and abs(float(z[y, x]) - float(z[yy, xx])) <= max_jump_m:
                        labels[j] = group
                        pending.append(j)
    return labels


def euclidean_components(points, radius_m):
    n = len(points)
    adjacency = np.empty((n, n), bool)
    for begin in range(0, n, 128):
        delta = points[begin:begin+128, None, :] - points[None, :, :]
        adjacency[begin:begin+128] = np.einsum("ijk,ijk->ij", delta, delta) <= radius_m**2
    return components(adjacency)


def knn_mean_distance(points, k):
    means = np.empty(len(points))
    for begin in range(0, len(points), 128):
        stop = min(begin + 128, len(points))
        delta = points[begin:stop, None, :] - points[None, :, :]
        squared = np.einsum("ijk,ijk->ij", delta, delta)
        squared[np.arange(stop-begin), np.arange(begin, stop)] = np.inf
        nearest = np.partition(squared, k-1, axis=1)[:, :k]
        means[begin:stop] = np.sqrt(nearest).mean(axis=1)
    return means


def geometry(points, colors, frame):
    from cap_harness.contracts import PointCloud
    from cap_harness.geometry import estimate_geometry, quaternion_wxyz_to_matrix
    started = time.perf_counter()
    result = {"point_count": len(points), "obb": None, "error": None}
    if len(points):
        centered = points - points.mean(0)
        eigenvalues = np.linalg.eigvalsh(centered.T @ centered / len(points))[::-1]
        result["covariance_eigenvalues_m2"] = eigenvalues.tolist()
        scale = max(float(eigenvalues[0]), 1e-30)
        result["relative_adjacent_eigenvalue_gaps"] = (np.abs(np.diff(eigenvalues))/scale).tolist()
        result["pca_axis_ambiguity_warning"] = bool(np.any(np.abs(np.diff(eigenvalues))/scale < .05))
    try:
        g = estimate_geometry(PointCloud(points=points, colors=colors, frame=frame))
        rotation = quaternion_wxyz_to_matrix(g.pose.quaternion_wxyz)
        result["obb"] = {"center_m": g.pose.position.tolist(),
                         "quaternion_wxyz": g.pose.quaternion_wxyz.tolist(),
                         "axes_columns_in_optical_frame": rotation.tolist(),
                         "extents_m": g.extents.tolist(), "frame": frame}
    except ValueError as exc:
        result["error"] = str(exc)
    result["elapsed_ms"] = (time.perf_counter()-started)*1000
    return result


def pixel_bounds(v, u):
    if not len(v):
        return None
    return [int(u.min()), int(v.min()), int(u.max())+1, int(v.max())+1]


def audit_capture_assets(snapshot):
    capture = snapshot.resolve().parent.parent
    known = {"report.json"}
    for frame in ("first", "last"):
        known.update(f"{frame}/{name}" for name in ("snapshot.json", "rgb.png", "aligned-depth-m.npy", "aligned-z16.npy"))
    files = [{"relative_path": str(p.relative_to(capture)), "bytes": p.stat().st_size,
              "sha256": artifact(p)["sha256"]} for p in sorted(capture.rglob("*")) if p.is_file()]
    extra = [r["relative_path"] for r in files if r["relative_path"] not in known]
    report = json.loads((capture/"report.json").read_text())
    return {"capture_root": str(capture), "files": files, "unexpected_assets_requiring_review": extra,
            "unaligned_depth_image_identified": False if not extra else None,
            "assessment": "ONLY_ALIGNED_FIRST_LAST_PAYLOADS_SAVED" if not extra else "UNCLASSIFIED_EXTRA_ASSETS_NOT_ASSUMED_RAW_DEPTH",
            "raw_depth_intrinsics_metadata_present": "raw_depth" in report["profile"],
            "factory_extrinsics_metadata_present": "factory_depth_to_color" in report["profile"],
            "metadata_is_not_raw_depth_pixels": True,
            "reprojection_evidence_produced": False,
            "reason": "Aligned depth is not an invertible record of raw per-pixel returns, occlusion and alignment assignment; same-frame raw depth pixels were not saved."}


def compare_components(a, b):
    """Every overlapping pair; correspondence is not target identification."""
    pairs, counts = np.unique(np.column_stack((a["labels"], b["labels"])), axis=0, return_counts=True)
    ga = {g["component_id"]: g for g in a["report"]["groups"]}
    gb = {g["component_id"]: g for g in b["report"]["groups"]}
    rows = []
    for (ia, ib), count in zip(pairs, counts):
        if ia == 0 or ib == 0:
            continue
        x, y = ga[int(ia)], gb[int(ib)]
        row = {"from_component": int(ia), "to_component": int(ib), "shared_points": int(count),
               "jaccard": float(count/(x["kept_points"]+y["kept_points"]-count)),
               "from_fraction": float(count/x["kept_points"]), "to_fraction": float(count/y["kept_points"])}
        ox, oy = x["geometry"]["obb"], y["geometry"]["obb"]
        if ox and oy:
            ra = np.array(ox["axes_columns_in_optical_frame"])
            rb = np.array(oy["axes_columns_in_optical_frame"])
            row.update(center_distance_m=float(np.linalg.norm(np.array(ox["center_m"])-oy["center_m"])),
                extents_delta_m=(np.array(oy["extents_m"])-ox["extents_m"]).tolist(),
                sign_invariant_corresponding_axis_angles_deg=np.rad2deg(np.arccos(np.clip(np.abs(np.sum(ra*rb, axis=0)), 0, 1))).tolist(),
                pca_axes_may_swap_or_be_ambiguous=x["geometry"]["pca_axis_ambiguity_warning"] or y["geometry"]["pca_axis_ambiguity_warning"])
        rows.append(row)
    return {"from": a["report"]["id"], "to": b["report"]["id"], "all_overlapping_pairs": rows,
            "selection": "none; no nearest/largest component assumed to be target"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--aspire-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output.resolve().relative_to(root)
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.aspire_source / "src"))
    sys.path.insert(0, str(root / "aspire_realman_phase05/src"))
    started = time.perf_counter()
    baseline = json.loads(args.baseline_report.read_text())
    pred = baseline["runs"][2]["predictions"][0]
    mask_path = Path(pred["mask"]["path"])
    assert artifact(mask_path)["sha256"] == pred["mask"]["sha256"]
    rgb, z, meta, provenance = load_snapshot(args.snapshot)
    assert provenance["rgb_sha256"] == pred["source_rgb_sha256"]
    mask = np.array(Image.open(mask_path)) > 0
    points, v, u = camera_points(z, np.asarray(meta["intrinsics"]), mask)
    colors = rgb[v, u]
    if not 17 <= len(points) <= 10000:
        raise ValueError("BOUNDED_OFFLINE_DIAGNOSTIC_REQUIRES_17_TO_10000_POINTS_NO_SILENT_DOWNSAMPLE")
    capture_audit = audit_capture_assets(args.snapshot)
    protected = [args.baseline_report, mask_path, args.snapshot, args.snapshot.parent.parent/"report.json",
                 *[Path(a["path"]) for a in meta["assets"].values()]]
    before = {str(p): artifact(p)["sha256"] for p in protected}
    prepared_ms = (time.perf_counter()-started)*1000
    methods = []

    def add(name, family, parameters, labels, algorithm_ms, mask_pixels=None):
        group_start = time.perf_counter()
        groups = []
        for group_id in np.unique(labels[labels > 0]):
            chosen = labels == group_id
            geo = geometry(points[chosen], colors[chosen], meta["optical_frame"])
            groups.append({"component_id": int(group_id), "kept_points": int(chosen.sum()),
                "other_or_excluded_from_this_candidate": int((~chosen).sum()),
                "candidate_pixel_bounds_xyxy": pixel_bounds(v[chosen], u[chosen]),
                "depth": distribution(points[chosen, 2]),
                "complement_depth": distribution(points[~chosen, 2]), "geometry": geo,
                "selected_as_target": False})
        keep = labels > 0
        row = {"id": name, "family": family, "parameters": parameters,
               "label": "ASPIRE raw baseline" if family == "raw" else "ASPIRE + standard preprocessing (diagnostic only)",
               "kept_points": int(keep.sum()), "excluded_points": int((~keep).sum()),
               "invalid_depth_in_original_mask": int(mask.sum())-len(points),
               "mask_pixels_retained": mask_pixels,
               "excluded_rgb_pixel_bounds_xyxy": pixel_bounds(v[~keep], u[~keep]),
               "excluded_depth": distribution(points[~keep, 2]), "group_count": len(groups), "groups": groups,
               "failure": None if groups else "ALL_POINTS_EXCLUDED_NO_CANDIDATE_OBB",
               "group_order": "first original raster pixel, not depth or component size",
               "membership": {"artifact": "memberships.npz", "labels_key": name, "zero": "excluded by filter", "positive": "candidate ID; all groups retained"},
               "algorithm_ms": algorithm_ms, "geometry_and_statistics_ms": (time.perf_counter()-group_start)*1000,
               "target_selection": None, "accuracy_qualified": False, "world_pose": None}
        methods.append({"report": row, "labels": labels})

    add("raw", "raw", {}, np.ones(len(points), np.int32), 0.0, int(mask.sum()))
    computed = methods[0]["report"]["groups"][0]["geometry"]["obb"]
    original = pred["camera_geometry"]["obb"]
    for key in ("center_m", "extents_m", "quaternion_wxyz"):
        assert np.allclose(computed[key], original[key], atol=1e-9, rtol=0), "RAW_BASELINE_REPRODUCTION_MISMATCH"
    for radius in (1, 2, 3):
        t = time.perf_counter()
        eroded = erode_square(mask, radius)
        labels = eroded[v, u].astype(np.int32)
        add(f"erode_{radius}px", "mask_erosion", {"iterations": radius, "footprint": "3x3 square", "purpose": "sensitivity only; not tuned target prior"}, labels,
            (time.perf_counter()-t)*1000, int(eroded.sum()))
    for jump in (.005, .01, .02):
        t = time.perf_counter()
        labels = depth_components(z, v, u, jump)
        add(f"depth_cc_{jump*1000:g}mm", "depth_continuity", {"max_neighbor_z_jump_m": jump, "pixel_connectivity": 8, "invalid_pixels": "no edge, no interpolation"}, labels,
            (time.perf_counter()-t)*1000)
    for radius in (.005, .01, .02):
        t = time.perf_counter()
        labels = euclidean_components(points, radius)
        add(f"xyz_cc_{radius*1000:g}mm", "euclidean_3d_components", {"radius_m": radius, "minimum_component_deletion": None}, labels,
            (time.perf_counter()-t)*1000)
    t = time.perf_counter()
    means = knn_mean_distance(points, 16)
    knn_ms = (time.perf_counter()-t)*1000
    for multiplier in (1, 2, 3):
        t = time.perf_counter()
        threshold = float(means.mean()+multiplier*means.std())
        labels = (means <= threshold).astype(np.int32)
        add(f"sor_k16_std{multiplier}", "statistical_outlier_control", {"k": 16, "std_multiplier": multiplier, "mean_knn_distance_m": float(means.mean()),
                "std_knn_distance_m": float(means.std()), "std_ddof": 0, "derived_threshold_m": threshold, "shared_knn_computation_ms": knn_ms,
                "caveat": "density-dependent; coherent far components may survive"}, labels, (time.perf_counter()-t)*1000+knn_ms)

    comparisons = []
    for family in ("mask_erosion", "depth_continuity", "euclidean_3d_components", "statistical_outlier_control"):
        chain = [m for m in methods if m["report"]["family"] == family]
        if family in ("mask_erosion", "statistical_outlier_control"):
            chain = methods[:1]+chain
        comparisons.extend(compare_components(a, b) for a, b in zip(chain, chain[1:]))
    export_start = time.perf_counter()
    np.savez_compressed(args.output / "memberships.npz", xyz_m=points, u=u, v=v,
                        **{m["report"]["id"]: m["labels"] for m in methods})
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    yy, xx = np.nonzero(mask)
    crop = (max(0, int(xx.min())-8), max(0, int(yy.min())-8), min(mask.shape[1], int(xx.max())+9), min(mask.shape[0], int(yy.max())+9))
    sheet = Image.new("RGB", (1280, 4*260+40), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    palette = np.array([[25,220,130],[220,80,230],[30,150,250],[255,190,25],[255,100,70],[140,100,255],[25,200,220]])
    for i, method in enumerate(methods):
        row, labels = method["report"], method["labels"]
        overlay = rgb.copy()
        color = np.zeros((len(points), 3), np.uint8)
        if row["family"] in ("raw", "mask_erosion", "statistical_outlier_control"):
            color[labels > 0] = [0,240,160]
            color[labels == 0] = [255,35,70]
        else:
            color = palette[(labels-1) % len(palette)]
        overlay[v,u] = (rgb[v,u]*.25+color*.75).astype(np.uint8)
        path = args.output / (row["id"]+"-rgb-membership.png")
        Image.fromarray(overlay).save(path)
        row["rgb_membership_overlay"] = artifact(path)
        panel = Image.fromarray(overlay).crop(crop)
        panel.thumbnail((312,160))
        x, y = (i%4)*320, (i//4)*260+40
        sheet.paste(panel, (x+4,y+24))
        draw.text((x+4,y+3), row["id"], font=font, fill="black")
        draw.text((x+4,y+187), f'keep {row["kept_points"]}; exclude {row["excluded_points"]}',font=font,fill="black")
        draw.text((x+4,y+207), f'groups {row["group_count"]}; no target selected',font=font,fill="black")
        draw.text((x+4,y+227), f'algorithm {row["algorithm_ms"]:.2f}ms',font=font,fill="black")
    draw.text((8,10), "Independent diagnostics; filter green=keep/red=exclude; clusters=all IDs (colors repeat). No world or accuracy certificate.",font=font,fill="black")
    sheet.save(args.output / "geometry-diagnostics-preview.jpg", quality=88)
    export_ms = (time.perf_counter()-export_start)*1000
    after = {str(p): artifact(p)["sha256"] for p in protected}
    assert before == after, "SEALED_INPUT_CHANGED"
    report = {"status": "DIAGNOSTICS_ONLY_NO_TARGET_COMPONENT_SELECTION", "base_commit": "121631d96c316ab3e0e716d826ec0d14d4cffd79",
              "provenance": provenance, "mask": artifact(mask_path), "original_report": artifact(args.baseline_report),
              "raw_obb_reproduced_without_modification": True, "protected_sha256_before": before, "protected_sha256_after": after,
              "input_preparation_ms": prepared_ms, "point_count": len(points), "mask_pixels": int(mask.sum()),
              "methods": [m["report"] for m in methods], "parameter_stability": comparisons,
              "membership_artifact": artifact(args.output/"memberships.npz"), "preview": artifact(args.output/"geometry-diagnostics-preview.jpg"),
              "export_ms": export_ms, "total_elapsed_ms": (time.perf_counter()-started)*1000,
              "timing_scope": "one CPU diagnostic pass, no speed benchmark; algorithm and geometry/statistics separate; SOR shared kNN cost charged to each variant",
              "capture_asset_audit": capture_audit,
              "unaligned_depth_image_available_in_sealed_capture": capture_audit["unaligned_depth_image_identified"],
              "pollution_origin_identifiable_from_aligned_only": False,
              "world_pose": None, "geometry_accuracy_qualified": False, "graspability_qualified": False,
              "sam3_calls": 0, "hardware_connections": 0, "motion_dispatches": 0,
              "algorithm_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output/"geometry-diagnostics.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps({"output": str(args.output), "methods": len(methods), "point_count": len(points), "raw_obb_unchanged": True,
        "summary": [{"id": m["report"]["id"], "kept": m["report"]["kept_points"], "excluded": m["report"]["excluded_points"],
                     "groups": m["report"]["group_count"], "algorithm_ms": m["report"]["algorithm_ms"]} for m in methods]}, indent=2))


if __name__ == "__main__":
    main()
