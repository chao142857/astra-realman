"""Scientific audit figures; reads diagnostics and frozen geometry, never writes inputs."""
import argparse,json,itertools
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.colors import ListedColormap,BoundaryNorm
from spatial_eval.geometry import corners,axes
from audit import SCENES,read,public_regions
COLORS=['#e5e7eb','#14a58b','#eb8245','#6948b9']
def xy_polygon(box):
 c=np.array(box['center_m']);a=np.array(axes(box['quaternion_wxyz']));s=np.array(box['size_m'])/2
 return np.array([(c+sx*s[0]*a[0]+sy*s[1]*a[1])[:2] for sx,sy in [(-1,-1),(-1,1),(1,1),(1,-1)]])
def category(gt,b):return 1 if gt and b else 2 if gt else 3 if b else 0
def main(module,root):
 out=root/'figures';out.mkdir(exist_ok=True);suite=module/'evidence/pilot02_preview_20261013/suite_v2';broot=module/'evidence/b_prototype_20261013/inputs_B'
 fig,axs=plt.subplots(1,2,figsize=(12,4),layout='constrained');labels=['GT','B target only','B obstacles only','B full']
 for ax,scene in zip(axs,SCENES[2:]):
  row=read(root/scene/'candidate_comparison.json')[0];vals=[row['checks'][key]['SAT_projection_threshold']['placement']['noncollision_lower_m']*1000 for key in ['GT','B_target_only','B_obstacles_only','B_full']]
  ax.bar(labels,vals,color=['#888','#77aadd','#ddbb77','#bb5566']);ax.axhline(2,color='red',ls='--',label='Required 2 mm');ax.set(title=scene,ylabel='Original SAT clearance threshold (mm)');ax.tick_params(axis='x',rotation=15)
  for i,value in enumerate(vals):ax.text(i,value+.15,f'{value:.4f}',ha='center',bbox={'facecolor':'white','edgecolor':'none','pad':1})
  ax.legend()
 fig.suptitle('Frozen witness pose: target/obstacle ablations (not Euclidean clearance)');fig.savefig(out/'yaw_ablation.png',dpi=170);plt.close(fig)
 for scene in SCENES:
  ctx=read(suite/scene/'model_inputs/RGB_MULTI_VIEW/context.json');g=read(suite/scene/'snapshot.json')['ground_truth'];b=read(broot/scene/'geometry.json');rows=read(root/scene/'candidate_comparison.json');w=rows[0]['prediction']
  fig,axs=plt.subplots(1,2,figsize=(12,5),layout='constrained')
  for ax,geometry,title in [(axs[0],g,'GT'),(axs[1],b,'B v1')]:
   for o in geometry['obstacles']:ax.add_patch(Polygon(xy_polygon(o),facecolor='#bbb' if title=='GT' else '#77aadd',alpha=.45,edgecolor='#666',lw=.5))
   for r in public_regions(ctx):ax.add_patch(Polygon(xy_polygon(r),fill=False,edgecolor='#159947',ls='--'))
   target=dict(geometry['objects'][0],center_m=w['position_m'],quaternion_wxyz=w['quaternion_wxyz']);ax.add_patch(Polygon(xy_polygon(target),facecolor='#ee7744',alpha=.8,edgecolor='black'))
   if ctx['task']['kind']=='path':
    pts=np.array([ctx['task']['constraints']['start_position_m'],*w['waypoints_m']]);ax.plot(pts[:,0],pts[:,1],'.-',color='#cc2277',label='GT witness path');ax.set(xlim=(.08,.88),ylim=(-.33,.33))
   else:
    c=w['position_m'];ax.set(xlim=(c[0]-.11,c[0]+.11),ylim=(c[1]-.11,c[1]+.11))
   check=rows[0]['checks']['GT' if title=='GT' else 'B_full']['required_2mm'];ax.set(title=f'{title}: witness {"PASS" if check["success"] else "FAIL"} at 2 mm',xlabel='world x (m)',ylabel='world y (m)');ax.set_aspect('equal');ax.grid(alpha=.2)
  fig.suptitle(scene+' — diagnostic geometry only');fig.savefig(out/f'{scene}_geometry.png',dpi=170);plt.close(fig)
  if ctx['task']['kind']=='path':
   rail_ids=read(root/'exploratory_followup'/scene/'summary.json')['assigned_rail_ids']
   fig,ax=plt.subplots(figsize=(9,4),layout='constrained')
   for boxes,color,label in [([o for o in g['obstacles'] if o['id'].startswith('height_rail')],'#777777','GT rails'),([o for o in b['obstacles'] if o['id'] in rail_ids],'#77aadd','B rail-associated boxes')]:
    for i,o in enumerate(boxes):
     pts=np.array(corners(o));low=pts.min(0);high=pts.max(0);poly=np.array([[low[1],low[2]],[low[1],high[2]],[high[1],high[2]],[high[1],low[2]]]);ax.add_patch(Polygon(poly,facecolor=color,alpha=.45,label=label if i==0 else None))
   workspace=next(r for r in public_regions(ctx) if r['id']=='workspace');pts=np.array(corners(workspace));low=pts.min(0);high=pts.max(0);poly=np.array([[low[1],low[2]],[low[1],high[2]],[high[1],high[2]],[high[1],low[2]]]);ax.add_patch(Polygon(poly,fill=False,edgecolor='#159947',ls='--',label='public workspace'))
   ax.set(xlim=(-.32,.32),ylim=(0,.29),xlabel='world y (m)',ylabel='world z (m)',title=scene+' — rail extrusion, y-z projection (all x)');ax.legend(loc='center');fig.savefig(out/f'{scene}_rails_yz.png',dpi=170);plt.close(fig)
   samples=[json.loads(line) for line in (root/scene/'detour_samples.jsonl').read_text().splitlines()];arr=np.zeros((9,49),int)
   for r in samples:
    y,z=r['prediction']['waypoints_m'][0][1:];arr[round(z/.02)-3,round(y/.01)+24]=category(r['GT'],r['B'])
   fig,ax=plt.subplots(figsize=(10,4),layout='constrained');im=ax.imshow(arr,origin='lower',extent=[-.245,.245,.05,.23],aspect='auto',cmap=ListedColormap(COLORS),vmin=0,vmax=3);ax.set(xlabel='lateral waypoint y (m)',ylabel='waypoint z (m)',title=scene+' — fixed-orientation path family, continuous SAT');cb=fig.colorbar(im,ax=ax,ticks=[0,1,2,3]);cb.ax.set_yticklabels(['neither','GT & B','GT only','B only']);fig.savefig(out/f'{scene}_path_grid.png',dpi=170);plt.close(fig)
  else:
   samples=[json.loads(line) for line in (root/'exploratory_followup'/scene/'refined_samples.jsonl').read_text().splitlines()];center=public_regions(ctx)[0]['center_m'];field=np.zeros((25,25),int);gt=np.zeros((25,25),bool);bb=np.zeros_like(gt)
   for r in samples:
    x,y=r['prediction']['position_m'][:2];i=round((x-center[0])/.0005)+12;j=round((y-center[1])/.0005)+12;gt[j,i]|=r['GT'];bb[j,i]|=r['B']
   for j,i in itertools.product(range(25),repeat=2):field[j,i]=category(gt[j,i],bb[j,i])
   fig,ax=plt.subplots(figsize=(6,5),layout='constrained');im=ax.imshow(field,origin='lower',extent=[-6.25,6.25,-6.25,6.25],cmap=ListedColormap(COLORS),vmin=0,vmax=3);ax.set(xlabel='x offset from public center (mm)',ylabel='y offset (mm)',title=scene+' — any scanned yaw feasible\n0.5 mm XY; witness yaw +/-6 deg at 0.25 deg; center z');cb=fig.colorbar(im,ax=ax,ticks=[0,1,2,3]);cb.ax.set_yticklabels(['neither','GT & B','GT only','B only']);fig.savefig(out/f'{scene}_refined_space.png',dpi=170);plt.close(fig)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--module',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);a=p.parse_args();main(a.module,a.audit)
