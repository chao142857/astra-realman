"""Dependency-injected, serial placement scheduler with one public budget clock."""
import copy
import hashlib
import json
import math
import threading
import time
from pathlib import Path
from bimanual_demo.primitives import placement_primitives


class PlacementRuntime:
    def __init__(self, backend, targets, output, *, condition, policy, budget_s=120,
                 max_requests=4, clock=time.monotonic):
        if condition not in ('M', 'S'):
            raise ValueError('CONDITION')
        if type(budget_s) not in (int,float) or not math.isfinite(budget_s) or not 0 < budget_s <= 480:
            raise ValueError('PUBLIC_BUDGET_RANGE')
        if type(max_requests) is not int or not 1 <= max_requests <= 4:
            raise ValueError('REQUEST_LIMIT_RANGE')
        if targets['backend'] != backend.backend_id or targets['arm'] != 'single':
            raise ValueError('TARGET_BACKEND_ARM_MISMATCH')
        if targets['frame'] != 'sapien:world' or targets['tool'] != 'dynamic_pad_center_position_with_Link6_orientation_wxyz':
            raise ValueError('TARGET_FRAME_TOOL_MISMATCH')
        for key in ('approach', 'release_pose', 'retract'):
            pose = targets[key]
            if len(pose) != 7 or any(type(x) not in (float, int) or not math.isfinite(x) for x in pose):
                raise ValueError('TARGET_POSE')
            if abs(sum(x*x for x in pose[3:]) - 1) > .001:
                raise ValueError('TARGET_QUATERNION')
        self.backend, self.targets, self.policy = backend, copy.deepcopy(targets), policy
        self.condition, self.clock = condition, clock
        self.deadline = clock() + budget_s
        self.max_requests, self.attempts = max_requests, 0
        self.stop_event = threading.Event()
        self.root = Path(output)
        self.root.mkdir(parents=True, exist_ok=False)
        self.stream = (self.root / 'events.jsonl').open('x', buffering=1)
        self.rows = []
        self.current = 0
        self.consumed = False
        self.primitives = placement_primitives(targets['approach'], targets['release_pose'],
                                              targets['retract'], targets['release_opening'])

    def emit(self, kind, data):
        row = copy.deepcopy({'kind': kind, 'wall_monotonic': self.clock(),
                             'physics_step': self.backend.steps, 'data': data})
        self.rows.append(row)
        self.stream.write(json.dumps(row, allow_nan=False) + '\n')

    def admit(self):
        if self.stop_event.is_set() or getattr(self.backend,'stopped',False):
            raise RuntimeError('STOP_NO_NEW_COMMANDS')
        if self.clock() >= self.deadline:
            raise TimeoutError('PUBLIC_BUDGET_EXPIRED')

    def stop(self):
        self.stop_event.set()
        self.backend.stop()

    def run(self):
        if self.consumed:
            raise RuntimeError('EPISODE_ALREADY_CONSUMED')
        self.consumed = True
        start, first_step = self.clock(), self.backend.steps
        status, error = 'INCOMPLETE', None
        backend_latency = 0.
        try:
            for index, primitive in enumerate(self.primitives):
                self.current = index
                self.admit()
                observation = self.backend.observe()
                self.emit('OBSERVATION', observation)
                if self.condition == 'M' or index == 0:
                    self.admit()
                    if self.attempts >= self.max_requests:
                        raise RuntimeError('REQUEST_BUDGET_EXPIRED')
                    self.attempts += 1
                    binding = {'observation_id': observation['observation_id'],
                               'revision': self.targets['revision'], 'request': self.attempts,
                               'primitive_index': index, 'condition': self.condition}
                    # Opaque task IDs only; GT checks/score/setup trace never enter context.
                    context = {'binding': binding, 'observation': observation,
                               'task': 'Place the held cube on the fixed green marker.',
                               'target_id': 'fixed_green_marker',
                               'allowed_actions': ['continue', 'stop'], 'diagnostics': 'D0',
                               'previous_feedback': [r['data'] for r in self.rows
                                                     if r['kind'] == 'EXECUTION_RESULT']}
                    self.emit('MODEL_ATTEMPT', {'context': context, 'model_source': self.policy.source})
                    t = self.clock()
                    try:
                        result = self.policy.decide(context, self.root / ('request-%02d' % self.attempts),
                                                    timeout_s=self.deadline-self.clock())
                    finally:
                        backend_latency += self.clock() - t
                    self.emit('MODEL_RESULT', result)
                    self.admit()  # A late result is logged, but cannot control the next primitive.
                    if set(result) != {'binding', 'action'} or json.dumps(result['binding'],sort_keys=True) != json.dumps(binding,sort_keys=True):
                        raise ValueError('STALE_OR_INVALID_PROPOSAL')
                    if result['action'] == 'stop':
                        raise RuntimeError('POLICY_STOP')
                    if result['action'] != 'continue':
                        raise ValueError('UNSUPPORTED_PROPOSAL')
                check = self.backend.check(primitive)
                self.emit('SKILL_CHECK', check)
                if check.get('ok') is not True:
                    raise RuntimeError('MISSING_OR_FAILED_EVIDENCE')
                self.admit()  # Same check, control, observation and budget boundary in M/S.
                self.emit('SKILL_INTERNAL_ACTION', {'index': index, 'primitive': primitive,
                                                   'execution_source': self.backend.source})
                result = self.backend.execute(primitive)
                self.emit('EXECUTION_RESULT', result)
                if result.get('ok') is not True:
                    raise RuntimeError('EXECUTION_FAILED_NO_RETRY')
            self.admit()
            # Evaluator is terminal; there are no policy requests after truth is produced.
            result = self.backend.evaluate()
            self.emit('INDEPENDENT_EVALUATION', result)
            status = result['status']
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)
            status = 'FAIL'
            self.emit('FAULT', {'error': error, 'automatic_retry': False})
        finally:
            try:
                self.emit('FINAL_OBSERVATION', self.backend.observe())
            except Exception as exc:
                self.emit('FINAL_OBSERVATION_FAILED', {'error': repr(exc)})
            summary = {'status': status, 'error': error, 'condition': self.condition,
                       'model_source': self.policy.source, 'observation_source': self.backend.source,
                       'execution_source': self.backend.source, 'model_attempts': self.attempts,
                       'real_model_calls': getattr(self.policy, 'calls', 0), 'hardware_calls': 0,
                       'primitive_count': sum(r['kind'] == 'SKILL_INTERNAL_ACTION' for r in self.rows),
                       'expanded_sequence_sha256': hashlib.sha256(json.dumps(self.primitives, sort_keys=True).encode()).hexdigest(),
                       'wall_time_s': self.clock() - start, 'physics_steps': self.backend.steps - first_step,
                       'physics_time_s': (self.backend.steps - first_step) * self.backend.dt,
                       'dt': self.backend.dt, 'backend_latency_s': backend_latency,
                       'decision_wait_mode': self.backend.decision_wait_mode,
                       'evaluation_scope': 'ENGINEERING_ORACLE; fixed-target continuation scheduling only',
                       'safety_cleanup': 'no new physical actions on failure; paused simulation',
                       'recovery': 'new observation and explicit new run; no automatic release/retry'}
            (self.root / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
            self.stream.close()
        return summary


class ScriptedPolicy:
    source = 'SCRIPTED_STUB_NOT_ASTRA'
    calls = 0

    def decide(self, context, output, *, timeout_s=None):
        return {'binding': context['binding'], 'action': 'continue'}
