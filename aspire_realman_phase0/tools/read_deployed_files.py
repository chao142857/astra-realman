"""Explicit small-file reads only. Emit to local cache; do not execute modules."""
import hashlib,json,pathlib
P=pathlib.Path
H=P('/home/tongji/alex/realman-chunk-gui-migration-20261017/astra_realman_harness')
O=P('/home/tongji/alex/astra_onsite_1011/astra_realman_harness')
files=[H/x for x in ['arm_stack.py','arm_worker.py','left_executor.py','realman_api2_readonly.py','realman_state.py','lab_cameras.py','camera_hub.py','onsite_sequence.py','lab_gripper_adapter.py','real_hardware_gui.py','real_calibration_status.py','scripts/capture_onsite_rgbd.py','scripts/record_onsite_sequence.py','config/lab.json','config/engineering/right_wrist_calibration_20261017.json','config/engineering/onsite_board_dfvision_image_verified_20261011.json','docs/RIGHT_WRIST_CALIBRATION_20261017.md','reports/v17_v19_audit_20261018/audit_facts.json']]
files += [O/x for x in ['config/engineering/three_camera_calibration_20261011.json','config/engineering/three_camera_mount_confirmation_20261011.json','logs/calibration_handoff_1011.json','logs/controller_geometry_readback_20261011.json','logs/wrist_handeye_candidate_20261011.json','logs/overhead_extrinsic_validation_20261011.json','docs/engineering/CALIBRATION_HANDOFF_1011.md','docs/engineering/THREE_CAMERA_CALIBRATION_20261011.md']]
files += [P('/home/tongji/aloha/RealMan_Control/Robotic_Arm')/x for x in ['rm_robot_interface.py','rm_ctypes_wrap.py','libs/linux_x86/libapi_c.so']]
for run in ['parallel-arms-20261018T142729-853ffbe2','parallel-arms-20261018T145818-fd3d3371','parallel-arms-20261018T153025-8a4d5e3b']:
 r=H/'logs'/run
 files += [p for p in r.iterdir() if p.is_file() and p.suffix=='.json']
 # One unmodified, recorded observation per run (the selected path is AFTER), never execute the proposal.
 for name in ['observation.json','before.json','state.json','model_input.json','result.json','action_result.json']:
  candidates=sorted(r.glob('step-001/**/'+name))
  files+=candidates[:1]
result={}
for p in dict.fromkeys(files):
 try:
  b=p.read_bytes(); d={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
  if p.suffix in ['.py','.json','.md'] and len(b)<700000:d['text']=b.decode()
  else:d['content_omitted']=True
  result[str(p)]=d
 except OSError as e:result[str(p)]={'error':str(e)}
print(json.dumps(result,ensure_ascii=False))
