"""All records label decision vs skill vs mock/raw transport; no fabricated Astra calls."""
import contextlib,copy,hashlib,json,time,zipfile
from pathlib import Path
class Recorder:
    def __init__(self,root):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.sequence=0;self.rows=[];self.objects={};self.started=time.monotonic()
    def emit(self,kind,value):
        self.sequence+=1;row={'sequence':self.sequence,'timestamp':time.time(),'kind':kind,'data':copy.deepcopy(value)};self.rows.append(row)
        with (self.root/'events.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    def begin_object(self,obj):
        self.objects.setdefault(obj,{'started':time.monotonic(),'astra_calls':0,'synthetic_decisions':0,'model_latency_s':0.,'arm_motion_s':0.,'camera_readback_s':0.,'gripper_s':0.,'handoff_s':0.,'recovery_s':0.,'successful_handoff':False,'successful_sort':False,'internal_action_count':0})
    @contextlib.contextmanager
    def timed(self,obj,key):
        start=time.monotonic()
        try:yield
        finally:
            if obj in self.objects:self.objects[obj][key]+=time.monotonic()-start
    def metrics(self):
        return {obj:{**{k:v for k,v in d.items() if k not in ('started','finished')},'seconds_per_object':d.get('finished',time.monotonic())-d['started'],'calls_per_object':d['astra_calls']} for obj,d in self.objects.items()}
    def export(self,state):
        summary={'source':'SYNTHETIC_ONLY','model':'gpt-6-astra','requested_effort':'medium','real_model_calls':0,'real_hardware_calls':0,
          'completed_objects':state.completed_objects,'failed_objects':state.failed_objects,'wall_time_s':time.monotonic()-self.started,
          'per_object':self.metrics(),'timing_note':'mock wall timings only; nested categories must not be summed; no real latency claim','state':state.snapshot()}
        (self.root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        from bimanual_demo.gui_contract import snapshot
        (self.root/'gui_state.json').write_text(json.dumps(snapshot(state,self.metrics()),indent=2)+'\n')
        files={str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file() and p.suffix!='.zip' and p.name!='manifest.json'}
        (self.root/'manifest.json').write_text(json.dumps({'schema':'bimanual-evidence-v1','source':'SYNTHETIC_ONLY','review_status':'UNREVIEWED','files':files},indent=2)+'\n')
        with zipfile.ZipFile(self.root/'capture_snapshot.zip','w',zipfile.ZIP_DEFLATED) as z:
            for p in self.root.rglob('*'):
                if p.is_file() and p.suffix!='.zip':z.write(p,str(p.relative_to(self.root)))
        return summary
