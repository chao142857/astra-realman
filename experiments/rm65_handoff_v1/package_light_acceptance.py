"""Prepare small review artifacts; raw records never leave this host."""
from pathlib import Path
import hashlib,json,subprocess
import imageio_ffmpeg
ROOT=Path(__file__).resolve().parent
E=ROOT/'evidence/interface_repair_yanglab_20261017'
P=E/'PUBLIC_LIGHT';P.mkdir(exist_ok=True)

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

r=json.loads((E/'independent_acceptance.json').read_text())
assert all(x['status']!='PENDING' for x in r['cases'].values())
assert all(x['unchanged'] for x in r['historical_tracked_ledgers'])
video_checks={};manifest={}
for name,c in r['cases'].items():
 folder=E/name;v=folder/'execution.mp4'
 proc=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(v),'-f','null','-'],capture_output=True,text=True,timeout=90)
 video_checks[name]={'decode_returncode':proc.returncode,'stderr':proc.stderr,'sha256':sha(v),'bytes':v.stat().st_size}
 assert proc.returncode==0,video_checks[name]
 for p in sorted(folder.iterdir()):
  if p.is_file() and (p.suffix in ('.json','.jsonl','.mp4') or p.name=='physics.jsonl'):
   manifest[str(p)]={'bytes':p.stat().st_size,'sha256':sha(p)}
 for p in folder.glob('group_*/contact_guard_summary_PRIVATE.json'):
  manifest[str(p)]={'bytes':p.stat().st_size,'sha256':sha(p)}
 # Keep the full private report and all trajectories locally; public only their manifest/summary.
(P/'independent_acceptance.json').write_text(json.dumps(r,indent=2)+'\n')
(P/'recordings_manifest.json').write_text(json.dumps({'host':'yanglab','raw_uploaded':False,'files':manifest,'video_decode':video_checks},indent=2)+'\n')
(P/'unit_tests.log').write_bytes((E/'unit_tests.log').read_bytes())
servo={}
for name in ('contact_d1_readback_02','contact_d1_left_v4_01','contact_d1_slow2_01'):
 folder=E/name;events=[json.loads(l) for l in (folder/'left/events.jsonl').read_text().splitlines()]
 latch=next(x['step'] for x in events if x['event']=='bilateral_contact_latch')
 data=[json.loads(l) for l in (folder/'contact_servo_readback_PRIVATE.jsonl').read_text().splitlines()]
 picked=[]
 for x in data:
  if x['step'] in (latch-2,latch-1,latch,latch+1,latch+5,latch+10,data[-1]['step']):
   b=x['before']['left'];a=x['after']['left'];i=b['master_index']
   picked.append({'step':x['step'],'measured_q_before':b['qpos'][i],'target':b['position_target'],
    'fd_q_velocity':(a['qpos'][i]-b['qpos'][i])/x['dt'],'engine_qvel_before':b['engine_qvel'][i],
    'engine_qvel_after':a['engine_qvel'][i],'K':b['stiffness'],'D':b['damping'],'limit_Nm':b['force_limit'],
    'measured_native_drive_torque':None})
 servo[name]={'latch_step':latch,'selected_unfiltered_rows':picked}
(P/'servo_readback_summary.json').write_text(json.dumps({'selection':'latch offsets -2,-1,0,1,5,10 and last row; raw remains complete','native_force_unknown':True,'data':servo},indent=2)+'\n')
print(json.dumps({'public_light_files':{p.name:p.stat().st_size for p in P.iterdir()},'video_decode_all_pass':True},indent=2))
