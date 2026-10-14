"""Explicitly exploratory refinement after initial scan; no model or B input writes."""
import argparse,copy,itertools,json,math,time
from pathlib import Path
from spatial_eval.geometry import contains,swept_collision
from audit import SCENES,read,write,sha,public_regions,environments,result,prediction,confusion,margins
PLAN={'reason':'Exploratory follow-up after coarse/local scans; not part of initial predeclared grid. No changes to B or future 36-run plan.','yaw_refinement':{'position_offsets_xy_m':[-.006,.006],'xy_step_m':.0005,'z':'public task-volume center','yaw':'private diagnostic witness yaw +/- 6 degrees, inclusive','yaw_step_deg':.25,'source_note':'GT-witness-guided diagnostic slice, not unseen model testing'},'rail_boundary_probe':{'x_step_m':.005,'y_inset_from_both_geometry_contained_boundary_m':[0,.001,.002,.005,.01],'z':'lower/center/upper jointly-contained workspace center heights','rail_assignment':'evaluation-only: B box center y within 20mm of GT height rail center and B y-size <=30mm','failure_attribution':'compare B full against B without rail-associated components, diagnostics only'},'new_generation_budget':0}
def collision(env,p,clearance):
 g=env['ground_truth'];held=dict(g['objects'][0],center_m=p,quaternion_wxyz=[1,0,0,0]);return any(swept_collision(held,p,o,clearance) for o in g['obstacles'])
def main(module,audit_root,out):
 out.mkdir(parents=True,exist_ok=False);write(out/'exploratory_plan.json',PLAN);broot=module/'evidence/b_prototype_20261013';suite=module/'evidence/pilot02_preview_20261013/suite_v2';freeze=read(broot/'inputs_B/freeze.json');summaries={}
 for scene in SCENES:
  dest=out/scene;dest.mkdir();ctx=read(suite/scene/'model_inputs/RGB_MULTI_VIEW/context.json');b=read(broot/'inputs_B'/scene/'geometry.json');truth=read(suite/scene/'snapshot.json')['ground_truth'];envs=environments(ctx,b,truth);center=public_regions(ctx)[0]['center_m'];summary={}
  if ctx['task']['kind']=='placement':
   witness=read(suite/scene/'private/design_and_controls.json')['witness'];q=witness['quaternion_wxyz'];angle=math.degrees(2*math.atan2(q[3],q[0]));pairs=[];feasible=[];best=None;t=time.perf_counter()
   with (dest/'refined_samples.jsonl').open('w') as f:
    for ix,iy,ai in itertools.product(range(-12,13),range(-12,13),range(-24,25)):
     p=prediction([center[0]+ix*.0005,center[1]+iy*.0005,center[2]],angle+ai*.25);gt=result(envs['GT'],ctx,p);bb=result(envs['B_full'],ctx,p);pairs.append((gt['success'],bb['success']))
     row={'prediction':p,'GT':gt['success'],'B':bb['success']};f.write(json.dumps(row)+'\n')
     if bb['success']:
      feasible.append(row)
      # Keep an existence certificate at the first successful sample, no optimization claim.
      if best is None:best={'prediction':p,'GT':gt,'B':bb,'thresholds':{label:margins(env,ctx,p) for label,env in envs.items()}}
   summary={'confusion':confusion(pairs),'seconds':time.perf_counter()-t,'first_B_feasible_certificate':best,'not_a_global_proof':True};write(dest/'B_feasible_samples.json',feasible)
  else:
   work=next(x for x in public_regions(ctx) if x['id']=='workspace');targetGT=truth['objects'][0];targetB=b['objects'][0];rails=[o for o in truth['obstacles'] if o['id'].startswith('height_rail')]
   ids=[o['id'] for o in b['obstacles'] if o['size_m'][1]<=.03 and any(abs(o['center_m'][1]-r['center_m'][1])<=.02 for r in rails)]
   railenv=copy.deepcopy(envs['B_full']);railenv['ground_truth']['obstacles']=[o for o in b['obstacles'] if o['id'] in ids]
   norail=copy.deepcopy(envs['B_full']);norail['ground_truth']['obstacles']=[o for o in b['obstacles'] if o['id'] not in ids]
   half=[max(targetGT['size_m'][i],targetB['size_m'][i])/2 for i in range(3)];low=[work['center_m'][i]-work['size_m'][i]/2+half[i] for i in range(3)];high=[work['center_m'][i]+work['size_m'][i]/2-half[i] for i in range(3)];samples=[]
   for xi,side,inset,z in itertools.product(range(math.floor((high[0]-low[0])/.005)+1),[-1,1],[0,.001,.002,.005,.01],[low[2],work['center_m'][2],high[2]]):
    p=[low[0]+xi*.005,low[1]+inset if side<0 else high[1]-inset,z]
    if not all(contains(work,dict(e['ground_truth']['objects'][0],center_m=p,quaternion_wxyz=[1,0,0,0])) for e in [envs['GT'],envs['B_full']]):continue
    gt=not collision(envs['GT'],p,.002);railhit=collision(railenv,p,.002);without=not collision(norail,p,.002);full=not collision(envs['B_full'],p,.002)
    samples.append({'position_m':p,'GT_collision_free':gt,'B_full_collision_free':full,'B_without_rail_collision_free':without,'B_rail_collision':railhit,'rail_uniquely_rejects_otherwise_free':gt and without and railhit})
   extra=[x for x in samples if x['rail_uniquely_rejects_otherwise_free']];summary={'assigned_rail_ids':ids,'jointly_contained_probe_samples':len(samples),'GT_free_samples':sum(x['GT_collision_free'] for x in samples),'GT_free_hit_by_B_rails':sum(x['GT_collision_free'] and x['B_rail_collision'] for x in samples),'rail_unique_false_rejections':len(extra),'first_unique_example':extra[0] if extra else None,'not_a_global_proof':True};write(dest/'rail_boundary_samples.json',samples)
   # Localize the initial detour discrepancies using original scorer and four ablations.
   rejects=[]
   for line in (audit_root/scene/'detour_samples.jsonl').read_text().splitlines():
    x=json.loads(line)
    if x['GT'] and not x['B']:rejects.append({'prediction':x['prediction'],'checks':{label:result(env,ctx,x['prediction']) for label,env in envs.items()}})
   write(dest/'detour_false_rejection_ablation.json',rejects)
  write(dest/'summary.json',summary);summaries[scene]=summary;print(scene,{k:v for k,v in summary.items() if k!='first_B_feasible_certificate'},flush=True)
 for f in freeze['files']:assert sha(broot/'inputs_B'/f['file'])==f['sha256']
 write(out/'summary.json',summaries)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--module',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.module,a.audit,a.output)
