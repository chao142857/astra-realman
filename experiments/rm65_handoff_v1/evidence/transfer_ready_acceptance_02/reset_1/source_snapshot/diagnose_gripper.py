"""Private post-hoc comparison. Does not import the simulator or feed the model."""
import json,gzip,csv,math
from pathlib import Path
D=Path(__file__).parent
runs={'original_b13164b':D.parent/'rm65_handoff_v0/evidence/final_baseline_01','centered_original':D/'evidence/legacy_centered_hold5_01','centered_damped':D/'evidence/legacy_centered_damped_hold5_01','centered_light':D/'evidence/legacy_centered_light_hold5_01','centered_refined':D/'evidence/legacy_centered_refined_hold5_01','down_original':D/'evidence/right_down_02','rotated_original':D/'evidence/right_rotate_01','rotated_damped':D/'evidence/right_rotate_damped_01'}
out=D/'evidence/gripper_diagnostic_report';out.mkdir(exist_ok=True);summary={}
for name,folder in runs.items():
 p=folder/'physics.jsonl'
 if p.exists():f=p.open()
 elif p.with_suffix('.jsonl.gz').exists():f=gzip.open(p.with_suffix('.jsonl.gz'),'rt')
 else:continue
 rows=[json.loads(x) for x in f];f.close();points=[]
 for r in rows:
  a=r['arms']['right'];contacts=[c for c in r['contacts'] if 'target_cube' in c['names'] and any(n.startswith('R__') for n in c['names'])]
  penetration=max([0.]+[-p['separation'] for c in contacts for p in c['points']])
  points.append({'time_s':r['sim_time_s'],'phase':r['phase'],'cube_z_m':r['object_pose'][2],'reported_speed_m_s':math.sqrt(sum(v*v for v in r['object_velocity'])),'right_gap_m':a['actual_pad_gap_m'],'left_gap_m':r['arms']['left']['actual_pad_gap_m'],'right_bilateral':r['bilateral_contact']['right'],'max_right_penetration_mm':penetration*1000})
 with (out/(name+'.csv')).open('w') as f:
  writer=csv.DictWriter(f,fieldnames=list(points[0]));writer.writeheader();writer.writerows(points)
 tail=points[-1250:];xyz=[r['object_pose'][:3] for r in rows[-1250:]]
 summary[name]={'source':str(folder.relative_to(D.parent)),'last_step':rows[-1]['step'],'max_right_penetration_mm':max(r['max_right_penetration_mm'] for r in points),'last_5s_right_bilateral_fraction':sum(r['right_bilateral'] for r in tail)/len(tail),'last_5s_position_range_m':[max(p[i] for p in xyz)-min(p[i] for p in xyz) for i in range(3)],'last_5s_max_reported_speed_m_s':max(r['reported_speed_m_s'] for r in tail),'interpretation':'descriptive only; tail may span different phases; original and V1 scores remain separate'}
 try:
  import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
  fig,axes=plt.subplots(3,1,figsize=(10,7),sharex=True)
  for ax,key in zip(axes,['right_gap_m','max_right_penetration_mm','reported_speed_m_s']):ax.plot([p['time_s'] for p in points],[p[key] for p in points]);ax.set_ylabel(key);ax.grid(alpha=.2)
  axes[1].axhline(2,color='red',linestyle='--');axes[2].axhline(.03,color='red',linestyle='--');axes[-1].set_xlabel('simulation time (s)');fig.suptitle(name);fig.tight_layout();fig.savefig(out/(name+'.png'));plt.close(fig)
 except ImportError:pass
(out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
