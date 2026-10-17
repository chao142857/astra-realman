#!/usr/bin/env python3
"""Offline candidate hand-eye estimation from saved data; no hardware imports.

Reports camera -> SDK-reported endpoint, NOT verified flange/pad TCP/World.
Square scale is estimated from robot translation instead of assuming 15 mm.
No output is deployable calibration. Original observations stay unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rpy_rotation(rpy):
    return Rotation.from_euler("xyz", rpy).as_matrix()


def angular_deg(a, b):
    return float(np.degrees(Rotation.from_matrix(a.T @ b).magnitude()))


def pnp(points, k, distortion):
    grid = np.zeros((77, 3), dtype=np.float64)
    grid[:, :2] = np.mgrid[0:11, 0:7].T.reshape(-1, 2)
    ok, rv, tv = cv2.solvePnP(grid, points, k, distortion,
                             flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError("PNP_FAILED")
    r = cv2.Rodrigues(rv)[0]
    if np.min((r @ grid.T + tv).T[:, 2]) <= 0:
        raise ValueError("PNP_BEHIND_CAMERA")
    reprojection = cv2.projectPoints(grid, rv, tv, k, distortion)[0].reshape(-1, 2)
    rms = float(np.sqrt(np.mean(np.sum((points-reprojection)**2, axis=1))))
    return r, tv.reshape(3), rms


def handeye_rotation(samples, flips, ids):
    rr = [samples[i]["robot_R"] for i in ids]
    tt = [samples[i]["robot_t"].reshape(3, 1) for i in ids]
    cc = [samples[i]["camera_options"][flips[i]][0] for i in ids]
    ct = [samples[i]["camera_options"][flips[i]][1].reshape(3, 1) for i in ids]
    r, _ = cv2.calibrateHandEye(rr, tt, cc, ct, method=cv2.CALIB_HAND_EYE_PARK)
    if not np.isfinite(r).all() or abs(np.linalg.det(r)-1) > 1e-5:
        raise ValueError("HAND_EYE_ROTATION_INVALID")
    board_rotations = [rr[j] @ r @ cc[j] for j in range(len(ids))]
    y = Rotation.from_matrix(board_rotations).mean().as_matrix()
    errors = [angular_deg(y, br) for br in board_rotations]
    return r, y, float(np.sqrt(np.mean(np.square(errors))))


def solve(samples, flips, ids):
    r, y, rotation_rms = handeye_rotation(samples, flips, ids)
    a, b = [], []
    for i in ids:
        g = samples[i]
        c = g["camera_options"][flips[i]]
        # G_i X C_i(s) = Y; unknown x_t, y_t, square scale s.
        a.append(np.column_stack((g["robot_R"], -np.eye(3),
                                  g["robot_R"] @ r @ c[1])))
        b.append(-g["robot_t"])
    a, b = np.vstack(a), np.concatenate(b)
    value, _, rank, singular = np.linalg.lstsq(a, b, rcond=None)
    if rank != 7 or not np.isfinite(value).all() or value[6] <= 0:
        raise ValueError("TRANSLATION_SCALE_UNOBSERVABLE_OR_INVALID")
    x = np.eye(4); x[:3, :3] = r; x[:3, 3] = value[:3]
    board = np.eye(4); board[:3, :3] = y; board[:3, 3] = value[3:6]
    return x, board, float(value[6]), rotation_rms, singular


def residual(sample, flip, x, board, scale):
    cr, ct = sample["camera_options"][flip]
    actual_r = sample["robot_R"] @ x[:3, :3] @ cr
    actual_t = sample["robot_t"] + sample["robot_R"] @ (
        x[:3, 3] + x[:3, :3] @ (ct*scale))
    return {"translation_mm": float(np.linalg.norm(actual_t-board[:3, 3])*1000),
            "rotation_deg": angular_deg(board[:3, :3], actual_r)}


def choose_corner_order(samples):
    # Two physically equivalent origins of a symmetric 11x7 grid. Resolve only
    # per-view 180-degree order via fixed-board / measured-rotation consistency.
    flips = [0]
    for i in range(1, len(samples)):
        costs = []
        for option in (0, 1):
            costs.append(np.mean([
                (angular_deg(samples[j]["robot_R"], samples[i]["robot_R"]) -
                 angular_deg(samples[j]["camera_options"][flips[j]][0],
                             samples[i]["camera_options"][option][0]))**2
                for j in range(i)]))
        flips.append(int(np.argmin(costs)))
    ids = list(range(len(samples)))
    _, _, cost = handeye_rotation(samples, flips, ids)
    for _ in range(3):
        changed = False
        for i in range(1, len(flips)):
            trial = flips.copy(); trial[i] = 1-trial[i]
            try:
                _, _, trial_cost = handeye_rotation(samples, trial, ids)
            except ValueError:
                # A deliberately wrong symmetry assignment can produce a
                # reflection rather than a proper rotation; never adopt it.
                continue
            if trial_cost+1e-6 < cost:
                flips, cost, changed = trial, trial_cost, True
        if not changed:
            break
    return flips


def depth_square_estimate(folder, corners, depth_entry):
    depth_path = folder/depth_entry["depth_path"]
    if sha(depth_path) != depth_entry["depth_sha256"]:
        raise ValueError("DEPTH_HASH_MISMATCH")
    depth = np.load(depth_path, allow_pickle=False)
    k = np.array(depth_entry["aligned_depth_intrinsics"]["matrix"])
    points = []
    for u, v in corners:
        px, py = int(round(u)), int(round(v))
        patch = depth[max(0, py-2):py+3, max(0, px-2):px+3]
        valid = patch[np.isfinite(patch) & (patch > 0) & (patch < 65.534)]
        z = float(np.median(valid)) if len(valid) >= 5 else np.nan
        points.append([(u-k[0, 2])*z/k[0, 0], (v-k[1, 2])*z/k[1, 1], z])
    points = np.array(points).reshape(7, 11, 3)
    distance = np.concatenate((np.linalg.norm(np.diff(points, axis=0), axis=2).ravel(),
                               np.linalg.norm(np.diff(points, axis=1), axis=2).ravel()))
    distance = distance[np.isfinite(distance)]
    return {"adjacent_pairs": len(distance),
            "median_mm": float(np.median(distance)*1000) if len(distance) else None,
            "p10_p90_mm": (np.quantile(distance, [.1, .9])*1000).tolist() if len(distance) else None,
            "method": "5x5 depth median at RGB corners; aligned optical Z, no metric-accuracy certification"}


def load_samples(report, root):
    samples = []
    for run in report["runs"]:
        folder = root/Path(run["run"]).name
        for row in run["decimated_stationary_pose_candidates"]:
            path = folder/row["observation"]
            obs = json.loads(path.read_text())
            state = obs["state"]["canonical_states"]["left"]
            if state["system_error"]["has_error"] or not state["frame_snapshot_stable"]:
                raise ValueError("ROBOT_STATE_INVALID")
            if state["work_frame"]["name"] != "World" or state["tool_frame"]["name"] != "Arm_Tip":
                raise ValueError("FRAME_CHANGED")
            # Preserve the frame ambiguity, but reject non-zero offsets so the
            # resulting conditional transform is not silently misnamed.
            for frame in (state["work_frame"], state["tool_frame"]):
                pose = frame["pose"]
                if not np.allclose(pose["xyz_m"]+pose["rpy_rad"], 0, atol=1e-12):
                    raise ValueError("NONZERO_ACTIVE_OFFSET_REQUIRES_EXPLICIT_BINDING")
            image = folder/row["image"]
            if sha(image) != row["image_sha256"]:
                raise ValueError("RGB_HASH_MISMATCH")
            detector_path = path.parent/"board_corners.json"
            detector = json.loads(detector_path.read_text())["wrist"]
            if detector["image_sha256"] != row["image_sha256"]:
                raise ValueError("CORNER_RGB_BINDING_MISMATCH")
            points = np.array(detector["corners_px"], dtype=float)
            if points.shape != (77, 2) or not np.isfinite(points).all():
                raise ValueError("CORNER_SCHEMA_INVALID")
            d = next(d for d in obs["depth"] if d["camera"] == "wrist")
            intr = d["color_intrinsics"]
            coeff = np.array(intr["distortion_coefficients"])
            if not np.all(coeff == 0):
                raise ValueError("DISTORTION_MODEL_NEEDS_EXPLICIT_CONVERSION")
            k = np.array(intr["matrix"], dtype=float)
            r, t, rms = pnp(points, k, coeff)
            rz = np.diag([-1., -1., 1.])
            samples.append({"run": folder.name, "index": row["index"],
                "observation_id": obs["observation_id"], "observation_sha256": sha(path),
                "image_sha256": sha(image), "corners_sha256": sha(detector_path),
                "robot_R": rpy_rotation(state["ee_pose"]["rpy_rad"]),
                "robot_t": np.array(state["ee_pose"]["xyz_m"]),
                "camera_options": [(r, t), (r @ rz, t+r @ np.array([10., 6., 0.]))],
                "pnp_reprojection_rms_px": rms,
                "depth_square_estimate": depth_square_estimate(path.parent, points, d)})
    return samples


def synthetic_check():
    rng = np.random.default_rng(1011)
    x = np.eye(4); x[:3, :3] = Rotation.from_rotvec([.2, -.1, .3]).as_matrix(); x[:3, 3] = [.05, -.04, .08]
    y = np.eye(4); y[:3, :3] = Rotation.from_rotvec([.1, .3, -.5]).as_matrix(); y[:3, 3] = [-.3, .05, .01]
    square = .0157; data = []; expected_flips = []
    for i in range(16):
        g = np.eye(4); g[:3, :3] = Rotation.from_rotvec(rng.uniform(-.7, .7, 3)).as_matrix()
        g[:3, 3] = rng.uniform(-.4, .4, 3)
        c = np.linalg.inv(x) @ np.linalg.inv(g) @ y
        a, b = c[:3, :3], c[:3, 3]/square
        alt = (a @ np.diag([-1., -1., 1.]), b+a @ np.array([10., 6., 0.]))
        flip = int(i > 0 and i % 3 == 0); expected_flips.append(flip)
        data.append({"robot_R": g[:3, :3], "robot_t": g[:3, 3],
                     "camera_options": [(a, b), alt] if not flip else [alt, (a, b)]})
    flips = choose_corner_order(data)
    fit, _, scale, _, _ = solve(data, flips, list(range(len(data))))
    errors = {"rotation_deg": angular_deg(x[:3, :3], fit[:3, :3]),
              "translation_m": float(np.linalg.norm(x[:3, 3]-fit[:3, 3])),
              "square_m": abs(scale-square), "corner_order_exact": flips == expected_flips}
    if errors["rotation_deg"] > 1e-6 or errors["translation_m"] > 1e-8 or errors["square_m"] > 1e-8 or not errors["corner_order_exact"]:
        raise ValueError("SYNTHETIC_SELF_CHECK_FAILED:%s" % errors)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--fixed-board-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    if a.output.exists():
        raise ValueError("OUTPUT_EXISTS_REFUSE_OVERWRITE")
    evidence = json.loads(a.fixed_board_evidence.read_text())
    report = json.loads(a.report.read_text())
    if evidence.get("board_fixed_same_position_all_three_runs") is not True:
        raise ValueError("FIXED_BOARD_NOT_CONFIRMED")
    if sorted(evidence["runs"]) != sorted(Path(r["run"]).name for r in report["runs"]):
        raise ValueError("EVIDENCE_RUN_MISMATCH")
    selfcheck = synthetic_check()
    samples = load_samples(report, a.data_root)
    flips = choose_corner_order(samples)
    ids = list(range(len(samples)))
    x, y, scale, rotation_rms, singular = solve(samples, flips, ids)
    all_rows, loo = [], []
    for i, s in enumerate(samples):
        row = {k: v for k, v in s.items() if k not in ("robot_R", "robot_t", "camera_options")}
        row.update(corner_order_reversed=bool(flips[i]), fit_residual=residual(s, flips[i], x, y, scale))
        all_rows.append(row)
        xx, yy, ss, _, _ = solve(samples, flips, [j for j in ids if j != i])
        loo.append({"run": s["run"], "index": s["index"],
                    "held_out_residual": residual(s, flips[i], xx, yy, ss),
                    "camera_translation_change_mm": float(np.linalg.norm(xx[:3, 3]-x[:3, 3])*1000),
                    "camera_rotation_change_deg": angular_deg(x[:3, :3], xx[:3, :3]),
                    "estimated_square_mm": ss*1000})
    result = {"kind": "OFFLINE_CONDITIONAL_HAND_EYE_CANDIDATE_NOT_DEPLOYABLE",
        "status": "REVIEW_ONLY", "execution_permitted": False, "model_calls": 0, "hardware_commands_sent": 0,
        "source_report_sha256": sha(a.report), "source_evidence_sha256": sha(a.fixed_board_evidence),
        "source_script_sha256": sha(Path(__file__)), "numpy_version": np.__version__, "opencv_version": cv2.__version__,
        "synthetic_self_check": selfcheck, "samples": all_rows, "sample_count": len(samples),
        "equation": "G_i X C_i(square_scale) = constant Y; T_destination_source; column vectors",
        "G_semantics": "SDK-reported EE pose, identity m/rad; reference and endpoint still not independently bound",
        "rotation": "RPY radians, Rz(yaw) @ Ry(pitch) @ Rx(roll)",
        "X_semantics": "camera optical -> SDK-reported endpoint; NOT certified physical pad TCP/flange",
        "Y_semantics": "chessboard origin -> SDK-reported pose reference; NOT certified global lab World",
        "method": "OpenCV PARK rotation; linear joint solve of X_t, Y_t and square size; symmetric corner order reconciled using fixed-board/robot relative rotations",
        "corner_frame": "origin relative to first detector order, geometric 180-degree gauge; not a named physical board corner",
        "candidate_T_sdk_endpoint_camera_optical": x.tolist(),
        "candidate_T_sdk_reference_board": y.tolist(),
        "estimated_square_mm": scale*1000,
        "metric_size_source": "estimated from recorded robot translation; NOT measured or manufacturer-certified",
        "fit_rotation_rms_deg": rotation_rms, "linear_system_singular_values": singular.tolist(),
        "leave_one_out": loo,
        "validation_scope": "LOO holds out pose fitting; corner ordering and stationary selection used the full dataset. Not an independent new-acquisition validation.",
        "unknowns": ["physical square measurement", "SDK reference/endpoint binding", "actual pad-center TCP", "external hold-out acquisition", "absolute exposure synchronization"],
        "deployment": "Not written to runtime config, PublicStore registration or WH; original logs unchanged"}
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"samples": len(samples), "square_mm_estimated": scale*1000,
        "corner_reversed": sum(flips), "fit_rotation_rms_deg": rotation_rms,
        "fit_translation_rms_mm": float(np.sqrt(np.mean([s["fit_residual"]["translation_mm"]**2 for s in all_rows]))),
        "loo_translation_max_mm": max(r["held_out_residual"]["translation_mm"] for r in loo),
        "loo_rotation_max_deg": max(r["held_out_residual"]["rotation_deg"] for r in loo),
        "status": "REVIEW_ONLY; no deployed calibration"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
