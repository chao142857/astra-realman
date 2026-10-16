"""One new, table-initial full-task episode. Existing atomic gate reused."""
import argparse,json,uuid
from pathlib import Path
from transfer_gate import Gate as BaseGate, ROOT, sha, save

VERSION='rm65.full_table_chunk.exploration.v1'
PARAMETERS={'client_timeout_s':180,'server_timeout_s':190,'workers':1,
    'model':'gpt-6-astra','reasoning':'medium','ephemeral':True,'action_interface':'chunk_v2',
    'right_hold_control':'master_damping0_v3','max_decisions':16,'shadow_dispatches':0,
    'execution_host':'yanglab','layout_base_separation_m':1.1,'automatic_retries':0}


def hashes():
    # Freeze the existing single-task source/dependency surface, not historical
    # evidence or any ledger. No source edits are permitted after preparation.
    result={p.name:sha(p) for pattern in ('*.py','*.sh','*.json') for p in sorted(ROOT.glob(pattern))}
    repo=ROOT.parents[1]
    for name in ('codex_astra_mac_bridge.py','structured_outputs.py'):
        result['production/'+name]=sha(repo/'astra_realman_harness/scripts'/name)
    for name in ('spatial_eval/mac_bridge.py','lab/pilot02_runtime.py','lab/pilot02_dispatcher.py'):
        result['transport/'+name]=sha(repo/'experiments/spatial_input_eval_v0'/name)
    return result


def new_root(root):
    path=Path(root).resolve();allowed=ROOT/'evidence/full_task_runs'
    fixture=any(p.startswith('rm65-full-fixture-') for p in path.parts)
    if not fixture and (not path.is_relative_to(allowed) or path==allowed):raise ValueError('NEW_FULL_TASK_ROOT_REQUIRED')
    return path


def prepare(root):
    root=new_root(root);root.mkdir(parents=True,exist_ok=False,mode=0o700)
    state={'version':VERSION,'batch_id':uuid.uuid4().hex,'output_root':str(root),
        'task':'handoff_place_full','source_hashes':hashes(),'parameters':PARAMETERS,
        'status':'DRAFT','authorization':None,'reserved_budget':0,'runs':[],'shadow_validated':False}
    save(root/'ledger.json',state)
    grant={k:state[k] for k in ('version','batch_id','output_root','task','source_hashes')}
    grant.update(PARAMETERS,generation_authorized=False,max_dispatches=0,
        proposed_max_dispatches=16,user_authorization_statement='')
    save(root/'authorization_REQUEST_NOT_GRANTED.json',grant)
    return state


class Gate(BaseGate):
    version=VERSION;task='handoff_place_full';requires_shadow=False;max_total=16;max_execute=16
    extra_grant_parameters=PARAMETERS
    new_root=staticmethod(new_root);hashes=staticmethod(hashes)

    def accept(self,folder):
        from chunk_handoff_task import accept_result
        return accept_result(folder)

    def __init__(self,root,authorization,preflight,config,stage='execute'):
        if stage!='execute':raise ValueError('FULL_TASK_NO_SHADOW')
        super().__init__(root,authorization,preflight,config,stage)
        if self.state.get('parameters')!=PARAMETERS:
            self.close();raise ValueError('FULL_TASK_PARAMETERS_CHANGED')
        # A new episode cannot be restarted from an otherwise valid partial run.
        if self.state['runs']:
            self.stop('EPISODE_RESTART_FORBIDDEN');self.close();raise ValueError('EPISODE_RESTART_FORBIDDEN')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',type=Path,required=True)
    print(json.dumps(prepare(p.parse_args().prepare),indent=2))
