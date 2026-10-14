"""Sealed, independent GT evaluator. Does not modify observations or estimates."""
import argparse,copy,itertools,json,math,time
from pathlib import Path
import numpy as np
from b_task_audit.audit import read,write,sha,public_regions,b_environment,result,margins,confusion,prediction
from b_prototype.diagnose import main as geometry_diagnostics,rot

def verify(folder):
 for f in read(folder/'freeze.json')['files']:assert sha(folder/f['file'])==f['sha256'],f['file']
def candidates(context,config):
 center=public_regions(context)[0]['center_m']
 if context['task']['kind']=='path':
  start=context['task']['constraints']['start_position_m']
  for yi,zi in itertools.product(range(-26,27),range(3,13)):
   p=prediction(center,0);p['quaternion_wxyz']=context['task_policy']['orientation']['quaternion_wxyz'];p['waypoints_m']=[[start[0],yi*.01,zi*.02],[center[0],yi*.01,zi*.02],center];yield p
 else:
  for dx,dy,angle in itertools.product(config['yaw']['xy_offsets_m'],config['yaw']['xy_offsets_m'],range(0,180,2)):
   yield prediction([center[0]+dx,center[1]+dy,center[2]],angle)
def plane_errors(reliability,truth):
 rows=[];sources=[]
 for obj in reliability['objects']:
  if obj['id']=='target':sources.append(('target',obj['details']['angle_rad'],obj['planes'],truth['objects']))
 for comp in reliability['components']:sources.append(('obstacle_component_'+str(comp['component']),comp['angle_rad'],comp['planes'],[b for b in truth['obstacles'] if b['id']!='table']))
 for source,angle,planes,boxes in sources:
  basis=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
  for plane in planes:
   normal=basis[:,plane['axis']]*plane['sign'];level=plane['level_m']*plane['sign'];matches=[]
   for b in boxes:
    axes=rot(b)
    for ax,sign in itertools.product(range(3),(-1,1)):
     face_n=axes[:,ax]*sign
     if np.dot(face_n,normal)>math.cos(math.radians(8)):
      face=np.array(b['center_m'])+axes[:,ax]*sign*b['size_m'][ax]/2
      matches.append((abs(float(face@normal)-level),b['id'],ax,sign))
   best=min(matches) if matches else None
   rows.append({'source':source,'axis':plane['axis'],'sign':plane['sign'],'support_n':plane['support_n'],'views':len(plane['view_support']),'residual_p95_m':plane['residual_p95_m'],'view_spread_m':plane['view_spread_m'],'uncertainty_proxy_m':plane['uncertainty_proxy_m'],'nearest_parallel_face_error_m':best[0] if best else None,'matched_GT_face':list(best[1:]) if best else None,'error_exceeds_proxy':best[0]>plane['uncertainty_proxy_m'] if best else None,'reliability_insufficient':len(plane['view_support'])<2 or plane['uncertainty_proxy_m']>=.001,'association_note':'nearest parallel plane only, finite face overlap not guaranteed; inspect task SAT margins independently'})
 return rows

def evaluate(suite,b1,b2,out,config,scan=True):
 out.mkdir(parents=True,exist_ok=False)
 for path in (b1,b2):verify(path)
 for name,root in [('B1',b1),('B2',b2)]:geometry_diagnostics(suite,root,out/name)
 summary={}
 for folder in sorted(p for p in b2.iterdir() if p.is_dir()):
  scene=folder.name;dest=out/scene;dest.mkdir();ctx=read(suite/scene/'model_inputs/RGB_MULTI_VIEW/context.json');truth=read(suite/scene/'snapshot.json')['ground_truth'];design=read(suite/scene/'private/design_and_controls.json')
  envs={'GT':{'ground_truth':truth},'B1':b_environment(ctx,read(b1/scene/'geometry.json')),'B2':b_environment(ctx,read(b2/scene/'geometry.json'))}
  assert truth['regions']==public_regions(ctx)
  named=[('witness',design['witness'])]+[(f'alternate_{i}',p) for i,p in enumerate(design['alternate_witnesses'])]+[('negative_'+k,p) for k,p in design['negative_controls'].items()]
  records=[]
  for name,p in named:
   records.append({'name':name,'prediction':p,'checks':{k:{'score':result(env,ctx,p),'SAT_projection_threshold':margins(env,ctx,p)} for k,env in envs.items()}})
  write(dest/'named_candidates.json',records)
  reliability=read(folder/'reliability.json');write(dest/'boundary_diagnostics.json',plane_errors(reliability,truth))
  row={'named':{k:confusion([(r['checks']['GT']['score']['success'],r['checks'][k]['score']['success']) for r in records]) for k in ('B1','B2')},'witness_GT_success':records[0]['checks']['GT']['score']['success'],'negative_GT_failures':{r['name']:not r['checks']['GT']['score']['success'] for r in records if r['name'].startswith('negative_')},'unknown_or_rejected_cells':len(reliability['unknown_or_rejected']),'missing':reliability['missing'],'reliability_warning':'raw boxes are hypotheses; omitted/unknown geometry can create false acceptance. Sidecar warnings do not repair geometry.'}
  if scan:
   t=time.perf_counter();pairs={k:[] for k in ('B1','B2')};paths={k:[] for k in pairs}
   with (dest/'samples.jsonl').open('w') as f:
    for i,p in enumerate(candidates(ctx,config)):
     checks={k:result(env,ctx,p) for k,env in envs.items()};entry={'index':i,'prediction':p,'success':{k:v['success'] for k,v in checks.items()},'failures':{k:v['error_types'] for k,v in checks.items()}}
     for k in pairs:
      pairs[k].append((checks['GT']['success'],checks[k]['success']))
      if ctx['task']['kind']=='path':paths[k].append((checks['GT']['constraints']['continuous_path_collision_free'],checks[k]['constraints']['continuous_path_collision_free']))
     f.write(json.dumps(entry)+'\n')
   row['scan']={k:confusion(v) for k,v in pairs.items()};row['continuous_collision']={k:confusion(v) for k,v in paths.items() if v};row['scan_seconds']=time.perf_counter()-t
  summary[scene]=row;write(dest/'summary.json',row);print('TASK_RESULT',scene,json.dumps(row),flush=True)
 for path in (b1,b2):verify(path)
 write(out/'summary.json',summary)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--module',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();e=a.module/'evidence/b_v2_20261014';seal=read(e/'estimates_sealed.json')
 for name,value in seal['freezes_sha256'].items():assert sha(e/name/'freeze.json')==value
 for name,value in read(e/'pre_estimation_lock.json')['source_sha256'].items():assert sha(a.module/name)==value
 config=read(e/'scan_predeclaration.json');a.output.mkdir(parents=True,exist_ok=False);write(a.output/'evaluation_binding.json',{'seal_sha256':sha(e/'estimates_sealed.json'),'scan_config_sha256':sha(e/'scan_predeclaration.json'),'new_model_requests':0,'clearance_m':.002})
 evaluate(e/'validation_suite',e/'validation_B1',e/'validation_B2',a.output/'validation',config)
 evaluate(a.module/'evidence/pilot02_preview_20261013/suite_v2',a.module/'evidence/b_prototype_20261013/inputs_B',e/'development_B2',a.output/'development',config,False)
