#!/usr/bin/env bash
set -eu
task_root=$(cd "$(dirname "$0")/../.." && pwd)
export PYTHONPATH="$task_root/aspire_realman_phase2a/src:$task_root/aspire_realman_phase05/src:$task_root/.cache/ASPIRE/src${PYTHONPATH:+:$PYTHONPATH}"
"${PYTHON:-python3}" -B -m unittest discover -s "$task_root/aspire_realman_phase2a/tests" -v
