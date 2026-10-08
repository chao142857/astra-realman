"""ENGINEERING_CONTROL_REGRESSION ONLY: one fresh-process grasp control.
No model imports, CLI preflight, calls, networks, hardware or B/F episode.
Read-only telemetry; original physical drives/scene/dispatcher are unchanged.
The shared backend adds contact qualification and contact-loss stopping.
"""
import argparse, json, os, sys, time, traceback, signal, hashlib, subprocess
from pathlib import Path
import numpy as np

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from sim_skills.full_pnp.backend import FullTaskBackend
from sim_skills.full_pnp import dependencies, rgb
from sim_skills.full_pnp.protocol import validate_actions

def plain(x):
    if isinstance(x,np.ndarray):return x.tolist()
    if isinstance(x,np.generic):return x.item()
    raise TypeError(type(x).__name__)
def dump(p,x):p.write_text(json.dumps(x,default=plain,indent=2)+'\n')
def pose(p):return [*map(float,p.p),*map(float,p.q)]
def run(a):
    root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    result={'label':'ENGINEERING_CONTROL_REGRESSION','z_mm':a.z_mm,'opening':a.opening,'real_model_calls':0,'hardware_calls':0,
       'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE,text=True).strip(),
       'source_git_status':subprocess.check_output(['git','status','--short'],cwd=BASE,text=True),
       'source_sha256':{str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),*sorted((BASE/'sim_skills/full_pnp').glob('*.py'))]},
       'command':[sys.executable,*sys.argv],
       'reset':'fresh process; not exact state clone or replay of original private state',
       'controls':'original moves to .15 then selected Z; same raw XY/orientation; original wait step counts 8856/5155; one closure; engineering relative lift .08m and 300-step hold if not aborted',
       'threshold_m':-.002,'status':'INCOMPLETE','actions':[]}
    dump(root/'started.json',result)
    b=None;stream=None;started=time.monotonic();phase='initialization';last=time.monotonic();before=None;deadline=started+180
    def stop(*_):
        if b:b.stop()
        raise RuntimeError('EXTERNAL_STOP')
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        init=time.monotonic();b=FullTaskBackend(a.assets,root/'scene',seed=2,video=False);s=b.s
        result['initialization_wall_s']=time.monotonic()-init;result['initialization_physics_s']=s.step*b.dt
        dump(root/'initial_state.json',s.state())
        stream=(root/'contact_trace.jsonl').open('x',buffering=1)
        def record(kind,extra=None):
            state=s.state();contacts=[]
            for c in s.scene.get_contacts():
                ns=[x.entity.name for x in c.bodies]
                if 'target_cube' not in ns and not any(n in s.pad_vertices for n in ns):continue
                points=[]
                for p in c.points:
                    local={n:(x.get_pose().inv()*__import__('sapien').Pose(p.position)).p.tolist() for n,x in zip(ns,c.bodies)}
                    points.append({'position_world_m':p.position.tolist(),'normal_api':p.normal.tolist(),'separation_m':float(p.separation),
                                   'impulse_api_Ns':p.impulse.tolist(),'point_in_body_local_m':local})
                contacts.append({'names':ns,'shape_types':[type(x).__name__ for x in c.shapes],'points':points})
            master=s.joints[s.master]
            row={'kind':kind,'phase':phase,'wall_monotonic':time.monotonic(),'state':state,'qvel':s.robot.get_qvel().tolist(),
                 'qacc_api':s.robot.get_qacc().tolist(),'external_qf_api':s.robot.get_qf().tolist(),
                 'master_drive_target_rad':float(master.drive_target[0]),'master_drive_velocity_target':float(master.drive_velocity_target[0]),
                 'master_stiffness':master.stiffness,'master_damping':master.damping,'master_force_limit_Nm':master.force_limit,'drive_mode':master.drive_mode,
                 'object_pose':s.object_pose(),'object_linear_velocity':s.cube_body.linear_velocity.tolist(),'object_angular_velocity':s.cube_body.angular_velocity.tolist(),
                 'support_poses':{n:pose(s.links[n].get_pose()) for n in s.pad_vertices},
                 'bilateral_contact':s.bilateral_pad_contact(),'contacts':contacts,'before_step':before,'extra':extra}
            stream.write(json.dumps(row,default=plain)+'\n')
        original_log=s.log
        def log(event,data):
            original_log(event,data)
            if event=='bilateral_contact_latch':record('LATCH_AFTER_TARGET_CHANGE',data)
        s.log=log
        def hook(when):
            nonlocal before,last
            if time.monotonic()>deadline:raise TimeoutError('DIAGNOSTIC_WATCHDOG_180S')
            if when=='before_step':
                delay=last+b.dt-time.monotonic()
                if delay>0:time.sleep(delay)
                if phase in ('closure','lift','hold'):
                    master=s.joints[s.master]
                    before={'step':s.step,'qvel':s.robot.get_qvel().tolist(),'qpos':s.robot.get_qpos().tolist(),
                        'applied_external_qf':s.robot.get_qf().tolist(),
                        'gravity_only_passive_force':s.robot.compute_passive_force(gravity=True,coriolis_and_centrifugal=False).tolist(),
                        'master_target_rad':float(master.drive_target[0]),'force_limit_Nm':master.force_limit}
            else:
                b.private_step_hook(when)
                if phase in ('closure','lift','hold'):record('AFTER_STEP_BEFORE_MONITOR')
                last=time.monotonic()
        s.step_hook=hook
        shapes={}
        for n in s.pad_vertices:
            shapes[n]=[]
            for sh in s.links[n].collision_shapes:
                shapes[n].append({'type':type(sh).__name__,'local_pose':pose(sh.local_pose),'vertices':sh.get_vertices(),
                     'triangles':sh.get_triangles(),'scale':sh.get_scale(),'contact_offset':sh.contact_offset,'rest_offset':sh.rest_offset})
        dump(root/'loaded_collision_geometry.json',shapes)
        dump(root/'solver_and_drive.json',{'solver_position_iterations':s.robot.get_solver_position_iterations(),
             'solver_velocity_iterations':s.robot.get_solver_velocity_iterations(),'cfg':s.cfg,
             'joints':[{k:getattr(j,k) for k in ('name','stiffness','damping','force_limit','drive_mode')} for j in s.joints],
             'telemetry_semantics':'qf is external passive-force feedforward set by original tick, not measured drive torque; contact normal/impulse kept in API ordering; no solver step occurs after STOP'})
        guard_source=None;expected=None
        def guard(action):
            fresh=b.observe();check=dependencies.check([action],guard_source,fresh,rgb.features(guard_source),rgb.features(fresh),model_requirements=['scene_healthy','object_static','object_near_tool'])
            d=float(np.linalg.norm(np.array(fresh['state']['actual_grasp_center_world'])-expected[:3]));ang=dependencies.angle(fresh['state']['flange_pose_world'][3:],expected[3:])
            check['join_error']={'distance_m':d,'rotation_rad':ang}
            if not np.isfinite([d,ang]).all() or d>=.01 or ang>=.05:check['status']='invalid'
            dump(root/'pre_gripper_check.json',check);return fresh,check
        b.gripper_guard=guard
        def dispatch(actions,source=None):
            nonlocal guard_source,expected
            validate_actions(actions);obs=b.observe();source=source or obs
            check=dependencies.check(actions,source,obs,rgb.features(source),rgb.features(obs),model_requirements=['scene_healthy'])
            result['actions'].append({'phase':phase,'actions':actions,'admission_check':check,'start_step':s.step})
            if check['status']!='valid':raise RuntimeError('OWNER_DEPENDENCIES_'+check['status'])
            guard_source=obs;expected=[*obs['state']['actual_grasp_center_world'],*obs['state']['flange_pose_world'][3:]]
            for x in actions:
                if x['type']=='move_pose':expected=x['pose']
            ticket={'owner_admitted':True,'candidate_id':'ENGINEERING_DIAGNOSTIC','commit_observation_id':obs['observation_id']}
            out=b.execute_chunk(actions,ticket,obs);result['actions'][-1].update(response=out,end_step=s.step)
            if not out['ok']:raise RuntimeError('EXECUTION_ABORT:'+str(out))
            return out
        def wait_steps(n):
            for _ in range(n):s.tick(1)
        phase='first_recorded_wait';wait_steps(8856)
        phase='approach';dispatch([{'type':'move_pose','pose':[.36,-.06,.15,0,1,0,0]},{'type':'move_pose','pose':[.36,-.06,a.z_mm/1000,0,1,0,0]}])
        phase='second_recorded_wait';wait_steps(5155)
        result['preclose_step']=s.step;dump(root/'preclose_state.json',s.state());s.start_video()
        phase='closure';record('PRE_CLOSURE');dispatch([{'type':'gripper','opening':a.opening}]);record('POST_CLOSURE')
        result['closure_completed']=True
        phase='lift';p=s.state()['actual_grasp_center_world'];dispatch([{'type':'move_pose','pose':[p[0],p[1],p[2]+.08,0,1,0,0]}])
        phase='hold';wait_steps(300);record('POST_HOLD')
        result['status']='CONTROL_COMPLETED'
    except Exception as exc:
        failure=str(exc)
        result.update(status='SAFETY_ABORT' if 'PAD_CONTACT_PENETRATION' in failure else 'GRASP_FAILED' if 'GRASP_CONTACT_' in failure else 'DIAGNOSTIC_ERROR',error=repr(exc),failed_phase=phase)
        traceback.print_exc()
    finally:
        if b:
            result.update(final_step=b.steps,stopped=b.stopped,final_state=b.s.state(),final_object_pose=b.s.object_pose(),
                          final_bilateral_contact=b.s.bilateral_pad_contact())
            if stream:record('TERMINAL_NO_ADDITIONAL_PHYSICS')
            b.close()
        if stream:stream.close()
        result['process_wall_s']=time.monotonic()-started;dump(root/'result.json',result)
        print(json.dumps({k:result.get(k) for k in ('label','z_mm','opening','status','failed_phase','final_step','process_wall_s','real_model_calls','hardware_calls')}),flush=True)
    return 0 if result['status'] in ('CONTROL_COMPLETED','SAFETY_ABORT','GRASP_FAILED') else 2
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--z-mm',type=int,choices=[30,40],required=True);p.add_argument('--opening',type=float,choices=[0,.45],required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--assets',type=Path,required=True)
    raise SystemExit(run(p.parse_args()))
