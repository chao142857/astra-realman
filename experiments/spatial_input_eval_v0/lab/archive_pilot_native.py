#!/usr/bin/env python3
"""Mac-only, read-only native-log collection. Never imports or calls the bridge."""
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]/'evidence/pilot01_20261013'
FILES = ['attachments.json', 'authoritative_schema.json', 'command.json', 'environment.json',
         'events.jsonl', 'last_message.json', 'prompt.json', 'result.json', 'schema.json',
         'schema_audit.json', 'stderr.log', 'input_only/context.json',
         'input_only/image-0.png', 'input_only/image-1.png', 'input_only/image-2.png']


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for row in read(ROOT/'ledger.json')['reservations']:
        run = ROOT/row['directory']; sample = run/'sample-0000'
        received = (sample/'bridge_result.json').exists()
        if received:
            result = read(sample/'bridge_result.json'); source = result.get('local_log')
        elif (run/'poststop_native_locator.json').exists():
            source = read(run/'poststop_native_locator.json')['native_source']
            if not re.fullmatch(r'/private/tmp/codex-astra-bridge/[0-9a-f]{32}', source):
                raise ValueError('UNEXPECTED_NATIVE_PATH')
            result = read(Path(source)/'result.json')
        else:
            continue
        if not source:
            continue
        if not re.fullmatch(r'/private/tmp/codex-astra-bridge/[0-9a-f]{32}', source):
            raise ValueError('UNEXPECTED_NATIVE_PATH')
        source = Path(source); payload = read(sample/'request.json')
        if read(source/'result.json') != result: raise ValueError('NATIVE_RESULT_MISMATCH')
        if read(source/'prompt.json') != payload['context']: raise ValueError('NATIVE_CONTEXT_MISMATCH')
        for name, expected in [('schema.json',payload['schema']),('authoritative_schema.json',payload['authoritative_schema'])]:
            if read(source/name) != expected: raise ValueError('NATIVE_SCHEMA_MISMATCH')
        for i, attachment in enumerate(payload['context']['attachments']):
            if sha(source/f'input_only/image-{i}.png') != attachment['sha256']:
                raise ValueError('NATIVE_IMAGE_MISMATCH')
        hashes = {}
        for name in FILES:
            if not (source/name).exists(): continue
            target = run/'mac_native'/name; target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if sha(target) != sha(source/name): raise ValueError('ARCHIVED_FILE_CHANGED')
            else: shutil.copy2(source/name, target)
            hashes[name] = sha(target)
        audit = dict(status='PASS', source=str(source), context_schema_rgb_and_result='EXACT_MATCH',
                     native_result_returned_to_client=received,
                     late_collection_does_not_override_client_timeout=not received,
                     native_worker_error=result.get('error'),
                     native_completed_events=sum(json.loads(line).get('type')=='turn.completed'
                          for line in result.get('events','').splitlines() if line.strip()),
                     archived_sha256=hashes, new_generation_requests=0, credentials_copied=False,
                     excluded=[str(p.relative_to(source)) for p in sorted(source.rglob('*')) if p.is_file() and str(p.relative_to(source)) not in FILES],
                     exclusion_reason='Runtime databases/caches excluded under ARTIFACT_POLICY.')
        dest=run/'native_archive_audit.json'
        if not dest.exists(): dest.write_text(json.dumps(audit, indent=2)+'\n')
        timing=run/'native_timing.json'
        if not timing.exists():
            timing.write_text(json.dumps(dict(source=str(source),
                prompt_written_unix=(source/'prompt.json').stat().st_mtime,
                result_written_unix=(source/'result.json').stat().st_mtime,
                native_inference_latency_s=result['latency_s'],
                note='Read from the original Mac runtime before Git checkout can change artifact mtimes.'),indent=2)+'\n')
        print(f'{row["index"]:02d} native archive PASS')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['pilot01_20261013','pilot01_parallel180_20261013'],default='pilot01_20261013')
    args=parser.parse_args()
    ROOT=Path(__file__).resolve().parents[1]/'evidence'/args.phase
    main()
