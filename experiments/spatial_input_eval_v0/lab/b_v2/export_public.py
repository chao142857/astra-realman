"""Trusted whitelist exporter; only A context, RGB, depth_m and valid arrays."""
import argparse,sys
from pathlib import Path
import importlib.util
p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
spec=importlib.util.spec_from_file_location('whitelist_export',Path(__file__).resolve().parents[1]/'b_prototype/export_public.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
mod.SCENES=tuple(sorted(x.name for x in a.suite.iterdir() if x.is_dir() and (x/'model_inputs/RGB_MULTI_VIEW/context.json').is_file()));assert len(mod.SCENES)==6
mod.export(a.suite,a.output)
