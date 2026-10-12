"""Current native CLI, loopback fake Responses, no auth and no external network.

The catalog and disabled feature flags are preserved. This proves client protocol
behavior only, never hosted Astra behavior. Output folders are never overwritten.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from telemetry_filter import phases

ROOT = Path(__file__).resolve().parent.parent
NATIVE = Path('/home/alex/.nvm/versions/node/v22.23.2/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex')
HOST = Path('/home/alex/.codex/packages/app-server-daemon/releases/0.162.1-x86_64-unknown-linux-musl/bin/codex-code-mode-host')


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def sandbox(output, cli, host, code):
    return ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib',
            '--symlink', 'usr/lib64', '/lib64', '--symlink', 'usr/bin', '/bin',
            '--ro-bind', str(cli), '/cli', '--ro-bind', str(host), '/host',
            '--ro-bind', str(code.with_name('telemetry_filter.py')), '/telemetry_filter.py',
            '--ro-bind', str(code), '/probe.py', '--bind', str(output), '/output',
            '--tmpfs', '/tmp', '--dir', '/home/probe/.codex', '--proc', '/proc',
            '--dev', '/dev', '--chdir', '/output', '/usr/bin/python3', '-B', '/probe.py', '--inside']


def host_probe():
    """V1 negotiation and empty session lifecycle; no JS or nested tools executed."""
    transcript = []
    proc = subprocess.Popen(['/host', '--listen', 'stdio'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def exchange(message):
        payload = json.dumps(message).encode()
        proc.stdin.write(struct.pack('<I', len(payload)) + payload)
        proc.stdin.flush()
        length = proc.stdout.read(4)
        if len(length) != 4:
            raise RuntimeError('HOST_FRAME_MISSING')
        reply = json.loads(proc.stdout.read(struct.unpack('<I', length)[0]))
        transcript.append({'request':message, 'response':reply})
        return reply
    try:
        ready = exchange({'type':'connection/hello', 'supportedVersions':[1],
                          'requiredCapabilities':[], 'optionalCapabilities':[]})
        opened = exchange({'type':'operation/request', 'id':1,
                           'request':{'method':'session/open', 'sessionId':'offline-diagnostic'}})
        closed = exchange({'type':'operation/request', 'id':2,
                           'request':{'method':'session/shutdown', 'sessionId':'offline-diagnostic'}})
        ok = (ready.get('selectedVersion') == 1 and opened.get('result', {}).get('status') == 'ok'
              and closed.get('result', {}).get('status') == 'ok')
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
    return {'status':'PASS' if ok else 'FAIL', 'transcript':transcript,
            'stderr':proc.stderr.read().decode(), 'executed_cells':0, 'nested_tools':0}


def inside():
    output = Path('/output')
    case = json.loads((output/'case.json').read_text())['case']
    requests = []
    phase_events = []
    answer = '{"offline_fixture":true}'
    item = {'id':'msg_offline', 'type':'message', 'role':'assistant',
            'status':'completed', 'content':[{'type':'output_text', 'text':answer}]}
    events = [
        {'type':'response.created', 'response':{'id':'resp_offline'}},
        {'type':'response.output_item.added', 'output_index':0, 'item':{**item, 'status':'in_progress'}},
        {'type':'response.output_text.delta', 'item_id':item['id'], 'output_index':0,
         'content_index':0, 'delta':answer},
        {'type':'response.output_item.done', 'output_index':0, 'item':item},
        {'type':'response.completed', 'response':{'id':'resp_offline', 'status':'completed',
          'output':[item], 'usage':{'input_tokens':7, 'output_tokens':5, 'total_tokens':12}}}]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            if self.path in ('/v1/logs','/v1/traces','/v1/metrics'):
                phase_events.extend(phases(json.loads(data)))
                self.send_response(200); self.send_header('Content-Length','2')
                self.end_headers(); self.wfile.write(b'{}'); return
            if not self.path.endswith('/responses'):
                # Local non-generative turn-cost reporting is not an inference POST.
                self.send_response(200); self.send_header('Content-Length','2')
                self.end_headers(); self.wfile.write(b'{}'); return
            # Never record headers, including in this unauthenticated fixture.
            requests.append({'path':self.path, 'body':json.loads(data), 'monotonic':time.monotonic()})
            wire_events = events[:1] if case=='stream_truncate' else events
            body = (b'{"error":{"message":"OFFLINE_INJECTED_503"}}' if case=='http503' else
                    ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in wire_events).encode())
            self.send_response(503 if case=='http503' else 200)
            self.send_header('Content-Type', 'application/json' if case=='http503' else 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 18080), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    argv = json.loads((output/'argv.json').read_text())
    env = {'HOME':'/home/probe', 'PATH':'/usr/bin:/bin', 'TMPDIR':'/tmp', 'LANG':'C.UTF-8',
           'RUST_LOG':'warn,codex_core::client=info,codex_api::endpoint::responses=info'}
    start = time.monotonic()
    timeout = False
    try:
        run = subprocess.run(argv, input=b'Return only {"offline_fixture":true}; do not use tools.',
                             env=env, capture_output=True, timeout=20)
        stdout, stderr, returncode = run.stdout, run.stderr, run.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, returncode = exc.stdout or b'', exc.stderr or b'', None
        timeout = True
    server.shutdown()
    (output/'exec.stdout.jsonl').write_bytes(stdout)
    (output/'exec.stderr.log').write_bytes(stderr)
    save(output/'fake_wire_events.json', events)
    save(output/'fake_requests.json', requests)
    save(output/'sanitized_native_phases.json', phase_events)
    lines = [json.loads(line) for line in stdout.decode().splitlines() if line.startswith('{')]
    raw = (output/'last_message.txt').read_text() if (output/'last_message.txt').exists() else ''
    completed = any(e.get('type')=='turn.completed' for e in lines)
    warning = any('fail closed' in json.dumps(e) for e in lines)
    save(output/'host_handshake.json', host_probe())
    good_completion = returncode==0 and warning and completed and raw.strip()==answer and len(requests)==1
    good_failure = returncode!=0 and not timeout and not completed and not raw and len(requests)==1
    result = {'classification':'FAKE_LOCAL_PROTOCOL_NOT_MODEL', 'case':case,'real_model_calls':0,
              'real_credentials':False, 'external_network':False, 'timeout':timeout,
              'returncode':returncode, 'wall_s':time.monotonic()-start, 'inference_post_count':len(requests),
              'fail_closed_warning':warning, 'turn_completed':completed, 'raw':raw,
              'strict_json_valid':raw.strip()==answer, 'network_routes':Path('/proc/net/route').read_text(),
              'sanitized_telemetry_records':len(phase_events),
              'status':'PASS' if (good_completion if case=='text_complete' else good_failure) else 'FAIL'}
    save(output/'RESULT.json', result)
    print(json.dumps(result))
    return int(result['status']!='PASS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inside', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--case',choices=('text_complete','http503','stream_truncate'),default='text_complete')
    a = p.parse_args()
    if a.inside:
        return inside()
    if not a.output:
        p.error('--output required')
    output = a.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    save(output/'case.json', {'case':a.case})
    record = json.loads((ROOT/'evidence/routing_repair/real_A_qualification/sample-0000/infer_output/worker_record.json').read_text())
    old = record['command']
    argv = ['/cli', 'exec', '--ignore-user-config', '--ignore-rules', '--sandbox', 'read-only',
            '--ephemeral', '--skip-git-repo-check', '--cd', '/output', '--json', '--color', 'never',
            '--model', 'gpt-6-astra', '--output-last-message', '/output/last_message.txt']
    # Copy all original disabling flags and explicit safety configuration.
    i = 0
    while i < len(old):
        if old[i] in ('--disable', '-c'):
            key, value = old[i:i+2]
            if key == '--disable' or not value.startswith(('model_provider=', 'log_dir=', 'sqlite_home=')):
                argv.extend([key, value])
            i += 2
        else:
            i += 1
    for cfg in ['model_provider="offline_fixture"',
                'model_providers.offline_fixture={name="OFFLINE FIXTURE",base_url="http://127.0.0.1:18080/v1",wire_api="responses",requires_openai_auth=false,supports_websockets=false,request_max_retries=0,stream_max_retries=0}',
                'model_catalog_json="/output/catalog.json"', 'log_dir="/tmp/runtime"',
                'sqlite_home="/tmp/runtime"', 'otel.log_user_prompt=false', 'otel.log_agent_responses=false',
                'otel.exporter={otlp-http={endpoint="http://127.0.0.1:18080/v1/logs",protocol="json"}}',
                'otel.trace_exporter={otlp-http={endpoint="http://127.0.0.1:18080/v1/traces",protocol="json"}}',
                'otel.metrics_exporter={otlp-http={endpoint="http://127.0.0.1:18080/v1/metrics",protocol="json"}}']:
        argv.extend(['-c', cfg])
    argv.append('-')
    catalog = json.loads(Path('/home/alex/.codex/models_cache.json').read_text())
    models = [m for m in catalog['models'] if m['slug']=='gpt-6-astra']
    if len(models)!=1 or models[0]['tool_mode']!='code_mode_only':
        raise ValueError('CATALOG_MODE_MISMATCH')
    save(output/'catalog.json', {'models':models})
    save(output/'argv.json', argv)
    code = Path(__file__).resolve()
    command = sandbox(output, NATIVE, HOST, code)
    save(output/'sandbox_command.json', command)
    save(output/'provenance.json', {'real_model_calls':0, 'source_commit':'1925370',
      'catalog_client_version':catalog.get('client_version'),
      'native_sha256':hashlib.sha256(NATIVE.read_bytes()).hexdigest(),
      'host_sha256':hashlib.sha256(HOST.read_bytes()).hexdigest(),
      'note':'Only fake local transport differs; catalog/model/effort/disabled flags preserved. No real auth mount.'})
    env = {'HOME':'/home/probe', 'PATH':'/usr/bin:/bin', 'TMPDIR':'/tmp', 'LANG':'C.UTF-8'}
    run = subprocess.run(command, env=env, capture_output=True, timeout=35)
    (output/'launcher.stdout').write_bytes(run.stdout)
    (output/'launcher.stderr').write_bytes(run.stderr)
    print(run.stdout.decode()[-3000:]); print(run.stderr.decode()[-1000:])
    return run.returncode


if __name__=='__main__':
    raise SystemExit(main())
