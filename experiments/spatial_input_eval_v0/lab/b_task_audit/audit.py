"""Private offline task audit. Reuses frozen scorer/SAT; never writes B or dispatches."""
import argparse,copy,hashlib,itertools,json,math,re,time
from pathlib import Path
from spatial_eval.geometry import contains,swept_collision,validate_geometry
from spatial_eval.schema import parse_prediction
from pilot02_contract import score
from replay_pilot01 import sat_threshold
SCENES=('p02_b_open_minus','p02_b_open_plus','p02_c_slot_030','p02_c_slot_120')
SCAN={'yaw_global':{'xy_step_m':.02,'z_step_m':.04,'yaw_step_deg':10,'yaw_range_deg':[0,180],'position_range':'entire publicly declared task-volume bounds (including endpoints)'},'yaw_local':{'xy_offsets_m':[-.012,.012],'xy_step_m':.002,'z':'public task-volume center only','yaw_range_deg':[0,180],'yaw_step_deg':2},'detour':{'lateral_waypoint_y_range_m':[-.24,.24],'y_step_m':.01,'lateral_waypoint_z_range_m':[.06,.22],'z_step_m':.02,'path_family':'start -> same start x at (y,z) -> same placement x at (y,z) -> public region center; fixed quaternion'},'boundary_contacts':'original SAT treats touch as collision; thresholds are brackets, not exact Euclidean distance','generation_budget':0}
def read(p):return json.loads(Path(p).read_text())
def write(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def public_regions(context):
 pattern=r'(\w+): center=(\[[^\]]+\]) m, full_size=(\[[^\]]+\]) m, wxyz=(\[[^\]]+\])'
 boxes=[{'id':name,'center_m':json.loads(center),'size_m':json.loads(size),'quaternion_wxyz':json.loads(q)} for name,center,size,q in re.findall(pattern,context['task']['instruction'])]
 required=[context['task']['constraints']['allowed_region_id']]
 if context['task']['kind']=='path':required.append(context['task']['constraints']['workspace_region_id'])
 assert set(required)=={b['id'] for b in boxes},'PUBLIC_REGION_PARSE_FAILED'
 return boxes

def b_environment(context,geometry):
 """Only public context and frozen B geometry accepted; no snapshot/private parameter."""
 assert context['geometry'] is None
 g=copy.deepcopy(geometry);g['regions']=public_regions(context);validate_geometry(g)
 return {'ground_truth':g}

def environments(context,b,truth):
 baseline={'ground_truth':copy.deepcopy(truth)}
 assert baseline['ground_truth']['regions']==public_regions(context),'GT_PUBLIC_REGION_MISMATCH'
 full=b_environment(context,b)
 target=copy.deepcopy(baseline);target['ground_truth']['objects']=copy.deepcopy(b['objects'])
 obstacle=copy.deepcopy(full);obstacle['ground_truth']['objects']=copy.deepcopy(truth['objects'])
 return {'GT':baseline,'B_target_only':target,'B_obstacles_only':obstacle,'B_full':full}

def result(env,context,prediction,clearance=None):
 task=copy.deepcopy(context['task'])
 if clearance is not None:task['constraints']['clearance_m']=clearance
 return score(env,task,prediction,context['task_policy'])

def margins(env,context,prediction):
 g=env['ground_truth'];held=copy.deepcopy(next(x for x in g['objects'] if x['id']==prediction['object_id']));held.update(center_m=prediction['position_m'],quaternion_wxyz=prediction['quaternion_wxyz'])
 obstacles=g['obstacles']+[x for x in g['objects'] if x['id']!=held['id']]
 placement=[prediction['position_m']];path=[context['task']['constraints']['start_position_m'],*prediction['waypoints_m']] if context['task']['kind']=='path' else placement
 out={}
 for label,points in [('placement',placement),('continuous_path',path)]:
  rows=[dict(obstacle_id=o['id'],**sat_threshold(held,points,o)) for o in obstacles]
  zero=any(x['collision_at_zero'] for x in rows)
  out[label]={'collision_at_zero':zero,'noncollision_lower_m':None if zero else min(x['noncollision_lower_m'] for x in rows),'collision_upper_m':min(x['collision_upper_m'] for x in rows),'per_obstacle':rows}
 return out

def confusion(rows):
 counts={k:0 for k in ('both_feasible','GT_only','B_only','neither')}
 for gt,b in rows:counts['both_feasible' if gt and b else 'GT_only' if gt else 'B_only' if b else 'neither']+=1
 pos=counts['both_feasible']+counts['GT_only'];neg=counts['B_only']+counts['neither']
 return dict(counts,samples=len(rows),GT_feasible=pos,GT_infeasible=neg,retention_given_GT_feasible=counts['both_feasible']/pos if pos else None,false_rejection_given_GT_feasible=counts['GT_only']/pos if pos else None,false_acceptance_given_GT_infeasible=counts['B_only']/neg if neg else None,agreement=(counts['both_feasible']+counts['neither'])/len(rows) if rows else None)

def prediction(position,yaw):return {'object_id':'target','position_m':[float(x) for x in position],'quaternion_wxyz':[math.cos(math.radians(yaw)/2),0,0,math.sin(math.radians(yaw)/2)],'waypoints_m':[]}
def scan_candidates(context,mode):
 region=public_regions(context)[0];center=region['center_m'];size=region['size_m']
 if mode=='yaw_global':
  # Uniform integer-index steps, endpoints selected explicitly; no adaptive GT tuning.
  coords=[[center[i]-size[i]/2+j*([.02,.02,.04][i]) for j in range(round(size[i]/[.02,.02,.04][i])+1)] for i in range(3)]
  for x,y,z,angle in itertools.product(*coords,range(0,180,10)):yield prediction([x,y,z],angle)
 elif mode=='yaw_local':
  for ix,iy,angle in itertools.product(range(-6,7),range(-6,7),range(0,180,2)):yield prediction([center[0]+ix*.002,center[1]+iy*.002,center[2]],angle)
 else:
  start=context['task']['constraints']['start_position_m']
  for yi,zi in itertools.product(range(-24,25),range(3,12)):
   y=yi*.01;z=zi*.02;p=prediction(center,0);p['waypoints_m']=[[start[0],y,z],[center[0],y,z],list(center)];yield p

def scan(context,envs,mode,out):
 counts=[];path_counts=[];examples={};valid_positions=[];per_yaw={};t=time.perf_counter()
 with (out/f'{mode}_samples.jsonl').open('w') as f:
  for index,pred in enumerate(scan_candidates(context,mode)):
   gt=result(envs['GT'],context,pred);b=result(envs['B_full'],context,pred);ok=(gt['success'],b['success']);counts.append(ok)
   key='both_feasible' if all(ok) else 'GT_only' if ok[0] else 'B_only' if ok[1] else 'neither'
   if key not in examples:examples[key]=pred
   if any(ok):valid_positions.append({'prediction':pred,'GT':ok[0],'B':ok[1]})
   if mode=='detour':path_counts.append((gt['constraints']['continuous_path_collision_free'],b['constraints']['continuous_path_collision_free']))
   else:
    angle=round(math.degrees(2*math.atan2(pred['quaternion_wxyz'][3],pred['quaternion_wxyz'][0])),6);per_yaw.setdefault(angle,[]).append(ok)
   f.write(json.dumps({'index':index,'prediction':pred,'GT':ok[0],'B':ok[1],'GT_failed':gt['error_types'],'B_failed':b['error_types']})+'\n')
 summary={'config':SCAN[mode],'confusion':confusion(counts),'examples':examples,'seconds':time.perf_counter()-t,'per_yaw':{str(k):confusion(v) for k,v in per_yaw.items()},'continuous_collision_agreement':confusion(path_counts) if path_counts else None,'not_a_global_feasibility_proof':True}
 write(out/f'{mode}_summary.json',summary);write(out/f'{mode}_feasible_samples.json',valid_positions)
 print(mode,summary['confusion'],flush=True);return summary

def main(module,out,scans=True):
 out.mkdir(parents=True,exist_ok=False);write(out/'predeclared_scan.json',SCAN)
 suite=module/'evidence/pilot02_preview_20261013/suite_v2';broot=module/'evidence/b_prototype_20261013';batch=module/'evidence/pilot02_runs/pilot02_continuation_01';ledger=read(batch/'ledger.json')
 protected=[p for p in broot.rglob('*') if p.is_file()]+[p for p in (module/'evidence/pilot02_runs').rglob('*') if p.is_file()]
 hashes={str(p.relative_to(module)):sha(p) for p in protected};write(out/'protected_before.json',hashes)
 allrows=[];summaries={}
 for scene in SCENES:
  dest=out/scene;dest.mkdir();context=read(suite/scene/'model_inputs/RGB_MULTI_VIEW/context.json');b=read(broot/'inputs_B'/scene/'geometry.json');truth=read(suite/scene/'snapshot.json')['ground_truth'];design=read(suite/scene/'private/design_and_controls.json');envs=environments(context,b,truth)
  write(dest/'B_check_environment.json',{'construction':'frozen B objects/obstacles + public task text regions ONLY','environment':envs['B_full'],'public_context_sha256':sha(suite/scene/'model_inputs/RGB_MULTI_VIEW/context.json'),'frozen_B_geometry_sha256':sha(broot/'inputs_B'/scene/'geometry.json')})
  candidates=[('GT_witness',design['witness'])]+[(f'alternate_{i+1}',p) for i,p in enumerate(design['alternate_witnesses'])]+[('negative_'+name,p) for name,p in design['negative_controls'].items()]
  for run in ledger['runs']:
   if run['job']['scene_id_private_catalog_only']==scene:
    p=parse_prediction((batch/run['artifact']/'raw.txt').read_text(),context['task']);candidates.append(('real_'+run['job']['condition'],p))
  rows=[]
  for name,p in candidates:
   row={'scene':scene,'candidate':name,'prediction':p,'checks':{label:{'required_2mm':result(env,context,p),'zero_clearance_diagnostic_only':result(env,context,p,0),'SAT_projection_threshold':margins(env,context,p)} for label,env in envs.items()}}
   rows.append(row);allrows.append(row)
  write(dest/'candidate_comparison.json',rows)
  comparisons=[(r['checks']['GT']['required_2mm']['success'],r['checks']['B_full']['required_2mm']['success']) for r in rows]
  summary={'candidate_confusion':confusion(comparisons),'candidate_sources':'pre-existing witness, all alternate witnesses, all declared negative controls, archived real A and C; duplicate actions retained and identified','distinct_actions':len({json.dumps(p,sort_keys=True) for _,p in candidates})}
  witness=rows[0];print(scene,{k:(v['required_2mm']['success'],v['SAT_projection_threshold']['placement']['noncollision_lower_m']) for k,v in witness['checks'].items()},flush=True)
  if context['task']['kind']=='path':
   workspace=next(x for x in public_regions(context) if x['id']=='workspace')
   # Intersection here diagnoses inflated volumes; it does not modify either environment.
   summary['estimated_obstacle_workspace_intersections']=[{'id':o['id'],'intersects_public_workspace_at_0':swept_collision(workspace,workspace['center_m'],o,0),'intersects_public_workspace_at_2mm':swept_collision(workspace,workspace['center_m'],o,.002),'center_m':o['center_m'],'size_m':o['size_m']} for o in b['obstacles']]
  if scans:
   for mode in (['detour'] if context['task']['kind']=='path' else ['yaw_global','yaw_local']):summary[mode]=scan(context,envs,mode,dest)
  write(dest/'summary.json',summary);summaries[scene]=summary
 for p,value in hashes.items():assert sha(module/p)==value,'PROTECTED_CHANGED:'+p
 write(out/'summary.json',{'baseline':'2dea56e','scenes':summaries,'named_candidates':confusion([(r['checks']['GT']['required_2mm']['success'],r['checks']['B_full']['required_2mm']['success']) for r in allrows]),'protected_files_unchanged':len(hashes),'new_astra_requests':0,'bridge_connections':0,'authorization_ledgers_created':0,'B_v1_or_plan_modified':False})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--module',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--named-only',action='store_true');a=p.parse_args();main(a.module,a.output,not a.named_only)
