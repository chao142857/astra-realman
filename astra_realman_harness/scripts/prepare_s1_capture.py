"""S1 capture-only preparation. Default never imports SAPIEN or a model client.

Running needs a separately approved, protocol-bound authorization file. This
file is an audit record of user authorization, not a way to grant permission.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/s1_shadow'

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):
    with Path(p).open('x') as f:json.dump(value,f,indent=2,allow_nan=False)

def validate_approval(approval):
    expected=read(DOC/'CAPTURE_AUTHORIZATION_TEMPLATE.json');expected['granted']=True
    if approval!=expected or approval['protocol_sha256']!=sha(DOC/'CAPTURE_PROTOCOL.json'):
        raise ValueError('SEPARATE_EXPLICIT_S1_CAPTURE_AUTHORIZATION_REQUIRED')

def verify_sources(assets):
    for name,expected in read(DOC/'CAPTURE_SOURCE_PINS.json').items():
        if sha(ROOT/name)!=expected:raise ValueError('CAPTURE_SOURCE_CHANGED:'+name)
    if sha(Path(assets)/'asset_manifest.json')!=read(DOC/'CAPTURE_PROTOCOL.json')['assets_manifest_sha256']:
        raise ValueError('FROZEN_ASSETS_REQUIRED')

def manifest():
    return {'status':'PREPARED_NOT_AUTHORIZED_NOT_CAPTURED','protocol_sha256':sha(DOC/'CAPTURE_PROTOCOL.json'),
        'script_sha256':sha(__file__),'budget':read(DOC/'CAPTURE_PROTOCOL.json')['budget'],
        'pixel_coverage':'UNKNOWN_UNTIL_AUTHORIZED_CAPTURE','Astra_calls':0,'new_SAPIEN_episodes':0,
        'hardware':0,'training':0,'default_mode':'read-only preparation'}

def worker(output,assets):
    # Only launcher reaches this branch after exclusive claim and authorization.
    claim=read(output/'EPISODE_CLAIM.json');validate_approval(read(output/'AUTHORIZATION.json'))
    if claim['script_sha256']!=sha(__file__) or claim['protocol_sha256']!=sha(DOC/'CAPTURE_PROTOCOL.json'):
        raise ValueError('CLAIM_BINDING')
    verify_sources(assets)
    start=time.monotonic();owner=None;protocol=read(DOC/'CAPTURE_PROTOCOL.json')
    result={'status':'INCOMPLETE','new_episode_attempts':1,'owner_submissions':0,'public_bundles':0,
        'Astra':0,'DA3':0,'SAM':0,'hardware':0,'training':0,'automatic_retries':0}
    def interrupt(*_):raise TimeoutError('CAPTURE_TOTAL_DEADLINE')
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGALRM,interrupt);signal.setitimer(signal.ITIMER_REAL,110)
    try:
        sys.path.insert(0,str(ROOT))
        from platform_v1.owner import Owner
        from platform_v1.research.rgbd_sensor import RGBDObservationBackend
        import sapien
        owner=Owner(assets,output,seed=protocol['seed'],budget_s=90,source='S1_CAPTURE_ONLY',
            infer_config=None,max_requests=0,backend_factory=RGBDObservationBackend)
        result.update(initialization_wall_s=owner.init_wall,initialization_final_step=owner.initial_step,
            initialization_internal_capture='original backend public_start remains private; not S1 input')
        scene=owner.b.s;instances=[]
        for spec in protocol['scene']['additional_instances']:
            builder=scene.scene.create_actor_builder();half=[spec['side_m']/2]*3
            builder.add_box_collision(half_size=half,material=scene.material)
            builder.add_box_visual(half_size=half,material=spec['render_rgb'])
            actor=builder.build(name='s1_'+spec['setup_name'])
            body=actor.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
            body.mass=scene.cfg['scene']['cube_mass_kg']
            actor.set_pose(sapien.Pose(spec['initial_center_world_m']))
            instances.append(actor)
        # Owner.idle preserves original pacing, STOP and monitor hooks. No execute.
        for _ in range(protocol['budget']['max_settle_steps']):owner.idle()
        observation=owner.observe();result['public_bundles']=1
        write(output/'OBSERVATION.json',observation)
        files={str(p.relative_to(output/'public')):sha(p) for p in (output/'public').rglob('*') if p.is_file()}
        write(output/'PUBLIC_SEAL.json',{'observation_sha256':sha(output/'OBSERVATION.json'),'public_files':files})
        # Private independent scoring only, generated after sealing the public input.
        actors=[scene.cube,*instances]
        write(output/'private/SCORING_TRUTH.json',{'source':'PRIVATE_SIMULATOR_TRUTH_NOT_MODEL_INPUT',
            'objects':[{'setup_name':a.name,'pose_world_xyz_wxyz':[*map(float,a.get_pose().p),*map(float,a.get_pose().q)],
                        'side_m':scene.cfg['scene']['cube_size_m']} for a in actors]})
        result.update(status='CAPTURED_PENDING_RGB_COVERAGE_REVIEW',final_step=owner.b.steps,
            settle_steps=owner.b.steps-owner.initial_step,owner_submissions=owner.chunks,
            observation_id=observation['observation_id'],episode_id=owner.id,
            planner_registered_for_new_actors=False,physical_motion_authorized=False)
        if owner.chunks!=0 or len(owner.observations)!=1:raise RuntimeError('CAPTURE_BUDGET_VIOLATION')
    except BaseException as exc:
        result.update(status='FAIL_STOP',error=repr(exc))
        if owner:
            try:owner.stop()
            except Exception:pass
    finally:
        if owner:owner.close()
        signal.setitimer(signal.ITIMER_REAL,0)
        result['worker_wall_s']=time.monotonic()-start;write(output/'RESULT.json',result)
    return 0 if result['status']=='CAPTURED_PENDING_RGB_COVERAGE_REVIEW' else 2

def launch(output,assets,approval):
    validate_approval(approval)
    if not Path(assets,'asset_manifest.json').is_file():raise ValueError('ASSETS_REQUIRED')
    verify_sources(assets)
    output.mkdir(exist_ok=False);start=time.monotonic()
    write(output/'AUTHORIZATION.json',approval)
    write(output/'EPISODE_CLAIM.json',{'scope':'S1_CAPTURE_ONLY','script_sha256':sha(__file__),
        'protocol_sha256':sha(DOC/'CAPTURE_PROTOCOL.json'),'claimed_monotonic':start,'retry':False})
    env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    watchdog=False
    with (output/'PROCESS.log').open('x') as log:
        child=subprocess.Popen([sys.executable,'-B',__file__,'--worker','--output',str(output),'--assets',str(assets)],
            stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:child.wait(timeout=max(.1,115-(time.monotonic()-start)))
        except subprocess.TimeoutExpired:
            watchdog=True;os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=max(.1,118-(time.monotonic()-start)))
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
    write(output/'PROCESS.json',{'returncode':child.returncode,'process_wall_s':time.monotonic()-start,
        'watchdog':watchdog,'retries':0})
    return child.returncode

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-authorized',action='store_true')
    parser.add_argument('--approval',type=Path);parser.add_argument('--assets',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);args=parser.parse_args()
    if args.worker:return worker(args.output.resolve(),args.assets.resolve())
    if not args.run_authorized:print(json.dumps(manifest(),indent=2));return 0
    if not all((args.approval,args.assets,args.output)):parser.error('approval/assets/output required')
    return launch(args.output.resolve(),args.assets.resolve(),read(args.approval))
if __name__=='__main__':raise SystemExit(main())
