"""Private post-hoc physical metrics. Never imported by public context builder."""
import argparse,json,math
from pathlib import Path
CRITERIA=json.loads((Path(__file__).parent/'process_criteria_v1.json').read_text())
def evaluate(folder):
 p=Path(folder);rows=[json.loads(x) for x in (p/'physics.jsonl').read_text().splitlines()];dt=json.loads((p/'configuration.json').read_text())['dt'];longest={k:0 for k in ['left_hold','right_independent_hold','stable_place']};current=dict(longest);interarm=[];penetrations=[];drops=[];lifted=False;released=False;max_penetration=0.
 for r in rows:
  xyz=r['object_pose'][:3];speed=math.sqrt(sum(v*v for v in r['object_velocity']));names=[c['names'] for c in r['contacts'] if 'target_cube' in c['names']];left_contact=any(any(n.startswith('L__') for n in ns) for ns in names);table=any('table' in ns for ns in names)
  # OBB footprint from quaternion; no unique reference object orientation.
  from scipy.spatial.transform import Rotation
  q=r['object_pose'][3:];rot=Rotation.from_quat([q[1],q[2],q[3],q[0]]).as_matrix();extent=abs(rot)@([.025]*3)
  released=released or r['phase']=='right_release'
  lifted=lifted or (r['bilateral_contact']['left'] and xyz[2]>.07)
  if lifted and not released and (table or xyz[2]<.06):drops.append(r['step'])
  tests={'left_hold':r['bilateral_contact']['left'] and xyz[2]>.07 and speed<.03,'right_independent_hold':r['bilateral_contact']['right'] and not left_contact and r['arms']['left']['actual_pad_gap_m']>.07 and not table and xyz[2]>.07 and speed<.03,'stable_place':table and r['arms']['right']['actual_pad_gap_m']>.07 and not left_contact and not r['bilateral_contact']['right'] and speed<.01 and all(abs(xyz[i]-CRITERIA['target_xy'][i])+extent[i]<=.07 for i in range(2))}
  for k,v in tests.items():current[k]=current[k]+dt if v else 0;longest[k]=max(longest[k],current[k])
  for c in r['contacts']:
   if 'target_cube' in c['names'] and any('Support_Link' in n for n in c['names']):max_penetration=max(max_penetration,-min(x['separation'] for x in c['points']))
   if any(n.startswith('L__') for n in c['names']) and any(n.startswith('R__') for n in c['names']):interarm.append(r['step'])
   if 'target_cube' in c['names'] and any('Support_Link' in n for n in c['names']) and min(x['separation'] for x in c['points'])<-.002:penetrations.append({'step':r['step'],'pair':c['names'],'min_separation':min(x['separation'] for x in c['points'])})
 verdict={'left_hold':longest['left_hold']>=.5,'right_independent_hold':longest['right_independent_hold']>=CRITERIA['right_continuous_independent_hold_s'],'stable_place':longest['stable_place']>=1.,'no_unintended_drop':not drops,'no_interarm_contact':not interarm,'no_pad_penetration_abort':not penetrations}
 return {'criteria':CRITERIA,'longest_continuous_s':longest,'checks':verdict,'full_process_pass':all(verdict.values()),'unintended_drop_steps':drops,'maximum_pad_penetration_m':max_penetration,'interarm_steps':interarm,'pad_penetrations':penetrations,'physics_steps':len(rows),'model_calls':0}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder',type=Path);a=p.parse_args();r=evaluate(a.folder);(a.folder/'process_evaluation_v1.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
