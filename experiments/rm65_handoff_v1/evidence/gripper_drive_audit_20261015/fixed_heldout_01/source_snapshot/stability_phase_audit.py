"""Read-only audit of the exact archived phase. No threshold or historical score edits."""
import gzip,json,csv,argparse
from pathlib import Path
import numpy as np

D=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=D/'evidence/legacy_centered_hold5_01/physics.jsonl.gz');p.add_argument('--output',type=Path,default=D/'evidence/consistency_20261014/stability');args=p.parse_args();source=args.source;out=args.output;out.mkdir(parents=True,exist_ok=False)
rows=[json.loads(x) for x in (gzip.open(source,'rt') if source.suffix=='.gz' else source.open())];rows=[r for r in rows if r['phase']=='right_independent_hold']
assert len(rows)==1250 and all(r['arms']['left']['actual_pad_gap_m']>.07 for r in rows)
t=np.array([r['sim_time_s'] for r in rows]);p=np.array([r['object_pose'][:3] for r in rows]);v=np.array([r['object_velocity'] for r in rows]);q=np.array([r['object_pose'][3:] for r in rows]);fd=np.diff(p,axis=0)/np.diff(t)[:,None]
def matrices(q):
 q=q/np.linalg.norm(q,axis=1)[:,None];w,x,y,z=q.T
 return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]).transpose(2,0,1)
rot=matrices(q)
tcp=np.array([r['arms']['right']['actual_grasp_center_world'] for r in rows]);fr=np.array([r['arms']['right']['flange_pose_world'][3:] for r in rows]);rrot=matrices(fr);relp=np.einsum('nji,nj->ni',rrot,p-tcp);relrot=rrot.transpose(0,2,1)@rot;dr=relp-relp[0];change=relrot[0].T@relrot;skew=np.array([change[:,2,1]-change[:,1,2],change[:,0,2]-change[:,2,0],change[:,1,0]-change[:,0,1]]).T/2;ang=np.arctan2(np.linalg.norm(skew,axis=1),(np.trace(change,axis1=1,axis2=2)-1)/2)
contacts=[]
for r in rows:
 cs=[c for c in r['contacts'] if 'target_cube' in c['names']];left=any(any(x.startswith('L__') for x in c['names']) for c in cs);table=any('table' in c['names'] for c in cs);depth=max([0]+[-x['separation'] for c in cs for x in c['points'] if any('Support_Link' in n for n in c['names'])]);contacts.append((r['bilateral_contact']['right'],left,table,depth))
def stats(a):return {k:float(x) for k,x in zip(['min','median','mean','p95','max'],[np.min(a),np.median(a),np.mean(a),np.percentile(a,95),np.max(a)])}
summary={'source':str(source.relative_to(D)),'phase':'right_independent_hold','start_step':rows[0]['step'],'end_step':rows[-1]['step'],'samples':len(rows),'duration_recorded_s':len(rows)*.004,'between_first_last_s':float(t[-1]-t[0]),'dt_range_s':[float(np.diff(t).min()),float(np.diff(t).max())],'same_reference_point':'Actor origin in old log; COM offset is checked independently in runtime_info.json. Cube is centered box. No smoothing or records filtered inside this phase. FD uses adjacent post-step positions.','matched_comparison_interval_count':len(fd),'matched_reported_world_speed_m_s':stats(np.linalg.norm(v[1:],axis=1)),'matched_difference_definition':'At row i, (position_i-position_{i-1})/dt is paired with reported velocity_i; full-phase engine statistics and old score also retain the first row.','reported_world_speed_m_s':stats(np.linalg.norm(v,axis=1)),'world_position_difference_speed_m_s':stats(np.linalg.norm(fd,axis=1)),'world_position_range_m':np.ptp(p,axis=0).tolist(),'observed_net_displacement_m':(p[-1]-p[0]).tolist(),'integrated_reported_velocity_over_matching_intervals_m':(v[1:]*np.diff(t)[:,None]).sum(axis=0).tolist(),'relative_position_range_m':np.ptp(relp,axis=0).tolist(),'maximum_relative_position_drift_m':float(np.linalg.norm(dr,axis=1).max()),'maximum_relative_rotation_drift_degrees':float(np.rad2deg(ang).max()),'right_bilateral_fraction':float(np.mean([c[0] for c in contacts])),'left_contact_samples':sum(c[1] for c in contacts),'table_contact_samples':sum(c[2] for c in contacts),'maximum_pad_penetration_m':max(c[3] for c in contacts),'original_speed_criterion_m_s':.03,'original_speed_criterion_all_samples_pass':bool(np.all(np.linalg.norm(v,axis=1)<.03)),'old_score_unchanged':True,'conclusion':'Reported velocity fails the old criterion but does not demonstrate sustained sliding: pose differences and relative grip pose show retention. Solver velocity and integrated transform motion are distinct quantities. No new PASS replaces the historical score.'}
(out/'summary.json').write_text(json.dumps(summary,indent=2))
with (out/'exact_phase.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['step','time_s','engine_speed_m_s','adjacent_fd_speed_m_s','relative_drift_m','relative_rotation_degrees','right_bilateral','left_contact','table_contact','pad_penetration_m'])
 for i,r in enumerate(rows):w.writerow([r['step'],t[i],np.linalg.norm(v[i]),'' if i==0 else np.linalg.norm(fd[i-1]),np.linalg.norm(dr[i]),np.rad2deg(ang[i]),*contacts[i]])
# Standalone SVG, exact statistics above; plot points decimated only for display.
from html import escape
curves=[(np.linalg.norm(v,axis=1)*1000,'PhysX speed (mm/s)',35),(np.r_[0,np.linalg.norm(fd,axis=1)]*1000,'Adjacent pose difference speed (mm/s)',.16),(np.linalg.norm(dr,axis=1)*1e6,'Relative position drift (micrometres)',1.)]
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="680" viewBox="0 0 1000 680">','<rect width="1000" height="680" fill="white"/>','<text x="60" y="25" font-family="sans-serif" font-size="18">Exact right_independent_hold phase — separate velocity scales</text>']
for panel,(values,label,ymax) in enumerate(curves):
 top=50+panel*200;bottom=top+140
 svg+=['<path d="M60 %s V%s H970" stroke="black" fill="none"/>'%(top,bottom),'<text x="60" y="%s" font-family="sans-serif" font-size="14">%s; y range 0–%s</text>'%(top-10,escape(label),ymax)]
 indices=list(range(0,len(t),5))+[len(t)-1];points=' '.join('%.2f,%.2f'%(60+910*(t[i]-t[0])/(t[-1]-t[0]),bottom-140*values[i]/ymax) for i in indices);svg.append('<polyline points="%s" fill="none" stroke="#176ca5" stroke-width="1.5"/>'%points)
 if panel==0:svg.append('<path d="M60 %s H970" stroke="red" stroke-dasharray="5 5"/>'%(bottom-140*30/ymax))
 svg.append('<text x="60" y="%s" font-family="sans-serif" font-size="12">%.3f s</text>'%(bottom+20,t[0]));svg.append('<text x="890" y="%s" font-family="sans-serif" font-size="12">%.3f s</text>'%(bottom+20,t[-1]))
svg.append('</svg>');(out/'phase_audit.svg').write_text(''.join(svg));print(json.dumps(summary,indent=2))
