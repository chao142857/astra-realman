"""Read native account/workspace routing only; never start a thread or turn."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time


def redact(value, key=''):
    if any(s in key.lower() for s in ('email', 'token', 'secret', 'cookie', 'authorization')) and isinstance(value,(str,dict,list)):
        return '[REDACTED]'
    if (key.lower().endswith(('accountid', 'userid', 'workspaceid', 'installationid', 'environmentid'))
            or key=='id' and isinstance(value,str)) and value is not None:
        if isinstance(value,dict) and set(value)=={'sha256'}:return value
        return {'sha256': hashlib.sha256(str(value).encode()).hexdigest()}
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', value)
        value = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [REDACTED]', value)
        value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[REDACTED_EMAIL]', value)
    return value


def main():
    sys.path.insert(0, '/code')
    from bridge import command
    out = Path('/output/account_routing')
    out.mkdir(exist_ok=False)
    (out/'input_only').mkdir()
    (out/'runtime').mkdir()
    original = command(out, [], sys.argv[1])
    configs = []
    i = 0
    while i < len(original):
        if original[i] in ('-c', '--disable'):
            configs += original[i:i+2]
            i += 2
        else:
            i += 1
    cmd = [sys.argv[1], 'app-server', '--listen', 'stdio://', *configs]
    rate_only=len(sys.argv)>2 and sys.argv[2]=='--rate-limits-only'
    metadata_request=({'id':2,'method':'account/rateLimits/read'} if rate_only else
                      {'id':2,'method':'account/read','params':{'refreshToken':False}})
    requests = [
        {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'spatial-routing-diagnostic', 'version': '0'}, 'capabilities': {'experimentalApi': True}}},
        {'method': 'initialized'},
        metadata_request,
    ]
    start = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=dict(os.environ), cwd=out/'input_only')
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    selector.register(proc.stderr, selectors.EVENT_READ)
    messages, buffer, errors = [], b'', b''
    sent_account = False
    status = 'RPC_TIMEOUT_NO_ROUTING_RESPONSE'
    try:
        proc.stdin.write((json.dumps(requests[0])+'\n').encode()); proc.stdin.flush()
        deadline = start+25
        while time.monotonic() < deadline:
            for key, _ in selector.select(timeout=.2):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                if key.fileobj is proc.stderr:
                    errors += data
                    continue
                buffer += data
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    message = json.loads(line)
                    messages.append(redact(message))
                    if message.get('id') == 1 and 'result' in message and not sent_account:
                        for request in requests[1:]:
                            proc.stdin.write((json.dumps(request)+'\n').encode())
                        proc.stdin.flush(); sent_account = True
                    if message.get('id') == 2:
                        name='RATE_LIMITS_READ' if rate_only else 'ACCOUNT_READ'
                        status = name+'_RESPONSE' if 'result' in message else name+'_ERROR'
            if status != 'RPC_TIMEOUT_NO_ROUTING_RESPONSE' or proc.poll() is not None:
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            _, remaining_stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill(); _, remaining_stderr = proc.communicate()
        errors += remaining_stderr
        selector.close()
    record = {'status': status, 'inference_requests': 0, 'generation_methods_sent': [],
              'command': cmd, 'requests': requests, 'sanitized_responses': messages,
              'account_request_sent': sent_account, 'latency_s': time.monotonic()-start,
              'stderr': redact(errors.decode(errors='replace')),
              'network_namespace': os.readlink('/proc/self/ns/net'),
              'credential_refresh_requested': False, 'credential_mount_read_only': True}
    (out/'probe.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
