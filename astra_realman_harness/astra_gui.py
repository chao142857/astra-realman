"""Local experiment console: camera ownership, process supervision, and evidence-based summaries."""
import copy
import hashlib
import hmac
import io
import json
import math
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from io_utils import ROOT, read_json, write_json, new_run
from experiment_launch import ALL_PROFILES, DEFAULTS, validate


def load(path, default=None):
    try:return read_json(path)
    except (OSError,ValueError,TypeError):return {} if default is None else default


def action_summary(action):
    if not action:return {'text':'等待模型决策','translation_mm':None,'rotation_deg':None,'opening_percent':None}
    if action.get('done'):
        return {'text':'模型宣称任务完成；本步不下发动作','translation_mm':[0,0,0],
                'rotation_deg':[0,0,0],'opening_percent':None}
    xyz=[round(v*1000,3) for v in action['translation_m']]
    rpy=[round(math.degrees(v),3) for v in action['rotation_rpy_rad']]
    opening=round(action['gripper_opening']*100,2)
    motion='TCP 保持位置' if not any(xyz+rpy) else 'TCP Δ '+ ' / '.join(f'{k} {v:+g} mm' for k,v in zip('XYZ',xyz))
    if any(rpy):motion+='；RPY '+ ' / '.join(f'{v:+g}°' for v in rpy)
    return {'text':motion+f'；夹爪目标开度 {opening:g}%','translation_mm':xyz,
            'rotation_deg':rpy,'opening_percent':opening}


def step_evidence(step):
    observation=load(step/'input_observation.json') or load(step/'input/observation.json')
    action=load(step/'parsed_action.json');transition=load(step/'transition.json')
    execution=load(step/'execution_result.json');feasibility=load(step/'feasibility.json')
    if not execution:
        previous=load(step/'next_observation.json').get('previous') or {}
        previous=previous.get('last_result',{})
        execution={'status':previous.get('status'),'executed_action':load(step/'executed_action.json'),
                   'sdk_result':load(step/'sdk_result.json'),'hardware_commands_sent':previous.get('hardware_commands_sent')}
    if not transition:
        telemetry=load(step/'pose-telemetry.json');after=load(step/'after_state.json').get('left',{})
        arm_sent=bool(execution.get('executed_action',{}).get('arm'))
        transition={'actual_after_pose':after.get('ee_pose'),'gripper_after':after.get('gripper_state'),
                    'actual_xyz_delta_m':telemetry.get('actual_xyz_delta_m'),
                    'translation_residual_m':telemetry.get('translation_residual_m') if arm_sent else None}
    backend=load(step/'decision/backend_result.json');diagnostics=load(step/'diagnostics.json')
    status=execution.get('status') or feasibility.get('status') or backend.get('status') or 'WAITING'
    reason=transition.get('execution_error') or execution.get('error') or backend.get('error')
    if feasibility.get('status') in ('REJECTED_IK','CHECK_ERROR'):reason=feasibility.get('reason')
    if transition.get('readback_error'):reason=transition['readback_error']
    if transition.get('after_validation_errors'):reason=', '.join(transition['after_validation_errors'])
    residual=transition.get('translation_residual_m')
    result_text={'EXECUTED':'执行成功 · 物体结果待观察','NOOP':'无需下发 · 目标已满足',
                 'REJECTED_IK':'FAIL · IK 拒绝，零下发','STOPPED':'FAIL · 执行已停止',
                 'CHECK_ERROR':'FAIL · IK 接口错误','FAILED':'FAIL · 模型调用或格式错误',
                 'MODEL_DONE':'模型宣称完成 · 尚非独立成功','DRY_RUN_NOT_SENT':'Shadow · 未下发',
                 'PASS_IK':'IK 通过 · 等待执行','COMPLETE':'模型已返回 · 等待执行',
                 'STARTED':'Astra 正在判断','WAITING':'等待决策'}.get(status,status)
    if reason and (transition.get('after_validation_errors') or transition.get('readback_error')):
        result_text='FAIL · 执行后回读异常'
    executed=transition.get('executed_command',execution.get('executed_action',{}))
    return {'step':step.name,'action':action,'action_summary':action_summary(action),
            'diagnostics':diagnostics,'status':status,'result_text':result_text,'failure_reason':reason,
            'executed_command':executed,'hardware_commands_sent':transition.get('hardware_commands_sent',execution.get('hardware_commands_sent')),
            'actual_xyz_delta_mm':[round(v*1000,3) for v in transition['actual_xyz_delta_m']] if transition.get('actual_xyz_delta_m') else None,
            'translation_residual_mm':[round(v*1000,3) for v in residual] if residual is not None else None,
            'gripper_before':transition.get('gripper_before'),'gripper_after':transition.get('gripper_after'),
            'sdk_result':transition.get('sdk_result',execution.get('sdk_result')),
            'feasibility':feasibility,'timing':load(step/'timing.json'),'backend':backend,
            'decision_cameras':observation.get('cameras',[]),
            'observation_id':observation.get('observation_id',transition.get('decision_observation_id')),
            'stage':('实测结果' if transition.get('actual_after_pose') else 'IK / 下发' if feasibility else '模型提案' if action else '模型处理中' if backend else '已观测' if observation else '等待观测'),
            'actual_after_pose':transition.get('actual_after_pose')}


