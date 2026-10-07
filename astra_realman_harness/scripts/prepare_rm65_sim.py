#!/usr/bin/env python3
"""Freeze the existing local RM65 assets, without changing their source tree."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = [source / 'scripts' / name for name in
             ('rm65_scene.py', 'bridge_diagnostics.py', 'run_expert.py')]
    for folder in ('configs/rm65_ctag_reference', 'vendor/target_models_20260921'):
        files.extend(p for p in (source / folder).rglob('*') if p.is_file())
    manifest = {'source': str(source), 'source_head': subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
        'renderer': 'default raster; inherited RT settings removed', 'files': {}}
    for src in sorted(files):
        rel = src.relative_to(source)
        if '.git' in rel.parts or '__pycache__' in rel.parts:
            continue
        dst = output / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        changes = []
        if dst.suffix in ('.urdf', '.yml'):
            value = dst.read_text()
            # Relative URDF mesh paths remain portable when this entire tree moves.
            old = str(source / 'vendor')
            if old in value:
                dst.write_text(value.replace(old, '../../vendor'))
                changes.append('absolute asset root -> relative ../../vendor')
        if rel.as_posix() == 'scripts/rm65_scene.py':
            value = dst.read_text()
            old = ("        sapien.render.set_camera_shader_dir('rt');sapien.render.set_ray_tracing_samples_per_pixel(8)\n"
                   "        sapien.render.set_ray_tracing_path_depth(4);sapien.render.set_ray_tracing_denoiser('none')")
            if value.count(old) != 1:
                raise ValueError('UPSTREAM_RENDERER_DRIFT')
            dst.write_text(value.replace(old, "        sapien.render.set_camera_shader_dir('default')"))
            changes.append('raster renderer only; no controller/physics changes')
        manifest['files'][str(rel)] = {'source_sha256': digest(src),
                                       'sha256': digest(dst), 'changes': changes}
    (output / 'asset_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source, args.output)
    print(json.dumps({'files': len(result['files']), 'output': str(args.output)}))
