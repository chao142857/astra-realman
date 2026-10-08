"""One frozen-input worker slot; reuse lifecycle/environment, add OS isolation."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from PIL import Image
from sim_skills.async_v1 import StubSlot,Rejected
from scripts.codex_astra_mac_bridge import worker_environment,worker_paths


class FullSlot(StubSlot):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.attempts={};self.launches=0
    def mark(self,index,stage,**data):
        row=self.attempts[index];row['stages'].append({'stage':stage,'monotonic':self.clock(),**data});row['status']=stage
        row.update({k:v for k,v in data.items() if k in ('usage_raw','return_code','error')})
        (self.root/('request-%03d'%index)/'attempt.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n')
        self.emit('ATTEMPT_STAGE',{'request':index,'stage':stage,**data})
    def submit_wire(self,wire,obs,*,delay_s,timeout_s,episode_deadline,evidence=None,reuse=None,past=None):
        self.assert_owner()
        if self.cancelled:raise Rejected('STOPPED')
        if self.job or self.pending:raise Rejected('SINGLE_SLOT_OCCUPIED')
        self.calls+=1;run=self.root/('request-%03d'%self.calls)
        run.mkdir(parents=True,exist_ok=False)
        self.attempts[self.calls]={'request':self.calls,'role':wire['role'],'usage_raw':None,'return_code':None,'stages':[]}
        self.mark(self.calls,'PREPARING')
        try:return self._prepare_launch(wire,obs,delay_s=delay_s,timeout_s=timeout_s,episode_deadline=episode_deadline,evidence=evidence,reuse=reuse,past=past)
        except Exception as exc:
            self.mark(self.calls,'FAILED',error=type(exc).__name__+':'+str(exc));raise
    def _prepare_launch(self,wire,obs,*,delay_s,timeout_s,episode_deadline,evidence=None,reuse=None,past=None):
        run=self.root/('request-%03d'%self.calls)
        inp=run/'input_only';inp.mkdir(parents=True,exist_ok=False);(run/'runtime').mkdir();code=run/'worker_code';code.mkdir()
        for name in ('worker.py','rgb.py'):
            (code/name).write_bytes(Path(__file__).with_name(name).read_bytes());(code/name).chmod(0o444)
        w=copy.deepcopy(wire);role=w['role'];attachments=[]
        def attach(path,camera,temporal,representation,box=None):
            image=Image.open(path).convert('RGB');original=image.size
            transform=None
            if box:
                coords=[int(box[0]*original[0]),int(box[1]*original[1]),int(box[2]*original[0]),int(box[3]*original[1])]
                if not (0<=coords[0]<coords[2]<=original[0] and 0<=coords[1]<coords[3]<=original[1]):raise Rejected('ROI_BOUNDS')
                image=image.crop(coords);transform={'bbox_pixels':coords,'source_observation_id':obs['observation_id'],'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
            if role=='E':
                image=image.resize((320,240),Image.Resampling.BILINEAR)
                transform={'kind':'resize_bilinear','source_resolution':list(original),'scale_xy':[320/original[0],240/original[1]]}
            name='image-%d.png'%len(attachments);image.save(inp/name);(inp/name).chmod(0o444)
            rec={'id':obs['observation_id']+':'+camera+':'+temporal+':'+representation,'file':name,'camera':camera,
                 'temporal_role':temporal,'representation':representation,'sha256':hashlib.sha256((inp/name).read_bytes()).hexdigest(),
                 'width':image.width,'height':image.height,'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                 'captured_monotonic':obs['captured_monotonic'],'source_observation_id':obs['observation_id'],'transform':transform}
            if temporal=='past':rec.update(id=past['observation_id']+':fixed:past',source_observation_id=past['observation_id'],captured_monotonic=past['captured_monotonic'])
            rec['id']+=':'+rec['sha256'][:16]
            attachments.append(rec)
        cameras=['assembly','fixed','wrist']
        if role=='A' and evidence:
            selected=evidence['selected_camera']
            box=(reuse['current_roi']['bbox'] if reuse and reuse['current_roi']['status']=='rgb_relocalized' else
                 evidence['bbox'] if evidence['binding']['source_observation_id']==obs['observation_id'] else None)
            if box is not None:cameras=['assembly',selected]
        for camera in cameras:attach(obs['images'][camera],camera,'current','full')
        if role=='A' and evidence and len(cameras)==2:attach(obs['images'][selected],selected,'derived','roi',box)
        if past and len(attachments)<4:attach(past['images']['fixed'],'fixed','past','full')
        if role=='E':
            for cal in w['observation']['calibration'].values():
                cal['intrinsic'][0]=[x*.5 for x in cal['intrinsic'][0]];cal['intrinsic'][1]=[x*.5 for x in cal['intrinsic'][1]]
                cal['resolution']=[320,240]
        w['attachments']=attachments
        raw=json.dumps(w,sort_keys=True,allow_nan=False).encode();digest=hashlib.sha256(raw).hexdigest()
        (inp/'wire.json').write_bytes(raw);(inp/'wire.json').chmod(0o444)
        from sim_skills.full_pnp.wire import schema_for_role,existing_infer_payload
        (run/'schema.json').write_text(json.dumps(schema_for_role(w),sort_keys=True))
        (run/'input_payload.json').write_text(json.dumps(existing_infer_payload(inp),sort_keys=True,allow_nan=False))
        env=worker_environment('/home/alex/.nvm/versions/node/v22.23.2/bin/codex',run)
        (run/'environment.json').write_text(json.dumps(worker_paths('/home/alex/.nvm/versions/node/v22.23.2/bin/codex',run,env),indent=2))
        # No /home workspace, scene, score, script, credentials or network are mounted.
        venv=str(Path(sys.prefix).resolve())
        command=['/usr/bin/bwrap','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
                 '--ro-bind',venv,venv,'--ro-bind',str(inp),'/input','--ro-bind',str(code),'/code',
                 '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--unshare-all','--die-with-parent','--new-session',
                 '--chdir','/input','--setenv','TMPDIR','/tmp',sys.executable,'-B','/code/worker.py','--sha256',digest,'--delay-s',str(delay_s)]
        (run/'command.json').write_text(json.dumps(command,indent=2))
        self.mark(self.calls,'PREPARED',wire_sha256=digest)
        stdout=(run/'worker.json').open('x');stderr=(run/'stderr.log').open('x')
        started=self.clock();deadline=min(started+timeout_s,episode_deadline)
        if started>=deadline:stdout.close();stderr.close();raise Rejected('NO_REQUEST_BUDGET')
        self.mark(self.calls,'LAUNCHING')
        try:proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,env=env,cwd=inp)
        except Exception:stdout.close();stderr.close();raise
        self.launches+=1;self.mark(self.calls,'STARTED',pid=proc.pid)
        self.job={'process':proc,'run':run,'snapshot':w,'digest':digest,'started':started,'deadline':deadline,
                  'candidate_deadline':episode_deadline,'stdout':stdout,'stderr':stderr}
        self.max_in_flight=max(self.max_in_flight,1)
        self.emit('REQUEST_START',{'request':self.calls,'role':role,'pid':proc.pid,'started':started,'deadline':deadline,
                  'snapshot_sha256':digest,'source':'RGB_DELAYED_STUB_NOT_ASTRA','attachments':attachments,
                  'preparation_s':started-wire['binding']['preparation_started_monotonic']})
    def poll(self):
        self.assert_owner()
        if not self.job:return
        job=self.job;proc=job['process']
        if proc.poll() is None:
            if self.clock()>=job['deadline']:self.cancel_job('REQUEST_TIMEOUT')
            return
        self.job=None;job['stdout'].close();job['stderr'].close()
        raw=(job['run']/'worker.json').read_bytes();record=None;error=None
        self.mark(self.calls,'RETURNED',return_code=proc.returncode,raw_sha256=hashlib.sha256(raw).hexdigest(),raw_bytes=len(raw))
        try:
            self.mark(self.calls,'PARSING')
            from sim_skills.full_pnp.wire import strict_json,parse_actual_raw
            if len(raw)>2*1024*1024:raise ValueError('RAW_TOO_LARGE')
            record=strict_json(raw)
            self.attempts[self.calls]['usage_raw']=record.get('usage') if isinstance(record,dict) else None
            if proc.returncode!=0:raise ValueError('WORKER_NONZERO_EXIT')
            candidate=parse_actual_raw(json.dumps(record['candidate'],allow_nan=False),job['snapshot'])
            self.mark(self.calls,'PARSED',usage_raw=record.get('usage'))
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc);self.mark(self.calls,'PARSE_FAILED',error=error)
        self.emit('REQUEST_END',{'request':self.calls,'return_code':proc.returncode,'record':record if not error else None,
                  'latency_s':self.clock()-job['started'],'error':error})
        if error:raise Rejected('WORKER_RETURN_OR_PARSE_FAILED_NO_RETRY:'+error)
        if self.cancelled or self.clock()>=job['deadline']:
            self.mark(self.calls,'LATE_OR_CANCELLED');return
        self.pending={'candidate':candidate,'snapshot':job['snapshot'],'digest':job['digest'],
                      'deadline':job['candidate_deadline'],'request':self.calls}
        self.max_pending=max(self.max_pending,1);self.mark(self.calls,'READY')
        self.emit('CANDIDATE_READY',{'request':self.calls})
    def cancel_job(self,reason):
        job=self.job
        super().cancel_job(reason)
        if job:
            path=job['run']/'worker.json';raw=path.read_bytes() if path.exists() else b''
            self.mark(self.calls,'CANCELLED',error=reason,raw_sha256=hashlib.sha256(raw).hexdigest(),raw_bytes=len(raw),return_code=job['process'].returncode)