class CameraHub:
    def __init__(self, configs, demo=False, demo_count=4):
        self.configs=configs;self.demo=demo;self.demo_count=demo_count
        self.session=None;self.error=None;self.starting=False
        self.lock=threading.RLock();self.capture_lock=threading.Lock();self.closing=False
        self._thread=None
    def start(self):
        with self.lock:
            if self.demo or self.starting or self.session or self.closing:return
            self.starting=True
        def open_streams():
            session=None
            try:
                from camera_session import CameraSession
                session=CameraSession(self.configs,startup_timeout=3,required_serials=[c["serial"] for c in self.configs[:3]])
                session.__enter__()
                with self.lock:
                    if self.closing:session.__exit__(None,None,None)
                    else:self.session=session
            except Exception as exc:
                if session:session.__exit__(None,None,None)
                self.error=type(exc).__name__+': '+str(exc)
            finally:self.starting=False
        self._thread=threading.Thread(target=open_streams,daemon=True);self._thread.start()
    def status(self):
        rows=[];session=self.session
        for i,c in enumerate(self.configs):
            available=False;age=None;reason=self.error or ('正在连接' if self.starting else '未检测到视频流')
            if self.demo:
                available=i<self.demo_count;age=0 if available else None;reason=None if available else '演示：此相机未接入'
            elif session:
                with session.condition:
                    item=session.latest.get(c['serial']);error=session.errors.get(c['serial'])
                if item:age=max(0,time.monotonic()-item['host_received_monotonic'])
                available=bool(item and not error and age<1)
                reason=error or ('画面已过期' if item and not available else None)
            rows.append({'index':i,'role':c['role'],'serial':c['serial'],'available':available,
                         'age_s':round(age,2) if age is not None else None,'error':reason,
                         'source':'SYNTHETIC' if self.demo else 'LIVE','role_confirmed':c.get('role_confirmed',False)})
        return rows
    def capture(self,path,configs):
        path=Path(path).resolve()
        if not path.is_relative_to((ROOT/'logs').resolve()) or not path.is_dir():raise ValueError('CAPTURE_PATH')
        if any(path.glob('camera-*.png')):raise ValueError('CAPTURE_ALREADY_WRITTEN')
        if self.demo:raise ValueError('DEMO_HAS_NO_HARDWARE_SNAPSHOT')
        if not self.session:raise ValueError(self.error or 'CAMERAS_NOT_READY')
        known={c['serial']:c for c in self.configs}
        # Role/serial and stream settings must match the actual shared producer.
        for c in configs:
            expected=known.get(c.get('serial'))
            if expected is None or any(c.get(k)!=expected.get(k) for k in ('serial','role','width','height','fps','role_confirmed')):
                raise ValueError('CAMERA_CONFIGURATION_MISMATCH')
        requested=[known[c['serial']] for c in configs]
        with self.capture_lock:images,failures,metrics=self.session.snapshot(path,configs=requested)
        return {'images':images,'failures':failures,'metrics':metrics}
    def image(self,index):
        if not 0<=index<len(self.configs):raise ValueError('CAMERA_INDEX')
        if self.demo:
            if index>=self.demo_count:raise ValueError('CAMERA_UNAVAILABLE')
            return demo_svg(index).encode(),'image/svg+xml'
        session=self.session
        if not session:raise ValueError('CAMERAS_NOT_READY')
        serial=self.configs[index]['serial']
        with session.condition:
            item=dict(session.latest.get(serial,{}));error=session.errors.get(serial)
        if not item or error or time.monotonic()-item['host_received_monotonic']>1:raise ValueError(error or 'FRAME_UNAVAILABLE')
        h,w,_=item['shape']
        try:
            from PIL import Image
            image=Image.frombytes('RGB',(w,h),item['_pixels'],'raw','RGB',item['_stride'])
            out=io.BytesIO();image.save(out,format='JPEG',quality=78)
            return out.getvalue(),'image/jpeg'
        except ImportError:
            import struct,zlib
            from observation import _chunk
            pixels=b''.join(b'\0'+item['_pixels'][y*item['_stride']:y*item['_stride']+w*3] for y in range(h))
            body=b'\x89PNG\r\n\x1a\n'+_chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+_chunk(b'IDAT',zlib.compress(pixels))+_chunk(b'IEND',b'')
            return body,'image/png'
    def close(self):
        with self.lock:self.closing=True;session=self.session;self.session=None
        if session:session.__exit__(None,None,None)
        if self._thread:self._thread.join(timeout=8)


