#!/usr/bin/env bash
# Task-specific migration only. Existing yanglab runtime.sh remains unchanged.
export PYTHONPATH=
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2
export RM65_PYTHON=/home/alex/astra/.venv/bin/python
export RM65_ASSETS=/home/alex/astra_spatial_capability/rm65-d4-runtime-20261015/assets
export MPLCONFIGDIR=/home/alex/astra_spatial_capability/rm65-d4-runtime-20261015/matplotlib
export RM65_CONTROLLER=original
export RM65_SOLVER=original
