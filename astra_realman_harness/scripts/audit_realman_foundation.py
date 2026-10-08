#!/usr/bin/env python3
"""Static preparation inventory only. Never import SDK/drivers or open devices."""
import argparse,ast,hashlib,json
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
FILES=['realman_api2_readonly.py','realman_state.py','lab_gripper_adapter.py','left_executor.py',
       'left_terminal.py','arm_stack.py','exact_target_feasibility.py','docs/api2_frame_evidence.json',
       'sim_skills/full_pnp/backend.py','sim_skills/full_pnp/grasp_control.py','sim_skills/full_pnp/protocol.py']

def audit(base=BASE):
    base=Path(base);paths={};hashes={}
    for name in FILES:
        path=base/name;data=path.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
        if path.suffix=='.py':
            for node in ast.walk(ast.parse(data)):
                if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.startswith('/home/tongji/'):
                    paths[node.value]=Path(node.value).exists()
    return {'scope':'STATIC_SOURCE_PREPARATION_NOT_HARDWARE_ACCEPTANCE','hardware_calls':0,'model_calls':0,
        'sdk_imports':0,'device_connections':0,'source_hashes':hashes,'external_paths_exist':paths,
        'hardware_ready':False,'physical_calibration':'NOT_VERIFIED',
        'differences':[
            {'topic':'motion','simulation':'absolute world pad-center xyz + flange wxyz, dynamic gripper offset',
             'real':'current controller pose plus xyz/RPY deltas; rm_movej_p(...,speed=1,r=0,connect=0,block=1)',
             'gap':'No verified common frame/TCP/orientation conversion; direct reuse of simulated pose is not permitted.'},
            {'topic':'units','simulation':'metres, radians, quaternion wxyz',
             'real':'API2 joints degrees, pose m/rad; raw JSON uses separate integer scales',
             'gap':'Do not apply raw JSON divisors to SDK floats or treat RPY addition as quaternion composition.'},
            {'topic':'gripper','simulation':'opening maps to joint target; observed contacts + finite latch; grasp qualification is private simulation assistance',
             'real':'hand_follow_pos / 0..1000 position; RM-plus raw pos/speed/current/sys_state/dof_err',
             'gap':'ACK, position or current does not prove bilateral contact/holding; no validated current-to-force or gap conversion.'},
            {'topic':'STOP','simulation':'owner checks each physics step; original monitor precedes contact-loss guard',
             'real':'software flag before dispatch/between channels and interruptible settling; arm call is blocking',
             'gap':'No verified in-flight controller stop path in this executor; software STOP is not an emergency stop.'},
            {'topic':'faults','simulation':'original safety abort preserved; contact failure ends action without retry',
             'real':'raw SDK return/errors logged; no automatic retry; failure readback attempted',
             'gap':'SDK timeout, disconnect and actual stop/ack timing require onsite verification.'}],
        'onsite_checks':[
            'Pin actual SDK/.so/driver/config paths and hashes; verify controller/model/firmware identity.',
            'Confirm returned end-pose frame, work/tool definitions, grasp TCP and installed gripper identity.',
            'Read raw arm and gripper state with timestamps; verify units, freshness and malformed/error handling.',
            'Verify independent emergency-stop chain and documented in-flight SDK stop behavior before any motion acceptance.',
            'Validate actual gripper travel, opening-to-gap mapping and contact/holding evidence; do not infer force from raw current.',
            'Verify timeout/disconnect/partial-send behavior and command-to-feedback lifecycle with no automatic resend.',
            'Only after separate authorization, validate bounded low-speed motion/grasp; hardware execution remains NOT_VERIFIED.'],
        'excluded':'mechanical base installation, stiffness modification, onsite recalibration, hardware/model calls, B/F experiments'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:json.dump(audit(),f,indent=2,ensure_ascii=False)
    print(json.dumps({'output':str(a.output),'hardware_ready':False,'hardware_calls':0,'sdk_imports':0}))
if __name__=='__main__':main()
