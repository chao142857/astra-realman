#!/usr/bin/env python3
"""Thin model request adapter over the frozen RM65Scene executor and existing RPC client."""
import argparse,json,os,queue,signal,socket,threading,time,uuid,traceback
from pathlib import Path
import numpy as np
from rm65_scene import RM65Scene
from run_expert import write_json

class ModelAdapter:
    def __init__(self,scene):
        self.s=scene;self.requests=0;self.executed=0;self.rejected=0;self.decisions=0;self.attempts=0
        self.ended=False;self.carried=False;self.closed=False;self.initial_step=scene.step
        self.started=time.monotonic();self.last_error=None
        self.records=(scene.output/'model_requests.jsonl').open('x',buffering=1)
        self.private=(scene.output/'private_scoring_trace.jsonl').open('x',buffering=1)
        self.initial_object=scene.object_pose();self.initial_z=self.initial_object[2]
        self.score_trace=[];self.max_tracking=0.;self.min_separation=0.
        scene.step_hook=self.record_step
    def record_step(self,when):
        if when!='after_step':return
        s=self.s;q=s.robot.get_qpos();err=float(np.max(np.abs(q[s.arm_indices]-s.arm_target)))
        self.max_tracking=max(self.max_tracking,err)
        seps=[float(p.separation) for c in s.scene.get_contacts() if 'target_cube' in [b.entity.name for b in c.bodies] for p in c.points]
        self.min_separation=min([self.min_separation,*seps])
        row={'step':s.step,'object_pose':s.object_pose(),'closed':self.closed,'qpos':q.tolist(),
             'tracking_error_max_rad':err,'pad_gap_m':s.state()['actual_pad_gap_m'],
             'grasp_center':s.state()['actual_grasp_center_world'],'bilateral_contact':s.bilateral_pad_contact()}
        self.private.write(json.dumps(row)+'\n');self.score_trace.append(row)
    def observe(self):
        r=self.s.observe();s=self.s;flange=s.links['Link6'].get_pose().to_transformation_matrix()
        r['robot_geometry']={'pose_format':'world meters, quaternion wxyz; orientation is Link6 flange orientation',
            'move_pose_position':'actual mean of two distal pad faces; current gripper-dependent offset is applied by executor',
            'flange_to_actual_pad_center_local_m':(flange[:3,:3].T@(s.pads().mean(0)-flange[:3,3])).tolist(),
            'gripper_opening':'1=open, 0=close; bilateral contact hold remains enabled',
            'world_reference':'robot base on temporary stand; table surface world z=0; +z up',
            'camera_calibration':{name:{'pose_world_xyz_wxyz':[*map(float,c.get_pose().p),*map(float,c.get_pose().q)],
                                         'intrinsic':c.get_intrinsic_matrix().tolist(),
                                         'camera_axes':'SAPIEN +x forward, +y left, +z up'} for name,c in s.cameras.items() if name in ['fixed','wrist']}}
        write_json(Path(r['images']['fixed']).parent/'model_observation.json',r);return r
    def update_payload(self):
        s=self.s;table_loaded=False
        for c in s.scene.get_contacts():
            if set(b.entity.name for b in c.bodies)=={'target_cube','table'}:
                table_loaded|=any(p.separation<=.0002 and np.linalg.norm(p.impulse)>1e-6 for p in c.points)
        carry=self.closed and s.bilateral_pad_contact() and not table_loaded
        if carry and not self.carried:s.set_planning_payload(True);self.carried=True
        elif not self.closed and self.carried:s.set_planning_payload(False);self.carried=False
    def dispatch(self,r):
        s=self.s;method=r.get('method')
        if method=='observe' and set(r)=={'method'}:return self.observe()
        if method=='get_state' and set(r)=={'method'}:return {'ok':True,'state':s.state()}
        if method=='finish':return self.finish(r.get('reason','model ended control'))
        if method!='chunk' or set(r)!={'method','observation_id','actions','reason'}:raise ValueError('REQUEST_SCHEMA')
        if self.ended or s.stopped.is_set():raise RuntimeError('CONTROL_ENDED_OR_STOPPED')
        actions=r['actions']
        if not isinstance(actions,list) or not 1<=len(actions)<=3:raise ValueError('CHUNK_SIZE')
        self.decisions+=1;self.requests+=len(actions)
        self.records.write(json.dumps({'decision':self.decisions,'request':r,'time':time.monotonic()})+'\n')
        if self.requests>60:raise ValueError('ACTION_REQUEST_BUDGET')
        if not s.latest or r['observation_id']!=s.latest['id'] or s.latest['consumed'] or time.monotonic()-s.latest['time']>180:
            self.rejected+=len(actions);raise ValueError('STALE_CONSUMED_OR_EXPIRED_OBSERVATION')
        s.latest['consumed']=True;results=[]
        for a in actions:
            try:
                typ=a.get('type');before=s.state()
                if typ=='move_pose' and set(a)=={'type','pose'}:
                    self.update_payload();res=s.move_tcp(a['pose'])
                elif typ=='move_delta' and set(a)=={'type','delta'}:
                    delta=np.asarray(a['delta'],float)
                    if delta.shape!=(3,) or not np.isfinite(delta).all():raise ValueError('INVALID_DELTA')
                    self.update_payload();state=s.state()
                    res=s.move_tcp([*(np.array(state['actual_grasp_center_world'])+delta),*state['flange_pose_world'][3:]])
                elif typ=='gripper' and set(a)=={'type','opening'}:
                    opening=a['opening']
                    if isinstance(opening,bool) or not isinstance(opening,(int,float)) or not np.isfinite(opening) or not 0<=opening<=1:raise ValueError('INVALID_OPENING')
                    closing=-.91*(1-opening)<float(s.robot.get_qpos()[s.master])
                    if closing and not self.closed:
                        if self.attempts>=2:raise ValueError('GRASP_ATTEMPT_BUDGET')
                        self.attempts+=1
                    if not closing:self.closed=False  # Intentional opening is release, not a dropped closed grasp.
                    res=s.gripper(opening);self.closed=closing
                    self.update_payload()
                    res={k:v for k,v in res.items() if k!='contact_latch'}
                elif typ=='hold' and set(a)=={'type','seconds'}:
                    secs=a['seconds']
                    if isinstance(secs,bool) or not isinstance(secs,(int,float)) or not np.isfinite(secs) or not 0<secs<=2:raise ValueError('INVALID_HOLD')
                    s.tick(round(secs/s.cfg['scene']['dt']));res={'ok':True,'after':s.state()}
                else:raise ValueError('ACTION_SCHEMA')
                if res.get('ok'):self.executed+=1
                else:self.rejected+=1
                safe={k:v for k,v in res.items() if k!='before'};results.append({'action':a,'result':safe})
                if not res.get('ok'):break
            except Exception as exc:
                self.last_error=repr(exc);self.rejected+=1
                results.append({'action':a,'result':{'ok':False,'error':repr(exc),'state':s.state()}});break
        out={'ok':all(x['result']['ok'] for x in results),'results':results,
             'unexecuted_count':len(actions)-len(results),'counts':self.counts()}
        self.records.write(json.dumps({'decision':self.decisions,'response':out})+'\n')
        return out
    def counts(self):return {'model_action_decisions':self.decisions,'action_requests':self.requests,'executed_actions':self.executed,'rejected_actions':self.rejected,'grasp_attempts':self.attempts}
    def finish(self,reason):
        if self.ended:raise ValueError('ALREADY_SCORED')
        self.ended=True;self.decisions+=1;s=self.s
        # Control is irreversibly closed before settling/scoring reads are exposed.
        held=[]
        if not s.stopped.is_set():
            for _ in range(300):s.tick(1);held.append(s.object_pose()[:3])
        rows=self.score_trace;best_run=[];current=[];max_lift=0.;dropped=False;lifted=False;reference=None;lost_steps=0
        for row in rows:
            lift=row['object_pose'][2]-self.initial_z;max_lift=max(max_lift,lift)
            if lift>=.05 and row['closed']:
                current.append(lift);lifted=True
                if reference is None:reference=np.array(row['object_pose'][:3])-row['grasp_center']
                if len(current)>len(best_run):best_run=current.copy()
            else:
                current=[]
            slip=reference is not None and np.linalg.norm(np.array(row['object_pose'][:3])-row['grasp_center']-reference)>.03
            lost_steps=lost_steps+1 if lifted and row['closed'] and not row['bilateral_contact'] and slip else 0
            if lost_steps>=20:dropped=True
        final=s.object_pose();zone=s.cfg['scene']['place_zone_xy'];err=float(np.linalg.norm(np.array(final[:2])-zone))
        vel=s.cube_body.get_linear_velocity();placed=err<s.cfg['scene']['place_zone_radius_m'] and abs(final[2]-.025)<.005
        released=not self.closed and s.state()['actual_pad_gap_m']>.07
        stable=bool(held) and float(np.max(np.ptp(held,axis=0)))<.002 and float(np.linalg.norm(vel))<.01
        ok=len(best_run)>=300 and placed and released and stable and not s.stopped.is_set() and not dropped
        result={'status':'PASS' if ok else 'FAIL','reason':reason,**self.counts(),'model_decisions_including_finish':self.decisions,
                'max_lift_m':max_lift,'longest_closed_hold_steps_above_50mm':len(best_run),
                'hold_minimum_lift_m':min(best_run) if len(best_run)>=300 else None,
                'final_object_pose':final,'placement_xy_error_m':err,'released':released,'stable_in_target':placed and stable,
                'dropped_while_closed':dropped,'max_tracking_error_rad':self.max_tracking,
                'minimum_physx_object_contact_separation_m':self.min_separation,'safety_abort':s.stopped.is_set(),
                'last_error':self.last_error,'elapsed_control_s':time.monotonic()-self.started,
                'execution_assistance':'contact latch + finite preload/drive; FCL payload geometry from simulator, not RGB-only execution',
                'blind_test':False,'video':str(s.output/'execution.mp4')}
        write_json(s.output/'final_score.json',result);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage');p.add_argument('--cameras',nargs='+');p.add_argument('--output',type=Path,required=True);p.add_argument('--socket',type=Path,required=True);a=p.parse_args()
    if a.output.exists() or a.socket.exists():raise RuntimeError('REFUSING_REUSE')
    s=RM65Scene(a.output);adapter=None;listener=None;started=time.monotonic();code=0
    def stop_signal(*_):s.stopped.set();s.shutdown.set()
    signal.signal(signal.SIGINT,stop_signal);signal.signal(signal.SIGTERM,stop_signal)
    try:
        # Generic center-workspace preparation, independent of any object/zone coordinate.
        prep=s.move_tcp([.30,0.,.15,0.,1.,0.,0.])
        if not prep['ok']:raise RuntimeError('GENERIC_PREPARATION_FAILED')
        adapter=ModelAdapter(s);s.start_video();jobs=queue.Queue(maxsize=1)
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(str(a.socket));os.chmod(a.socket,0o600);listener.listen(4);listener.settimeout(.2)
        def handle(c):
            with c:
                try:
                    c.settimeout(150);raw=c.makefile('rb').readline(16385)
                    if len(raw)>16384 or not raw.endswith(b'\n'):raise ValueError('REQUEST_FRAMING')
                    r=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('NONFINITE')))
                    if r=={'method':'health'}:out=s.diag.health()
                    elif r in ({'method':'stop'},{'method':'shutdown'}):
                        s.stopped.set()
                        if r['method']=='shutdown':s.shutdown.set()
                        out={'ok':True,'stopped':True}
                    else:
                        response=queue.Queue(maxsize=1);jobs.put_nowait((r,response));out=response.get(timeout=140)
                except Exception as exc:out={'ok':False,'error':repr(exc)}
                c.sendall(json.dumps(out,allow_nan=False).encode()+b'\n')
        def accept():
            while not s.shutdown.is_set():
                try:c,_=listener.accept()
                except socket.timeout:continue
                except OSError:break
                threading.Thread(target=handle,args=(c,),daemon=True).start()
        threading.Thread(target=accept,daemon=True).start()
        write_json(a.output/'ready.json',{'pid':os.getpid(),'socket':str(a.socket),'mode':'RM65_MODEL_DEVELOPMENT'})
        print('BRIDGE_READY '+str(a.socket),flush=True)
        while not s.shutdown.is_set() and time.monotonic()-started<2380:
            try:r,response=jobs.get(timeout=.2)
            except queue.Empty:continue
            s.diag.begin(uuid.uuid4().hex,r.get('method'),s.step)
            try:out=adapter.dispatch(r)
            except Exception as exc:out={'ok':False,'error':repr(exc)}
            s.diag.complete(out,s.step);response.put(out)
    except Exception as exc:
        code=1;traceback.print_exc();write_json(a.output/'infrastructure_error.json',{'error':repr(exc)})
    finally:
        if listener:listener.close();a.socket.unlink(missing_ok=True)
        if adapter:
            if not adapter.ended:write_json(a.output/'incomplete.json',{'status':'INCOMPLETE',**adapter.counts()})
            adapter.records.close();adapter.private.close()
        s.close();write_json(a.output/'closed.json',{'closed':True,'elapsed_s':time.monotonic()-started,'returncode':code})
    return code
if __name__=='__main__':raise SystemExit(main())
