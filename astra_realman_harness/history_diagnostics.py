"""Measured transitions and four controlled profiles. No hardware or model calls."""
import copy
import json
from collections import deque
from io_utils import ROOT, strict_json
from left_terminal import parse, model_input, SCHEMA_PATH
from execution_telemetry import pose_telemetry

PROFILES = ('H1D0', 'H5D0', 'H1D1', 'H5D1')
DIAGNOSTIC_FIELDS = ('scene_assessment', 'previous_result_assessment',
                     'next_action_intent', 'expected_visible_change')
DECISION_SCHEMA = ROOT/'schema/left_decision.schema.json'
EVIDENCE_RULES = (
    'History contains completed measured transitions, oldest first. Only the three current images '
    'are attached; historical camera references are identifiers, not supplied images. Do not claim '
    'to have seen earlier images. Separate controller return, measured motion, and visible object '
    'state. Closed gripper, SDK success, and model done do not establish holding/grasp/place success. '
    'Without same-camera historical images or reliable historical object evidence, object visual '
    'change and failure time are unknown. Do not infer an achieved object change from an action. '
    'No previous model diagnosis or expected visible change is supplied. Assess the previous '
    'proposal and measured result, not an unprovided remembered intent. Position metres; RPY radians. '
    'Execution residual is applicable only to an actually dispatched arm command. '
    'Keep the original task and choose the next action from current evidence.'
)


def schema_path(profile):
    if profile not in PROFILES:
        raise ValueError('UNKNOWN_PROFILE')
    return DECISION_SCHEMA if profile.endswith('D1') else SCHEMA_PATH


def decode(raw, profile):
    schema_path(profile)
    if profile.endswith('D0'):
        return None, parse(raw)
    value = strict_json(raw)
    if not isinstance(value, dict) or set(value) != {'diagnostics', 'action'}:
        raise ValueError('DECISION_ENVELOPE_FIELDS')
    d = value['diagnostics']
    if not isinstance(d, dict) or set(d) != set(DIAGNOSTIC_FIELDS):
        raise ValueError('DIAGNOSTIC_FIELDS')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 600 for v in d.values()):
        raise ValueError('DIAGNOSTIC_LENGTH_OR_TYPE')
    # The established action parser remains the only authority; no repair or clamping.
    return copy.deepcopy(d), parse(json.dumps(value['action'], allow_nan=False))


def build_transition(episode_id, step, decision, before, after, action, execution, feasibility,
                     *, completed_at, after_errors=(), readback_error=None):
    def state(obs):
        return obs['canonical_states']['left'] if obs else {}
    ds, bs, ats = state(decision), state(before), state(after)
    commands = copy.deepcopy(execution['executed_action'])
    channels = [k for k in ('arm', 'gripper') if commands.get(k) is not None]
    count = execution['hardware_commands_sent']
    if count != len(channels):
        raise ValueError('DISPATCH_COUNT_MISMATCH')
    if execution['status'] == 'REJECTED_IK' and (count or channels):
        raise ValueError('IK_REJECTION_WITH_DISPATCH')
    bp, ap = bs.get('ee_pose'), ats.get('ee_pose')
    target = commands.get('arm')
    telemetry = {}
    if bp and ap:
        pose = target['pose'] if target else bp['xyz_m'] + bp['rpy_rad']
        telemetry = pose_telemetry(bp, {'xyz_m':pose[:3], 'rpy_rad':pose[3:]}, ap)
    residual_applicable = bool(target and bp and ap)
    result = {
        'version':1, 'episode_id':episode_id, 'step':step,
        'decision_observation_id':decision['observation_id'],
        'after_observation_id':after['observation_id'] if after else None,
        'proposed_action':action, 'executed_command':commands,
        'hardware_commands_sent':count, 'executed_channels':channels,
        'execution_status':execution['status'], 'execution_error':execution.get('error'),
        'sdk_result':execution['sdk_result'], 'feasibility':feasibility,
        'decision_observation_pose':ds.get('ee_pose'), 'dispatch_before_pose':bp,
        'actual_after_pose':ap, 'actual_xyz_delta_m':telemetry.get('actual_xyz_delta_m'),
        'translation_residual_m':telemetry.get('translation_residual_m') if residual_applicable else None,
        'rotation_residual_rad':telemetry.get('rotation_residual_rad') if residual_applicable else None,
        'execution_residual_applicable':residual_applicable,
        'residual_reference':'actually dispatched arm target' if residual_applicable else 'not applicable',
        'gripper_before':bs.get('gripper_state'), 'gripper_after':ats.get('gripper_state'),
        'robot_errors':{'before':bs.get('system_error'), 'after':ats.get('system_error')},
        'after_validation_errors':list(after_errors), 'readback_error':readback_error,
        'readback_available':after is not None,
        'object_state':{'holding':'unknown', 'grasp_success':'unknown', 'place_success':'unknown'},
        'timestamps':{'decision':decision['captured_at'], 'dispatch_before':before['captured_at'],
                      'after':after['captured_at'] if after else None, 'completed_at':completed_at},
        'camera_references':{'decision':decision['cameras'], 'after':after['cameras'] if after else []},
        'source':decision.get('source', 'unknown'),
    }
    return copy.deepcopy(result)


class TransitionHistory:
    """Explicit completion insertion, never side effects from repeated input building."""
    def __init__(self, profile, episode_id):
        schema_path(profile)
        self.profile = profile
        self.reset(episode_id)

    def reset(self, episode_id):
        self.episode_id = episode_id
        self.records = deque(maxlen=int(self.profile[1]))
        self.seen = {}
        self.last_step = 0

    def append(self, transition):
        t = copy.deepcopy(transition)
        if t['episode_id'] != self.episode_id:
            raise ValueError('HISTORY_EPISODE_MISMATCH')
        identity = t['step']
        if identity in self.seen:
            if self.seen[identity] != t:
                raise ValueError('HISTORY_CONFLICTING_DUPLICATE')
            return
        if identity <= self.last_step:
            raise ValueError('HISTORY_ORDER')
        self.records.append(t)
        self.seen[identity] = copy.deepcopy(t)
        self.last_step = identity

    def context(self, observation, schema, decision_step):
        for t in self.records:
            if (t['step'] >= decision_step or t['timestamps']['completed_at'] > observation['decision_ready_at']
                or t['timestamps']['after'] is None
                or t['timestamps']['after'] > observation['captured_at']):
                raise ValueError('FUTURE_OR_INCOMPLETE_TRANSITION')
        context = model_input(observation, schema)
        # Never derive history from the partially populated legacy capture.previous.
        context.pop('previous', None)
        context['history'] = copy.deepcopy(list(self.records))
        context['episode_id'] = self.episode_id
        context['decision_step'] = decision_step
        context['evidence_rules'] = EVIDENCE_RULES
        if self.profile.endswith('D1'):
            context['diagnostic_output_instructions'] = (
                'Return strict diagnostics + action JSON in one response. Each diagnostic is one or '
                'two short sentences, at most 600 characters; unknown is allowed. These are public '
                'evidence summaries and predictions, not a transcript of internal reasoning. '
                'Cite current views for scene evidence; do not force a failure explanation.'
            )
        return context
