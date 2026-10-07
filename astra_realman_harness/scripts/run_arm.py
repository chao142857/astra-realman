#!/usr/bin/env python3
"""Existing RealMan stack, arm-selectable. Read or preflight by default; --execute sends one action."""
import argparse,json,signal,sys,threading,time,uuid
from contextlib import ExitStack
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT,new_run,write_json,read_json
from arm_stack import ArmStack,ENDPOINTS,capture_states,model_input

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arm',choices=['left','right'],default='right')
    p.add_argument('--both',action='store_true',help='Read both arms; only --arm can be commanded.')
    p.add_argument('--execute',action='store_true',help='Explicitly send exactly one action; no retry.')
    p.add_argument('--cameras',type=Path,help='Existing camera config JSON, optional; uses unchanged CameraSession.')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('read')
    delta=sub.add_parser('delta');delta.add_argument('--xyz',type=float,nargs=3,required=True);delta.add_argument('--rpy',type=float,nargs=3,default=[0,0,0])
    pose=sub.add_parser('pose');pose.add_argument('--target',type=float,nargs=6,required=True)
    grip=sub.add_parser('gripper');grip.add_argument('--opening',type=float,required=True)
    act=sub.add_parser('action');act.add_argument('--json',type=Path,required=True)
    args=p.parse_args()
    if args.command=='read' and args.execute:p.error('read cannot execute')
    # Reject malformed numerical input before opening a connection.
    from io_utils import vector,number
    if args.command=='delta' and not (vector(args.xyz,3) and vector(args.rpy,3)):p.error('finite XYZ/RPY required')
    if args.command=='pose' and not vector(args.target,6):p.error('finite pose required')
    if args.command=='gripper' and not (number(args.opening) and 0<=args.opening<=1):p.error('opening must be 0..1')
    raw=read_json(args.json) if args.command=='action' else None
    if raw is not None and raw.get('arm')!=args.arm:p.error('action arm must match --arm')
    stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set());signal.signal(signal.SIGTERM,lambda *_:stop.set())
    run=new_run(ROOT/'logs'/('arm-'+args.arm+'-'+time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]))
    with ExitStack() as stack:
        from realman_api2_readonly import SDKReadOnly
        session=stack.enter_context(SDKReadOnly(new_run(run/'sdk')))
        for arm in (('left','right') if args.both else (args.arm,)):
            if not session.connect(arm,*ENDPOINTS[arm])['connected']:raise RuntimeError(arm+':CONNECTION_FAILED')
        streams=None
        if args.cameras:
            from camera_session import CameraSession
            cameras=json.loads(args.cameras.read_text())['cameras']
            streams=stack.enter_context(CameraSession(cameras))
        def capture(path):return capture_states(session,path,streams=streams)
        executor=ArmStack(args.arm,session,capture,stop,run/'operations',execute_enabled=args.execute)
        obs=capture(run/'initial');s=obs['canonical_states'][args.arm]
        write_json(run/'model_input.json',model_input(obs))
        op=uuid.uuid4().hex
        if args.command=='read':result={'status':'READ_ONLY','states':obs['canonical_states'],'hardware_commands_sent':0}
        elif args.command=='delta':result=executor.move_delta(args.xyz,args.rpy,s['work_frame']['id'],op)
        elif args.command=='pose':result=executor.move_to_pose(args.target,s['work_frame']['id'],s['tool_frame']['id'],op)
        elif args.command=='gripper':result=executor.set_gripper(args.opening,op)
        else:result=executor.run(raw,op)
        write_json(run/'summary.json',result)
        print(json.dumps({'run':str(run),'mode':'EXECUTE' if args.execute else 'READ_OR_PREFLIGHT_ONLY','result':result},ensure_ascii=False))
if __name__=='__main__':main()
