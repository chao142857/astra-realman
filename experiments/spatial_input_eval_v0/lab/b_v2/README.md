# B v2 task reliable geometry prototype

B v2 improves preservation of legal paths and placements, but does not yet provide a reliable complete collision environment. The independent six-scene experiment finds substantial gains from local heights and continuous plane boundaries, alongside missing-wall false acceptances. See [the evidence report](../../evidence/b_v2_20261014/REPORT.md).

This version was designed using the old four-scene B v1 GT audit. Those scenes are development diagnostics only. The six additional scenes use the same renderer, material conventions and camera arrangement with new geometry; they are a narrow synthetic validation set, not a new-domain generalization test.

## Components

- `estimate.py`: public RGB-D only, upright piecewise rectangular hypotheses. Geometry uses the existing schema; `reliability.json` is a separate public-derived record. No GT, segmentation, model or network access.
- `validation_suite.py`: six deterministic static SAPIEN scenes, three bounded paths and three free-yaw pockets. Uses the existing renderer. All six retained.
- `export_public.py`: whitelist export of RGB, depth, valid masks, camera calibration and A task context. Private scene data and segmentation are excluded.
- `evaluate.py`: independent GT diagnostics after sealing; original `pilot02_contract.score`, `contains`, `swept_collision`, SAT threshold helpers. No new collision algorithm.
- `ablate_errors.py`: private evaluation-only target/obstacle attribution. Its mixed worlds are not model inputs.
- `figures.py`: diagnostic figures, not model attachments.
- `verify_artifacts.py`: read-only integrity and historical preservation check.

## Estimation semantics

RGB red/gray masks are specific to this synthetic dataset. Depth is backprojected at the renderer's documented pixel centers. Surface normals and depth edges split local support. A 4 mm connectivity voxel links surface components; fitted continuous planes set boundaries. The voxel size is not measurement accuracy. Heights are inferred from each cell's visible top and outward-facing local side support, never a global bottom or GT.

Measured depth shells are observed surface; points ahead of a measured surface are observed free; occluded or unobserved points remain unknown. Interior solid boxes use an explicit upright-solid prior. Missing bottom faces are truncated to visible extent, tagged unknown, and not completed from GT. Free-ray probes can reject contradictory extrusion but cannot certify all box interiors. Absent boxes are not evidence of free space.

Each observed plane records support count, 95th-percentile residual, per-view medians, view disagreement and a pixel-footprint-based uncertainty proxy. The proxy is not a calibrated confidence bound. A missing face or weak/single-view support is insufficient for 2 mm certification. In the tested data every complete solid has an insufficient-reliability flag. The legacy box-only scorer ignores that sidecar: reported raw acceptance is a hypothesis check, not a safe execution decision.

There is a known coverage limitation: top cells with inadequate samples can be omitted without an individually enumerated rejected-cell record. A `missing: []` list therefore does not assert full coverage. Global unknown semantics remain necessary. Do not use this prototype as a robot collision map. The estimator is frozen despite these validation findings.

## Offline reproduction on ubuntu-robot

Use fresh output directories; commands reject existing estimate directories. These commands perform no model inference. Do not run historical batch dispatchers.

```bash
cd /home/alex/astra-realman_ws/spatial-b-v2-20261014
export PYTHONPATH="$PWD/experiments/spatial_input_eval_v0:$PWD/experiments/spatial_input_eval_v0/lab"
PY=/home/alex/astra/.venv/bin/python
M=experiments/spatial_input_eval_v0

# Verify all archived evidence and historical preservation.
$PY "$M/lab/b_v2/verify_artifacts.py" --repo "$PWD" --output /tmp/b-v2-integrity-recheck.json
$PY -m unittest discover -s "$M/tests"

# Optional rerender into a NEW directory. Existing frozen input remains unchanged.
$PY "$M/lab/b_v2/validation_suite.py" --output /tmp/b-v2-rerender-new
$PY "$M/lab/b_v2/export_public.py" --suite /tmp/b-v2-rerender-new --output /tmp/b-v2-public-new

# Isolated replay of frozen observations, not the optional rerender.
cp "$M/lab/b_v2/estimate.py" /tmp/b-v2-estimator-replay.py
cp -r "$M/evidence/b_v2_20261014/public_validation" /tmp/b-v2-public-replay
$PY "$M/lab/b_prototype/isolated_run.py" \
  --estimator /tmp/b-v2-estimator-replay.py --public /tmp/b-v2-public-replay \
  --output /tmp/b-v2-estimates-replay --deny-root /home/alex/astra-realman_ws
# For B1 use an unmodified copy of lab/b_prototype/estimate.py in a fresh output.

# Independent rescoring of archived sealed estimates into a NEW directory.
$PY "$M/lab/b_v2/evaluate.py" --module "$M" --output /tmp/b-v2-evaluation-replay
```

SAPIEN 3.0.0b1, Python 3.10.12, NumPy 1.26.4, SciPy 1.10.1 and Pillow 12.3.0 were used on Ubuntu-Robot. Rendering emitted Mesa device warnings but all six captures completed. Raw logs and calibration/depth are archived. Figures were produced separately with Matplotlib 3.9.4; their generation is outside estimator timing. Rendered RGB is actual simulator output; figures and overlays are explicitly diagnostic.

Changing estimator parameters after looking at these GT results requires a new version and new independent validation. Existing B v1, production bridge, scores, ledgers and the frozen 36-request plan remain unchanged.
