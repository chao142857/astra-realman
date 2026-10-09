"""Pure future-scheduling contract. No Broker/Owner/threads/network/threshold fit.

This is a contract checker and intent log, not another Supervisor. Callers must
still use the existing physical Owner and its admission gates. Simulation here
never validates native subagent concurrency or causes real requests.
"""
import math
from .contracts import clone

SEMANTIC_EVENTS = ('task_needs_new_semantics', 'critical_identity_ambiguous',
                   'relevant_new_instance_unmatched', 'semantic_conflict_with_reliable_current_evidence')

class ScheduleContract:
    def __init__(self):
        self.phase = 'IDLE'; self.trace = []; self.completed_at = None; self.observation = None; self.world = None; self.last_revision = None

    def _record(self, event, details):
        record = {'event': event, 'phase': self.phase, **clone(details), 'dispatch': False, 'grants_execution': False}
        self.trace.append(record); return clone(record)

    def owner_action_completed(self, completed_monotonic):
        if self.phase != 'IDLE': raise ValueError('POSTCHECK_REQUIRED_BEFORE_NEXT_ACTION')
        if type(completed_monotonic) not in (int,float) or not math.isfinite(completed_monotonic): raise ValueError('COMPLETION_TIME')
        self.completed_at = completed_monotonic; self.phase = 'NEED_OBSERVATION'
        return self._record('OWNER_ACTION_COMPLETED', {'next': 'observe'})

    def observed(self, observation):
        if self.phase != 'NEED_OBSERVATION': raise ValueError('OBSERVE_ORDER')
        if type(observation['captured_monotonic']) not in (int,float) or not math.isfinite(observation['captured_monotonic']): raise ValueError('OBSERVATION_TIME')
        if observation['captured_monotonic'] < self.completed_at: raise ValueError('OBSERVATION_BEFORE_COMPLETION')
        self.observation = clone(observation); self.phase = 'NEED_UPDATE'
        return self._record('CURRENT_OBSERVATION', {'observation_id': observation['observation_id'], 'next': 'WorldHead.update'})

    def updated(self, world):
        if self.phase != 'NEED_UPDATE': raise ValueError('UPDATE_ORDER')
        if world['state']['observation_id'] != self.observation['observation_id'] or world['binding']['execution_epoch'] != self.observation['execution_epoch']:
            raise ValueError('UPDATE_BINDING')
        if type(world['world_revision']) is not int or world['world_revision']<1 or (self.last_revision is not None and world['world_revision']<=self.last_revision): raise ValueError('STALE_UPDATE_REVISION')
        self.last_revision=world['world_revision']
        self.world = clone(world); self.phase = 'NEED_CONSISTENCY_CHECK'
        return self._record('WORLD_UPDATED', {'world_id': world['world_id'], 'world_revision': world['world_revision'], 'next': 'consistency_check'})

    def checked(self, *, geometry_loss, association_uncertainty, visibility, task_relevance,
                chunk_finished, deviation, identity_clear, semantic_events):
        if self.phase != 'NEED_CONSISTENCY_CHECK': raise ValueError('CHECK_ORDER')
        if set(semantic_events) != set(SEMANTIC_EVENTS) or any(type(v) is not bool for v in semantic_events.values()): raise ValueError('SEMANTIC_EVENTS')
        if any(type(v) is not bool for v in (task_relevance, chunk_finished, deviation, identity_clear)): raise ValueError('SCHEDULE_FLAGS')
        semantic_reasons = [key for key, value in semantic_events.items() if value and task_relevance]
        if identity_clear and semantic_events['critical_identity_ambiguous']: raise ValueError('IDENTITY_FLAGS_CONFLICT')
        next_action = ('wait_for_semantic_then_replan' if semantic_reasons else
            ('request_next_chunk' if chunk_finished else ('terminate_suffix_and_replan' if deviation else 'continue_after_owner_admission')))
        self.phase = 'IDLE'
        return self._record('CONSISTENCY_CHECKED', {'world_id': self.world['world_id'],
            'world_revision': self.world['world_revision'], 'execution_epoch': self.observation['execution_epoch'],
            'geometry_loss': geometry_loss, 'association_uncertainty': association_uncertainty,
            'visibility': visibility, 'task_relevance': task_relevance,
            'L_chunk': {'terminate_suffix': deviation or bool(semantic_reasons), 'chunk_finished': chunk_finished},
            'A_intent': next_action, 'semantic_intent': 'request_semantic' if semantic_reasons else 'none',
            'semantic_reasons': semantic_reasons, 'cheap_update_preferred_for_geometry_only_change': deviation and identity_clear and not semantic_reasons,
            'not_a_unified_loss_threshold': True, 'native_concurrency': 'UNVERIFIED_DISABLED'})
