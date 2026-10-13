#!/usr/bin/env python3
"""Export scientific plots from analyze_pilot01.py CSVs; no model calls."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "astra-pilot01-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT = Path(__file__).resolve().parents[1] / "evidence/pilot01_analysis_20261013"
TITLES = {
    "position_vector_L2_m": "Position: vector L2 error",
    "size_vector_L2_m": "Size: vector L2 error",
    "height_scalar_absolute_m": "Top height: scalar absolute error",
    "gap_scalar_absolute_m": "Gap: scalar absolute error",
}


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def run(directory):
    directory = Path(directory)
    data = read_csv(directory / "threshold_curves.csv")
    question_rows = read_csv(directory / "question_errors.csv")
    with plt.rc_context({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "pilot01-b103ee5-analysis", "savefig.dpi": 180}):
        fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.3), layout="constrained")
        for axis, (metric, title) in zip(axes.flat, TITLES.items()):
            for condition, sensitivity, label, style, color, marker in (
                    ("A", "exact", "A: exact threshold", "-", "#2563eb", "o"),
                    ("A", "uniform_10nm", "A: threshold +10 nm", "--", "#d97706", "s"),
                    ("C", "exact", "C: exact and +10 nm (identical)", "-", "#15803d", "^")):
                rows = sorted([r for r in data if r["metric"] == metric and r["condition"] == condition
                               and r["sensitivity"] == sensitivity], key=lambda r: float(r["threshold_mm"]))
                axis.plot([float(r["threshold_mm"]) for r in rows], [100*float(r["accuracy"]) for r in rows],
                          linestyle=style, color=color, marker=marker, markersize=6,
                          markerfacecolor="white" if sensitivity == "exact" else color,
                          linewidth=1.7, label=label)
            axis.set(title=title + " (n=6 per condition)", xlabel="Error threshold (mm)",
                     ylabel="Within threshold (%)", xticks=[2, 5, 10, 20], ylim=(0, 105),
                     yticks=[0, 25, 50, 75, 100])
            axis.grid(axis="both", color="#d1d5db", linewidth=.6, alpha=.7)
        handles, labels = axes.flat[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="outside lower center", ncol=3, fontsize=9)
        fig.suptitle("Pilot 01: numeric sensitivity by error metric\nFrozen scores unchanged; +10 nm is a post-hoc sensitivity view", fontsize=14)
        for extension in ("png", "svg", "pdf"):
            metadata = {"Date": None} if extension == "svg" else {"CreationDate": None, "ModDate": None} if extension == "pdf" else {}
            fig.savefig(directory / ("threshold_curves." + extension), metadata=metadata)
        plt.close(fig)
        fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.3), layout="constrained")
        scenes = sorted({r["scene_id"] for r in question_rows})
        for axis, (metric, title) in zip(axes.flat, TITLES.items()):
            for condition, offset, color in (("A", -.18, "#2563eb"), ("C", .18, "#15803d")):
                rows = {r["scene_id"]: r for r in question_rows if r["metric"] == metric and r["condition"] == condition}
                axis.bar([i+offset for i in range(6)], [float(rows[s]["error_mm"]) for s in scenes],
                         width=.34, color=color, label=condition)
            axis.axhline(5, color="#b91c1c", linestyle=":", label="Original 5 mm tolerance")
            axis.set(title=title, xlabel="Frozen scene", ylabel="Error (mm)",
                     xticks=list(range(6)), xticklabels=["S" + str(i) for i in range(1,7)])
            axis.grid(axis="y", color="#d1d5db", linewidth=.6, alpha=.7)
            axis.set_axisbelow(True)
        handles, labels = axes.flat[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="outside lower center", ncol=3)
        fig.suptitle("Pilot 01: per-scene numerical error\nSeparate vector/scalar metrics; C errors are near zero at this scale", fontsize=14)
        for extension in ("png", "svg", "pdf"):
            metadata = {"Date": None} if extension == "svg" else {"CreationDate": None, "ModDate": None} if extension == "pdf" else {}
            fig.savefig(directory / ("numeric_errors_by_scene." + extension), metadata=metadata)
        plt.close(fig)
    manifest = {"real_generation_requests": 0, "matplotlib_version": matplotlib.__version__,
                "input_sha256": {name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
                                 for name in ("threshold_curves.csv", "question_errors.csv")},
                "plot_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "reproduce": ["python3 lab/analyze_pilot01.py", "python3 -m venv /tmp/pilot01-plot-venv",
                              "/tmp/pilot01-plot-venv/bin/python -m pip install matplotlib==3.10.7",
                              "/tmp/pilot01-plot-venv/bin/python lab/plot_pilot01_analysis.py"],
                "reproduce_working_directory": "experiments/spatial_input_eval_v0"}
    (directory / "plot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT)
    run(parser.parse_args().directory)
