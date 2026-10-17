"""Existing console projection and offline-only launch for real chunk migration."""
import json
import uuid
from astra_gui import Console, load
from io_utils import ROOT
from real_chunk_adapter import FakeBackend, OfflineChunkAdapter, BLOCKERS, parse_chunk, save


def fixture():
    # Coordinate-contract test only: neither a grasp nor a handoff reference.
    return {'done':False,'stages':[{'mode':'sequential','observe_s':.5,'actions':[
        {'arm':'left','kind':'tcp','waypoints_world_wxyz':[[.01,0,.3,1,0,0,0]]},
        {'arm':'left','kind':'tcp','waypoints_world_wxyz':[[.01,.01,.3,1,0,0,0]]}]},
        {'mode':'parallel','observe_s':.5,'actions':[
            {'arm':'left','kind':'gripper','opening_fraction':.15,'contact_mode':'position'},
            {'arm':'right','kind':'gripper','opening_fraction':1.,'contact_mode':'position'}]}]}


def chunk_evidence(step):
    chunk=load(step/'parsed_chunk.json');result=load(step/'chunk_result.json')
    status=result.get('status','OUTCOME_UNKNOWN')
    ops=result.get('operations',[])
    try:raw=(step/'raw_proposal.txt').read_text()
    except OSError:raw=None
    return {'step':step.name,'action':chunk,'operations':ops,'status':status,'stage':status,
        'action_summary':{'text':f'chunk · {len(ops)} 个有序操作 · 离线模拟'},
        'result_text':status+' · 不代表物理抓取成功','failure_reason':result.get('reason'),
        'hardware_commands_sent':0,'dispatch_started':False,'diagnostics':{},'backend':{},
        'raw_proposal':raw,'model_output_valid':bool(chunk),'timing':{'execution_s':result.get('elapsed_s')},
        'migration':load(step/'migration.json'),'decision_cameras':[], 'camera_streams':{},
        'task_success':'NOT_ASSESSED'}


class OfflineChunkConsole(Console):
    """Inherits rendering/history only. Cannot start a live runner even by POST."""
    offline_chunk = True
    def __init__(self, *, three_calibration=None, live_cameras=False):
        super().__init__(demo=True,demo_count=0)
        self.three_calibration=three_calibration
        self.live_cameras=live_cameras
        if live_cameras:
            from astra_gui import CameraHub
            self.camera=CameraHub(self.camera.configs,False,4)
    def preflight(self, settings):
        raw=settings.get('raw_proposal',json.dumps(fixture()))
        parse_chunk(raw)
        return {'offline_only':True,'protocol_valid':True,'model_requests':0,
                'hardware_commands_sent':0,'real_execution_ready':False,'blockers':BLOCKERS}
    def start(self, settings):
        self.preflight(settings)
        with self.lock:
            if self.active or self.closing:raise ValueError('CONSOLE_BUSY_OR_CLOSING')
            raw=settings.get('raw_proposal',json.dumps(fixture()))
            run=ROOT/'logs'/('real-chunk-offline-'+uuid.uuid4().hex[:12]);run.mkdir()
            save(run/'SYNTHETIC.json',{'synthetic':True,'physics':False})
            save(run/'history_profile.json',{'profile':'real_chunk_offline_v1','max_steps':1,'phase':'full-pick-place'})
            save(run/'offline_manifest.json',{'generation_authorized':False,'max_dispatches':0,
                'hardware_execution_authorized':False,'historical_ledgers_reused':False})
            self.current_run=run;self.active=True;self.lines.clear();self.error=None
        try:
            result=OfflineChunkAdapter(FakeBackend()).run(raw,run/'step-001')
            save(run/'summary.json',{'status':result['status'],'reason':result['reason'],'steps':1,
                'model_calls':0,'hardware_commands_sent':0,'elapsed_s':result['elapsed_s'],
                'synthetic':True,'task_success':'NOT_ASSESSED'})
            return {'started':True,'offline_only':True,'run':run.name}
        finally:self.active=False
    def annotate(self, body):
        raise ValueError('OFFLINE_FAKE_NOT_PHYSICAL_TASK_EVIDENCE')
    def state(self, selected=None):
        value=super().state(selected)
        from real_calibration_status import inventory
        value['calibration_inventory']=inventory(self.three_calibration)
        value['live_readonly_cameras']=self.live_cameras
        if self.live_cameras:value['demo']=False
        value.update(offline_chunk=True,real_execution_ready=False,real_blockers=BLOCKERS,
                     fixture_proposal=json.dumps(fixture(),ensure_ascii=False,indent=2))
        return value
