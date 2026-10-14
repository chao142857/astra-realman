"""Real RM65 PhysX smoke and physical script; no model or hardware interface."""
import argparse,sys,os,json,time,traceback,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'astra_realman_harness'))
from sim_skills.rm65 import RM65Backend
result={'status':'RUNNING','source':'SAPIEN_PHYSX','model_calls':0,'hardware_connections':0,'started':time.time()};b=None
try:
 b=RM65Backend(os.environ['RM65_ASSETS'],a.output,seed=2,video=True)
 obs=b.observe();result['initial_state']=obs['state'];result['images']=obs['images']
 result['setup_hold']=b.setup_held();b.observe()
 xy=b.s.cfg['scene']['place_zone_xy']
 for z in [.12,.06]:
  move=b.s.move_tcp([*xy,z,0,1,0,0])
  if not move['ok']:raise RuntimeError('SCRIPT_MOVE_FAILED:'+str(move))
 b.s.gripper(1.);b.s.set_planning_payload(False);b.s.tick(300);result['evaluation']=b.evaluate();result['final_observation']=b.observe();result['status']=result['evaluation']['status']
except BaseException as e:result.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());traceback.print_exc()
finally:
 if b:b.close()
 a.output.mkdir(parents=True,exist_ok=True);result['ended']=time.time();(a.output/'smoke_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
