#!/usr/bin/env bash
set -euo pipefail
LAB_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$LAB_DIR/../../.." && pwd)
PYTHON_EXE=${SPATIAL_EVAL_PYTHON:-"$REPO_ROOT/.venv/bin/python"}
if [[ $# != 1 ]]; then echo 'Usage: run_offline.sh NEW_OUTPUT_DIRECTORY' >&2; exit 2; fi
mkdir -- "$1"
OUTPUT_DIR=$(cd -- "$1" && pwd)
export PYTHONPATH="$LAB_DIR/.."
"$PYTHON_EXE" -m unittest discover -s "$LAB_DIR/../tests" -v > "$OUTPUT_DIR/unit_tests.log" 2>&1
"$PYTHON_EXE" -m spatial_eval.cli run --snapshot "$LAB_DIR/../evidence/s1_archive/snapshot.json" --output "$OUTPUT_DIR/mock_s1"
"$PYTHON_EXE" "$LAB_DIR/render_scenes.py" --output "$OUTPUT_DIR/sim_suite" > "$OUTPUT_DIR/render.log" 2>&1
"$PYTHON_EXE" "$LAB_DIR/verify_suite.py" --suite "$OUTPUT_DIR/sim_suite" --output "$OUTPUT_DIR/acceptance"
"$PYTHON_EXE" -m spatial_eval.cli run --snapshot "$OUTPUT_DIR"/sim_suite/*/snapshot.json --output "$OUTPUT_DIR/mock_sim_suite"
"$PYTHON_EXE" "$LAB_DIR/render_scenes.py" --output "$OUTPUT_DIR/sim_suite_repeat" > "$OUTPUT_DIR/render_repeat.log" 2>&1
"$PYTHON_EXE" "$LAB_DIR/verify_suite.py" --suite "$OUTPUT_DIR/sim_suite_repeat" --output "$OUTPUT_DIR/acceptance_repeat"
"$PYTHON_EXE" "$LAB_DIR/compare_reproduction.py" --first "$OUTPUT_DIR/sim_suite" --second "$OUTPUT_DIR/sim_suite_repeat" --output "$OUTPUT_DIR/reproduction.json"
echo "Offline acceptance completed: $OUTPUT_DIR; Astra generation requests=0"
