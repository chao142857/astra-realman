#!/usr/bin/env python3
"""Small serial engineering matrix; preserve every attempt and sampled GPU use."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--pairs', type=int, default=5, choices=range(1, 6))
    p.add_argument('--smoke-only', action='store_true')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    rows = []
    specs = [(2, 'S')] if a.smoke_only else [(seed, c) for seed in range(2, 2 + a.pairs) for c in ('M', 'S')]
    runner = Path(__file__).with_name('run_sim_placement.py')
    for seed, condition in specs:
        name = 'seed-%02d-%s' % (seed, condition)
        episode = a.output / name
        cmd = [sys.executable, str(runner), '--assets', str(a.assets), '--output', str(episode),
               '--seed', str(seed), '--condition', condition]
        if a.smoke_only:
            cmd.append('--smoke-only')
        elif len(rows) == 0:
            cmd.append('--video')
        row = {'episode': name, 'command': cmd, 'status': 'INCOMPLETE'}
        rows.append(row)
        (a.output / 'matrix.json').write_text(json.dumps(rows, indent=2))
        start = time.monotonic()
        gpu = []
        with (a.output / (name + '.log')).open('x') as log:
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    try:
                        total = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu',
                                                         '--format=csv,noheader,nounits'], text=True, timeout=3).strip()
                        own = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid,used_memory',
                                                       '--format=csv,noheader,nounits'], text=True, timeout=3).strip()
                        gpu.append({'elapsed_s': time.monotonic() - start, 'device_memory_utilization': total,
                                    'compute_processes': own, 'episode_pid': process.pid})
                    except (OSError, subprocess.SubprocessError) as exc:
                        gpu.append({'error': repr(exc)})
                    if time.monotonic() - start > 180:
                        row['timeout'] = True
                        process.terminate()
                        break
                    time.sleep(.5)
                try:
                    row['return_code'] = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    row['return_code'] = process.wait()
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
        (a.output / (name + '-gpu.json')).write_text(json.dumps(gpu, indent=2))
        if (episode / 'result.json').exists():
            row['result'] = json.loads((episode / 'result.json').read_text())
            row['status'] = row['result']['status']
        row['wall_time_s'] = time.monotonic() - start
        (a.output / 'matrix.json').write_text(json.dumps(rows, indent=2))
        print(json.dumps({k: row[k] for k in ('episode', 'status', 'return_code', 'wall_time_s')}), flush=True)
        # Preserve failures; a controller/physics fault ends acceptance, no blind retry.
        if row['status'] != 'PASS':
            break
    return 0 if len(rows) == len(specs) and all(r['status'] == 'PASS' for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