def demo_svg(index):
    # Native vector mock scene; permanently labelled synthetic, never a real camera image.
    rotate=[-7,0,5,10][index];cx=[345,315,345,355][index];cy=[235,250,270,245][index]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#202e39"/><stop offset="1" stop-color="#101a23"/></linearGradient><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#55717b" stroke-opacity=".16"/></pattern><radialGradient id="ball"><stop stop-color="#e0f584"/><stop offset="1" stop-color="#8ba941"/></radialGradient></defs>
<rect width="640" height="480" fill="url(#bg)"/><path d="M-40 115L510 55 750 480H0Z" fill="#283b43"/>
<g transform="rotate({rotate} 320 240)"><rect x="30" y="120" width="600" height="350" fill="url(#grid)"/>
<ellipse cx="350" cy="344" rx="100" ry="32" fill="#060e14" opacity=".45"/>
<path d="M228 273L415 250 456 326 260 354Z" fill="#5b737a"/><path d="M240 273L407 262 439 320 270 341Z" fill="#172931"/><path d="M260 354L456 326V353L263 386Z" fill="#405b64"/>
<path d="M85 -25L157 35 260 149 303 190" fill="none" stroke="#0c151c" stroke-width="73"/>
<path d="M85 -25L157 35 260 149 303 190" fill="none" stroke="#a5b7bd" stroke-width="52"/>
<circle cx="158" cy="35" r="29" fill="#d6e0e1"/><circle cx="258" cy="147" r="25" fill="#bfcdd0"/><circle cx="258" cy="147" r="12" fill="#526971"/>
<path d="M298 183L322 204" stroke="#d5e0e1" stroke-width="47"/>
<path d="M307 212L306 255 327 270M345 205L364 244 351 266" stroke="#dae2e1" stroke-width="12" fill="none"/>
<circle cx="{cx}" cy="{cy}" r="24" fill="url(#ball)"/><path d="M{cx-20} {cy-12}Q{cx+8} {cy-8} {cx+10} {cy+21}" fill="none" stroke="#f4f5c4" stroke-width="2"/>
</g><path d="M300 240H340M320 220V260" stroke="#b9eece" stroke-opacity=".4"/>
<rect x="18" y="436" width="259" height="26" rx="6" fill="#0d171d" opacity=".85"/><text x="29" y="453" font-family="monospace" font-size="12" fill="#c4d4d8">SYNTHETIC DEMO / NO CAMERA INPUT</text></svg>'''


class Console:
    def __init__(self, *, demo=False, cameras_only=False, demo_count=4, python=sys.executable, lock_path=None):
        self.demo=demo;self.cameras_only=cameras_only;self.python=python
        self.lock_path=lock_path or Path('/home/tongji/alex/astra_realman_harness/logs/auto-pick.lock')
        self.token=secrets.token_hex(32);self.url=None
        self.camera=CameraHub(read_json(ROOT/'config/left_terminal_fourview.json')['cameras'],demo,demo_count)
        (ROOT/'logs').mkdir(exist_ok=True)
        self.session=new_run(ROOT/'logs'/('gui-session-'+uuid.uuid4().hex[:10]))
        self.lock=threading.RLock();self.process=None;self.active=False;self.current_run=None
        self.return_code=None;self.stop_requested=False;self.error=None;self.started_at=None
        self.settings=dict(DEFAULTS);self.lines=deque(maxlen=600);self.demo_stop=threading.Event()
        self.closing=False;self.console_sequence=0;self.last_budget=False
    def start(self,settings):
        settings=validate(settings)
        from launch_provenance import snapshot
        with self.lock:
            if self.closing:raise ValueError('CONSOLE_CLOSING')
            if self.cameras_only:raise ValueError('CAMERAS_ONLY')
            if self.active:raise ValueError('已有实验运行中')
            if not self.demo:
                required=4 if settings['profile']=='legacy4' else 3
                if not all(c['available'] for c in self.camera.status()[:required]):
                    raise ValueError(f'该实验需要前 {required} 路相机，当前未全部就绪；预览可继续使用已有相机。')
            self.active=True;self.stop_requested=False;self.error=None;self.return_code=None
            self.current_run=None;self.started_at=time.time();self.settings=settings;self.lines.clear();self.last_budget=False
            self.console_sequence+=1;launch_id=uuid.uuid4().hex[:8]
            settings_path=self.session/(launch_id+'-settings.json');write_json(settings_path,settings)
            self.output_path=self.session/(launch_id+'-console.log')
            command=[self.python,'-u','-I','-B',str(ROOT/'scripts/run_experiment.py'),
                     '--settings',str(settings_path),'--no-preview','--lock-path',str(self.lock_path)]
            self.launch_manifest=snapshot(settings,command,self.lock_path)
            write_json(self.session/(launch_id+'-manifest.json'),self.launch_manifest)
            if self.demo:
                self.demo_stop.clear()
                threading.Thread(target=self._demo_run,daemon=True).start()
            else:
                command=[self.python,'-u','-I','-B',str(ROOT/'scripts/run_experiment.py'),
                         '--settings',str(settings_path),'--no-preview','--lock-path',str(self.lock_path)]
                env=dict(os.environ,ASTRA_CAMERA_HUB_URL=self.url,ASTRA_CAMERA_HUB_TOKEN=self.token)
                try:
                    self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                        text=True,encoding='utf-8',errors='replace',bufsize=1,cwd=ROOT,env=env)
                except Exception as exc:
                    self.active=False;self.error=str(exc);raise
                threading.Thread(target=self._read_output,args=(self.process,),daemon=True).start()
        return {'started':True,'demo':self.demo}
    def preflight(self,settings):
        from launch_provenance import equivalent_command
        settings=validate(settings)
        count=4 if settings['profile']=='legacy4' else 3
        cameras=self.camera.status()
        return {'command':equivalent_command(settings,self.python,self.lock_path),
                'required_camera_count':count,'required_cameras_ready':all(c['available'] for c in cameras[:count]),
                'cameras':cameras,'active':self.active,'synthetic':self.demo,
                'backend_config_present':(ROOT/'config/decision_backend.json').is_file(),
                'bridge_token_present':(ROOT/'config/codex_astra_bridge.token').is_file(),
                'bridge_and_robot':'未探测；此检查不调用模型、不连接机器人。单次 Shadow 可显式验证观测与模型通路。',
                'next':'回合结束 → 导出证据 → 人工复位场景 → 手动载入下一组'}
    def _line(self,line):
        with self.lock:self.lines.append(line.rstrip()[:16000])
        with self.output_path.open('a',encoding='utf-8') as f:f.write(line if line.endswith('\n') else line+'\n')
        if line.startswith('RUN → '):
            try:
                run=Path(json.loads(line.split(' → ',1)[1])['log']).resolve()
                if run.is_relative_to((ROOT/'logs').resolve()) and run.is_dir():
                    self.current_run=run
                    metadata=run/'gui_launch.json'
                    if not metadata.exists():
                        sources=['astra_gui.py','camera_session.py','shared_cameras.py','experiment_launch.py','scripts/run_experiment.py']
                        write_json(metadata,{'console_log':str(self.output_path),'settings':self.settings,'gui_session':str(self.session),
                            'launch_manifest':self.launch_manifest,
                            'source_manifest':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}})
            except (ValueError,KeyError,TypeError):pass
        if line.startswith('BUDGET → '):
            self.last_budget=True
            if self.current_run and not (self.current_run/'gui_budget.json').exists():
                write_json(self.current_run/'gui_budget.json',{'status':'WALL_BUDGET_EXHAUSTED','source':'legacy wrapper monotonic timer'})
    def _read_output(self,process):
        try:
            for line in process.stdout:self._line(line)
            code=process.wait()
            with self.lock:
                self.return_code=code;self.active=False
                if code and self.current_run is None:self.error='启动失败；请查看原始终端输出。'
        except Exception as exc:
            with self.lock:self.error=str(exc)
        finally:
            if process.stdout:process.stdout.close()
            if process.stdin:process.stdin.close()
            if process.poll() is not None:self.active=False
    def stop(self):
        with self.lock:
            if not self.active:return {'stopped':False,'reason':'NO_ACTIVE_RUN'}
            self.stop_requested=True
            if self.demo:self.demo_stop.set()
            elif self.process and self.process.poll() is None:
                # Existing cooperative signal handler stops new actions. Never SIGKILL hardware code.
                self.process.send_signal(signal.SIGINT)
        return {'stop_requested':True,'note':'等待当前阻塞 SDK 调用返回；这不是硬件急停。'}
    def runs(self):
        rows=[]
        for run in sorted((ROOT/'logs').iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
            if not run.is_dir() or not ((run/'summary.json').exists() or (self.current_run==run)):continue
            summary=load(run/'summary.json');profile=load(run/'history_profile.json')
            launch=load(run/'gui_launch.json').get('settings',{})
            profile=dict(profile,**launch)
            rows.append({'id':run.name,'profile':profile.get('profile','legacy'),'status':summary.get('status','RUNNING'),
                         'synthetic':(run/'SYNTHETIC.json').exists(),'phase':profile.get('phase')})
            if len(rows)>=50:break
        return rows
    def resolve_run(self,name):
        if not name:return self.current_run
        if not isinstance(name,str) or Path(name).name!=name:raise ValueError('RUN_ID')
        run=(ROOT/'logs'/name).resolve()
        if run.parent!=(ROOT/'logs').resolve() or not run.is_dir():raise ValueError('RUN_NOT_FOUND')
        if not (run/'summary.json').exists() and run!=self.current_run:raise ValueError('NOT_AN_EPISODE')
        return run
    def state(self,selected=None):
        run=self.resolve_run(selected)
        steps=[];summary={};profile={};labels={}
        if run:
            steps=[step_evidence(p) for p in sorted(run.glob('step-*')) if p.is_dir()]
            summary=load(run/'summary.json');profile=load(run/'history_profile.json');labels=load(run/'independent_observation.json')
            profile=dict(profile,**load(run/'gui_launch.json').get('settings',{}))
        console_lines=list(self.lines)
        if run and run!=self.current_run:
            console_lines=['此回合未保存 GUI 原始终端；可查看该回合 decision/astra_raw.txt 与结构化日志。']
            metadata=load(run/'gui_launch.json')
            path=Path(metadata.get('console_log','/')).resolve()
            if path.is_relative_to((ROOT/'logs').resolve()) and path.is_file():
                with path.open('rb') as stream:
                    stream.seek(max(0,path.stat().st_size-2*1024*1024))
                    console_lines=stream.read().decode('utf-8',errors='replace').splitlines()[-600:]
        latest=steps[-1] if steps else {}
        stable=labels.get('actual_stable_in_basket','unknown')
        if not labels.get('evidence') or not labels.get('observer') or labels.get('episode_id')!=summary.get('episode_id',run.name if run else None):stable='unknown'
        return {'demo':self.demo,'cameras_only':self.cameras_only,'camera_status':self.camera.status(),
                'active':self.active,'stop_requested':self.stop_requested,'started_at':self.started_at,
                'current_run':self.current_run.name if self.current_run else None,'selected_run':run.name if run else None,
                'selected_synthetic':bool(run and (run/'SYNTHETIC.json').exists()),
                'run_path':str(run) if run else None,'settings':self.settings,'summary':summary,'profile':profile,
                'steps':steps,'latest':latest,'independent_success':stable,'labels':labels,
                'return_code':self.return_code,'error':self.error,'budget_expired':bool((run and load(run/'gui_budget.json')) or (run==self.current_run and self.last_budget)),
                'console':console_lines,'console_sequence':self.console_sequence,'runs':self.runs()}
    def annotate(self,body):
        with self.lock:
            run=self.resolve_run(body.get('run'))
            if not run or (self.active and run==self.current_run):raise ValueError('请等该回合结束再标注独立结果。')
            result=body.get('result')
            if result not in ('success','fail','unknown'):raise ValueError('RESULT')
            evidence=body.get('evidence','');observer=body.get('observer','');reason=body.get('reason','')
            if not all(isinstance(v,str) and len(v)<=4000 for v in (evidence,observer,reason)):raise ValueError('LABEL_TEXT')
            if not evidence.strip() or not observer.strip():raise ValueError('请填写观察者和录像/现场观察依据。')
            if result=='fail' and not reason.strip():raise ValueError('请记录观察到的失败现象；原因不确定时写 unknown。')
            old=load(run/'independent_observation.json')
            label=dict(old,episode_id=load(run/'summary.json').get('episode_id',run.name),
                       actual_stable_in_basket={'success':True,'fail':False,'unknown':'unknown'}[result],
                       observer=observer,evidence=evidence,notes=reason,observed_at=time.time(),
                       synthetic=(run/'SYNTHETIC.json').exists())
            event=run/('independent-observation-'+uuid.uuid4().hex+'.json');write_json(event,label)
            temp=run/('label-'+uuid.uuid4().hex+'.tmp');write_json(temp,label)
            os.replace(temp,run/'independent_observation.json')
            return label
    def historical_image(self,run_name,step_name,index):
        run=self.resolve_run(run_name)
        if not run or not step_name.startswith('step-') or Path(step_name).name!=step_name:raise ValueError('STEP')
        step=run/step_name
        # Show exactly the decision input images, never subsequent after images.
        obs=load(step/'input_observation.json') or load(step/'input/observation.json')
        cameras=obs.get('cameras',[])
        if not 0<=index<len(cameras):raise ValueError('NO_IMAGE_FOR_SLOT')
        path=Path(cameras[index]['image_path']).resolve()
        if not path.is_relative_to((ROOT/'logs').resolve()) or path.stat().st_size>8*1024*1024:raise ValueError('IMAGE_PATH')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=cameras[index].get('sha256'):raise ValueError('IMAGE_HASH')
        return data,'image/png'
    def _demo_run(self):
        from fixtures.synthetic_history import observation,action
        from history_diagnostics import build_transition,DIAGNOSTIC_FIELDS
        from left_terminal import command_plan
        settings=dict(self.settings);run=new_run(ROOT/'logs'/('gui-demo-'+uuid.uuid4().hex[:10]))
        self.current_run=run;episode=run.name
        write_json(run/'SYNTHETIC.json',{'synthetic':True,'meaning':'GUI behavior demo only; no model, camera, or hardware.'})
        write_json(run/'history_profile.json',dict(settings,synthetic=True))
        self._line('RUN → '+json.dumps({'log':str(run),'mode':'SYNTHETIC_DEMO'}))
        count=0;start=time.monotonic();status='MAX_STEPS';current=observation(run,0)
        try:
            for i in range(1,min(settings['max_steps'],4)+1):
                if self.demo_stop.is_set():status='STOPPED';break
                if time.monotonic()-start>=settings['wall_budget_s']:status='WALL_BUDGET_EXHAUSTED';break
                current.update(episode_id=episode,task=settings['task'],decision_ready_at=time.time())
                count=i;step=new_run(run/('step-%02d'%i));write_json(step/'input_observation.json',current)
                a=action();a['translation_m']=[[.018,-.012,.008],[.16,0,0],[.012,.006,-.015],[0,0,0]][i-1]
                a['gripper_opening']=[.26,.26,.8,.8][i-1];a['done']=i==4
                self._line('STEP → '+str(i))
                if self.demo_stop.wait(.6):status='STOPPED';break
                write_json(step/'parsed_action.json',a)
                if settings['profile'].endswith('D1'):
                    values=['演示场景：球位于夹爪附近，桌面视角可见框内开口；握持状态仍需观察。',
                            '示例仅展示 SDK、位姿与拒绝反馈。未提供真实前后画面，物体变化为 unknown。',
                            '调整 TCP 与框开口的相对位置，再观察投放条件。',
                            '预期下一帧夹爪更接近开口；这是预测，尚未验证。']
                    write_json(step/'diagnostics.json',dict(zip(DIAGNOSTIC_FIELDS,values)))
                self._line('PARSED ACTION → '+json.dumps(a))
                if self.demo_stop.wait(.8):status='STOPPED';break
                rejected=i==2;plan=command_plan(a,current['canonical_states']['left'])
                commands={'arm':None if rejected else plan['arm'],'gripper':None if rejected else plan['gripper']}
                executed={'status':'REJECTED_IK' if rejected else ('MODEL_DONE' if a['done'] else 'EXECUTED'),
                          'executed_action':commands,'hardware_commands_sent':sum(v is not None for v in commands.values()),
                          'sdk_result':{'called':not rejected and not a['done'],'arm':0 if commands['arm'] else None,'gripper':None},
                          'synthetic':True}
                check={'status':'REJECTED_IK' if rejected else 'PASS_IK','reason':'SYNTHETIC：原目标无 IK 解，未发送运动或夹爪命令。' if rejected else 'SYNTHETIC：可行性通过。'}
                after=observation(run,i)
                stamp=after['canonical_states']['left']['timestamp']
                after['canonical_states']['left']=copy.deepcopy(current['canonical_states']['left'])
                after['canonical_states']['left']['timestamp']=stamp
                if commands['arm']:
                    pose=commands['arm']['pose'];after['canonical_states']['left']['ee_pose'].update(xyz_m=pose[:3],rpy_rad=pose[3:])
                if commands['gripper']:
                    after['canonical_states']['left']['gripper_state']['position']=a['gripper_opening']*1000
                after['canonical_states']['left']['raw_sdk_state']['pose']=after['canonical_states']['left']['ee_pose']['xyz_m']+after['canonical_states']['left']['ee_pose']['rpy_rad']
                before_folder=new_run(step/'pre-execution');write_json(before_folder/'observation.json',current)
                write_json(step/'next_observation.json',after)
                t=build_transition(episode,i,current,current,after,a,executed,check,completed_at=time.time())
                for name,value in [('transition.json',t),('execution_result.json',executed),('feasibility.json',check)]:write_json(step/name,value)
                self._line('EXECUTED ACTION → '+json.dumps(executed));current=after
                if a['done']:status='MODEL_DONE';break
        except Exception as exc:self.error=str(exc);status='STOPPED'
        finally:
            summary={'episode_id':episode,'status':status,'steps':count,'model_calls':0,'hardware_commands_sent':0,
                     'episode_total_s':time.monotonic()-start,'synthetic':True,'independent_success':'unknown',
                     'reason':'HUMAN_STOP' if status=='STOPPED' and self.demo_stop.is_set() else self.error}
            write_json(run/'summary.json',summary);self._line('SUMMARY → '+json.dumps(summary))
            self.active=False;self.return_code=0
    def close(self):
        self.closing=True;self.stop()
        if self.process and self.process.poll() is None:
            # Keep serving shared frames while a blocking arm call finishes/readback occurs.
            return False
        self.camera.close();return True


def make_server(console,port=8877):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def local(self):
            host=self.headers.get('Host','')
            parsed=urlparse('http://'+host)
            return parsed.hostname in ('127.0.0.1','localhost','::1')
        def send(self,data,kind='application/json',status=200):
            if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)))
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            if not self.local():self.send_error(403);return
            u=urlparse(self.path);q=parse_qs(u.query)
            try:
                if u.path=='/':
                    body=(ROOT/'gui/index.html').read_text().replace('__ASTRA_TOKEN__',console.token)
                    return self.send(body.encode(),'text/html; charset=utf-8')
                if u.path in ('/app.js','/style.css'):
                    return self.send((ROOT/'gui'/u.path[1:]).read_bytes(),'text/javascript' if u.path.endswith('.js') else 'text/css')
                if u.path=='/api/state':return self.send(console.state(q.get('run',[None])[0]))
                if u.path.startswith('/api/camera/'):
                    data,kind=console.camera.image(int(u.path.rsplit('/',1)[1]));return self.send(data,kind)
                if u.path=='/api/history-image':
                    data,kind=console.historical_image(q['run'][0],q['step'][0],int(q['index'][0]));return self.send(data,kind)
                if u.path in ('/api/replay','/api/replay-image','/api/evidence-zip','/api/control-template'):
                    from replay_evidence import replay,evidence_zip
                    run=console.resolve_run(q['run'][0]);name=q['step'][0]
                    if not run:raise ValueError('NO_RUN')
                    evidence=replay(run,name)
                    if u.path=='/api/replay':return self.send(evidence)
                    if u.path=='/api/control-template':
                        from offline_diagnostic_controls import annotation_template
                        from scripts.prepare_history_replay import decision_observation
                        return self.send(annotation_template(decision_observation(run/name)))
                    if u.path=='/api/evidence-zip':
                        if console.active and run==console.current_run:raise ValueError('请在回合结束后导出冻结证据。')
                        return self.send(evidence_zip(run,name),'application/zip')
                    if q['stage'][0] not in ('before','decision','after'):raise ValueError('STAGE')
                    pair=next((p for p in evidence['pairs'] if p['serial']==q['serial'][0] and p['role']==q['role'][0]),None)
                    item=pair.get(q['stage'][0]) if pair else None
                    if not item or not item['available']:raise ValueError('IMAGE_MISSING_OR_INVALID')
                    return self.send(Path(item['image_path']).read_bytes(),'image/png')
                if u.path=='/api/prepared-zip':
                    name=q['id'][0]
                    if not name.startswith('offline-controls-') or Path(name).name!=name:raise ValueError('PREPARED_ID')
                    output=(ROOT/'logs'/name).resolve()
                    if output.parent!=(ROOT/'logs').resolve():raise ValueError('PREPARED_PATH')
                    return self.send((output/'prepared-evidence.zip').read_bytes(),'application/zip')
                if u.path=='/api/export':
                    run=console.resolve_run(q['run'][0]);from scripts.report_history_experiment import report
                    return self.send(report(run))
                self.send_error(404)
            except (ValueError,KeyError,OSError) as exc:self.send({'error':str(exc)},status=503 if '/camera/' in u.path else 400)
        def do_POST(self):
            origin=self.headers.get('Origin')
            if (not self.local() or not hmac.compare_digest(self.headers.get('X-Astra-Token',''),console.token)
                or (origin and origin!='http://'+self.headers.get('Host'))):
                self.send_error(403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=32768:raise ValueError('REQUEST_SIZE')
                body=json.loads(self.rfile.read(size));path=urlparse(self.path).path
                if path=='/api/start':result=console.start(body)
                elif path=='/api/preflight':result=console.preflight(body)
                elif path in ('/api/marker','/api/prepare-controls'):
                    with console.lock:
                        run=console.resolve_run(body.get('run'))
                        if not run or console.active:raise ValueError('请先结束当前实验再整理回放。')
                        from replay_evidence import mark,step_folder
                        step=step_folder(run,body['step'])
                        if path=='/api/marker':result=mark(run,body)
                        else:
                            from offline_diagnostic_controls import prepare_controls
                            output=ROOT/'logs'/('offline-controls-'+uuid.uuid4().hex[:12])
                            result=prepare_controls(run,int(step.name.split('-')[1]),output,
                                base_profile=body.get('base_profile','H5D1'),annotation=body.get('annotation'),
                                visual_history_mode=body.get('visual_history_mode','none'),fixed_camera=body.get('fixed_camera','tabletop'))
                            result['output']=str(output)
                elif path=='/api/stop':result=console.stop()
                elif path=='/api/annotate':result=console.annotate(body)
                elif path=='/api/capture':result=console.camera.capture(body['path'],body['cameras'])
                elif path=='/api/rescan':
                    with console.lock:
                        if console.active:raise ValueError('实验运行中不能重启相机流。')
                        previous=console.camera
                        previous.close()
                        console.camera=CameraHub(previous.configs,console.demo,previous.demo_count)
                        console.camera.start()
                    result={'rescan_started':True}
                elif path=='/api/demo-cameras' and console.demo:
                    n=body.get('count')
                    if type(n) is not int or not 0<=n<=4:raise ValueError('CAMERA_COUNT')
                    console.camera.demo_count=n;result={'count':n}
                else:self.send_error(404);return
                self.send(result)
            except (ValueError,KeyError,TypeError,OSError) as exc:self.send({'error':str(exc)},status=400)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    console.url='http://127.0.0.1:'+str(server.server_port)
    return server
