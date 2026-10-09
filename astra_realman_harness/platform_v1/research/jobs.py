"""Finite OS-process lifecycle, shared by adapters, never an action executor."""
import json
import subprocess
import time
from pathlib import Path

class ProcessJob:
    def __init__(self, folder, command, env, deadline, *, cooperative=False, clock=time.monotonic):
        self.folder = Path(folder); self.command = command; self.deadline = deadline
        self.clock = clock; self.cooperative = cooperative; self.cancel_reason = None
        self.cancel_at = None; self.proc = None; self.stages = []; self.usage_raw = None
        self.record('PREPARED')
        self.stdout = (self.folder / 'worker.json').open('xb')
        self.stderr = (self.folder / 'stderr.log').open('xb')
        (self.folder / 'command.json').write_text(json.dumps(command, indent=2))
        self.record('LAUNCHING')
        try:
            self.proc = subprocess.Popen(command, stdout=self.stdout, stderr=self.stderr, env=env,
                                         stdin=subprocess.DEVNULL, cwd=self.folder)
            self.record('STARTED', pid=self.proc.pid)
        except Exception as exc:
            self.stdout.close(); self.stderr.close(); self.record('LAUNCH_FAILED', error=repr(exc)); raise

    def record(self, stage, **data):
        self.stages.append({'stage': stage, 'monotonic': self.clock(), **data})
        (self.folder / 'process.json').write_text(json.dumps({'stages': self.stages, 'usage_raw': self.usage_raw,
            'deadline_monotonic': self.deadline, 'cancel_reason': self.cancel_reason}, indent=2))

    def cancel(self, reason='CANCELLED'):
        if self.cancel_reason is not None: return
        self.cancel_reason = reason; self.cancel_at = self.clock(); self.record('CANCELLING', reason=reason)
        if self.cooperative: (self.folder / 'infer_output/CANCEL').touch()
        elif self.proc and self.proc.poll() is None: self.proc.terminate()

    def poll(self):
        now = self.clock()
        if now >= self.deadline and self.cancel_reason is None: self.cancel('TIMEOUT')
        if self.proc.poll() is None:
            if self.cancel_at is not None and now - self.cancel_at >= 4:
                self.proc.kill(); self.proc.wait(timeout=2)
            else: return None
        self.stdout.close(); self.stderr.close()
        raw = (self.folder / 'worker.json').read_bytes()
        self.record('CANCELLED' if self.cancel_reason else 'RETURNED', return_code=self.proc.returncode, raw_bytes=len(raw))
        return {'bytes': raw, 'return_code': self.proc.returncode, 'cancel_reason': self.cancel_reason}

    def close(self):
        if self.proc.poll() is None:
            self.cancel('OWNER_CLOSED')
            try: self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait(timeout=2)
        return self.poll()
