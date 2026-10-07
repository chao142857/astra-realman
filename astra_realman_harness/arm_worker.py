"""Persistent process per arm; never share an SDK runtime or handle across workers."""
import copy
import json
import multiprocessing
import time
from pathlib import Path
from io_utils import write_json
from arm_stack import ENDPOINTS,capture_states
from left_terminal import parse,validate_state
from exact_target_feasibility import check_exact_target
from left_executor import RealArmExecutor


def worker_main(arm,connection,stop,root):
    # SDK import/init occurs only inside an explicitly started live child.
    from realman_api2_readonly import SDKReadOnly
    root=Path(root);root.mkdir(parents=True,exist_ok=True);(root/'sdk').mkdir()
    try:
        with SDKReadOnly(root/'sdk') as session:
            if not session.connect(arm,*ENDPOINTS[arm])['connected']:raise RuntimeError('CONNECT_FAILED')
            prepared=None;reads=0;refresh_index=0
            def capture(path):return capture_states(session,path)
            connection.send({'ok':True,'value':'READY'})
            while True:
                request=connection.recv();kind=request['kind']
                if kind=='close':return
                try:
                    if kind=='read':
                        reads+=1;value=capture(root/('read-'+str(reads)))['canonical_states'][arm]
                    elif kind in ('prepare','refresh'):
                        if kind=='prepare':
                            prepared={'action':request['action'],'step':Path(request['step']),'used':False};prepared['step'].mkdir();refresh_index=0
                            write_json(prepared['step']/'raw_proposal.json',request['action'])
                        elif prepared is None or prepared['used']:raise RuntimeError('NO_REFRESHABLE_PROPOSAL')
                        refresh_index+=1;p=prepared['step']/('preflight-'+str(refresh_index));p.mkdir()
                        obs=capture(p/'state');s=obs['canonical_states'][arm]
                        a=parse(json.dumps(prepared['action'],allow_nan=False),arm,s['work_frame']['id'],s['tool_frame']['id'])
                        errors=validate_state(obs,live=True,max_age_s=3,arm_id=arm,work=s['work_frame']['id'],tool=s['tool_frame']['id'],frame_fingerprints={k:s[k]['definition_fingerprint'] for k in ('work_frame','tool_frame')})
                        if errors:raise RuntimeError('PREFLIGHT:'+','.join(errors))
                        check=check_exact_target(session,a,obs)
                        write_json(p/'check.json',check);prepared.update(obs=obs,check=check)
                        value=check
                    elif kind=='execute':
                        if prepared is None or prepared['used']:raise RuntimeError('NO_PREPARED_ACTION_OR_ALREADY_USED')
                        prepared['used']=True;began=time.time()
                        ex=RealArmExecutor(session,capture,stop,prepared['step'],arm_id=arm)
                        try:
                            value=copy.deepcopy(ex.execute(prepared['action'],prepared['obs'],feasibility=prepared['check']))
                            after=capture(prepared['step']/'after');ex.guard(after)
                            value.update(after_state=after['canonical_states'][arm],started_at=began,finished_at=time.time())
                            write_json(prepared['step']/'worker_result.json',value)
                        except Exception:
                            stop.set();raise
                    else:raise RuntimeError('UNKNOWN_WORKER_REQUEST')
                    connection.send({'ok':True,'value':value})
                except Exception as exc:
                    if kind in ('prepare','refresh','execute'):stop.set()
                    connection.send({'ok':False,'error':type(exc).__name__+':'+str(exc)})
    except BaseException as exc:
        stop.set()
        try:connection.send({'ok':False,'error':type(exc).__name__+':'+str(exc)})
        except Exception:pass
    finally:connection.close()


class ProcessArmWorker:
    def __init__(self,arm,stop,root,timeout_s=120):
        context=multiprocessing.get_context('spawn');self.connection,child=context.Pipe();self.timeout=timeout_s;self.stop=stop
        self.process=context.Process(target=worker_main,args=(arm,child,stop,str(root)),name='realman-'+arm)
        self.process.start();child.close()
        try:self._receive()
        except Exception:self.close();raise
    def _receive(self):
        if not self.connection.poll(self.timeout):
            self.stop.set();raise TimeoutError('WORKER_TIMEOUT_UNKNOWN_DISPATCH_NO_RETRY')
        reply=self.connection.recv()
        if not reply['ok']:raise RuntimeError(reply['error'])
        return reply['value']
    def _rpc(self,kind,**kwargs):self.connection.send({'kind':kind,**kwargs});return self._receive()
    def read(self):return self._rpc('read')
    def prepare(self,action,step):return self._rpc('prepare',action=action,step=str(step))
    def refresh(self):return self._rpc('refresh')
    def execute(self):return self._rpc('execute')
    def close(self):
        if self.process.is_alive():
            try:self.connection.send({'kind':'close'})
            except (BrokenPipeError,OSError):pass
            # Do not terminate an SDK call whose motion outcome is unknown.
            self.process.join(timeout=2)
        self.connection.close()
