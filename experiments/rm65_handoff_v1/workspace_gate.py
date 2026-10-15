"""New task policy on the existing atomic single-worker episode gate."""
import uuid
from pathlib import Path
import transfer_gate as original

ROOT = original.ROOT
VERSION = 'rm65.workspace_yield.episode.v1'


def new_root(root):
    p = Path(root).resolve()
    allowed = ROOT / 'evidence/workspace_runs'
    fixture = any(x.startswith('rm65-workspace-fixture-') for x in p.parts)
    if not fixture and (not p.is_relative_to(allowed) or p == allowed):
        raise ValueError('DEDICATED_NEW_WORKSPACE_ROOT_REQUIRED')
    return p


def hashes():
    result = original.hashes()
    for n in ('workspace_task.py', 'workspace_criteria_v1.json', 'evaluate_workspace.py', 'workspace_gate.py', 'workspace_authorized_once.sh', 'diagnose_decision4.py'):
        result[n] = original.sha(ROOT/n)
    return result


def prepare(root):
    root = new_root(root)
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    state = {'version': VERSION, 'batch_id': uuid.uuid4().hex, 'output_root': str(root),
             'task': 'shared_workspace_yield_v1', 'source_hashes': hashes(), 'status': 'DRAFT',
             'authorization': None, 'reserved_budget': 0, 'runs': [], 'shadow_validated': False,
             'planning_budget': {'shadow': 1, 'execute': 7, 'total': 8}}
    original.save(root/'ledger.json', state)
    grant = {k: state[k] for k in ('version', 'batch_id', 'output_root', 'task', 'source_hashes')}
    grant.update(generation_authorized=False, max_dispatches=0, planned_max_dispatches=8,
                 max_shadow_dispatches=1, max_execute_dispatches=7, model='gpt-6-astra',
                 reasoning='medium', ephemeral=True, client_timeout_s=180, server_timeout_s=190,
                 workers=1, user_authorization_statement='')
    original.save(root/'authorization_REQUEST_NOT_GRANTED.json', grant)
    return state


class Gate(original.Gate):
    version = VERSION
    task = 'shared_workspace_yield_v1'
    new_root = staticmethod(new_root)
    hashes = staticmethod(hashes)
    execution_hostname = 'Ubuntu-Robot'
    max_total = 8
    max_execute = 7
    extra_grant_parameters = {'max_shadow_dispatches': 1, 'max_execute_dispatches': 7,
                              'model': 'gpt-6-astra', 'reasoning': 'medium', 'ephemeral': True}
