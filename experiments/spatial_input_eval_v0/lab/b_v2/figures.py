"""Independent diagnostic figures from sealed artifacts; never model inputs."""
import argparse,json,copy,itertools
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon,Rectangle
from PIL import Image,ImageDraw
from spatial_eval.geometry import corners,axes
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();r=a.root;o=r/'figures';o.mkdir(exist_ok=True)
def read(p):return json.loads(p.read_text())
def poly(box):
 c=np.array(box['center_m']);ax=np.array(axes(box['quaternion_wxyz']));s=np.array(box['size_m'])/2
 return np.array([(c+sx*s[0]*ax[0]+sy*s[1]*ax[1])[:2] for sx,sy in [(-1,-1),(-1,1),(1,1),(1,-1)]])
def envs(scene):return [read(r/'validation_suite'/scene/'snapshot.json')['ground_truth']]+[read(r/f'validation_{v}'/scene/'geometry.json') for v in ('B1','B2')]
# The independent suite's actual rendered RGB, without overlays.
canvas=Image.new('RGB',(1440,6*290),'white');d=ImageDraw.Draw(canvas)
for row,scene in enumerate(sorted(p.name for p in (r/'validation_B2').iterdir() if p.is_dir())):
 d.text((10,row*290+4),scene+' | actual SAPIEN RGB',fill='black')
 for i in range(3):canvas.paste(Image.open(r/'public_validation'/scene/f'image-{i}.png').resize((360,270)),(i*480,row*290+20))
canvas.save(o/'rendered_validation.png')
# At each yaw scene, display a retained witness and the first false acceptance where present.
for scene in ('v2_val_yaw_01','v2_val_yaw_02','v2_val_yaw_03'):
 geometry=envs(scene);witness=read(r/'validation_suite'/scene/'private/design_and_controls.json')['witness'];bad=None
 for line in (r/'evaluation/validation'/scene/'samples.jsonl').read_text().splitlines():
  x=json.loads(line)
  if x['success']['B2'] and not x['success']['GT']:bad=x['prediction'];break
 preds=[('predeclared legal witness',witness)]+([('first sampled B2 false acceptance',bad)] if bad else [])
 fig,axs=plt.subplots(len(preds),3,figsize=(12,4*len(preds)),squeeze=False)
 for row,(label,pred) in enumerate(preds):
  for col,(label_g,g) in enumerate(zip(('GT','B v1','B v2'),geometry)):
   ax=axs[row,col]
   for b in geometry[0]['obstacles']:
    if b['id']!='table':ax.add_patch(Polygon(poly(b),fill=False,ec='0.65',lw=1))
   for b in g['obstacles']:
    if b['id']=='table':continue
    if b['center_m'][2]-b['size_m'][2]/2 <= pred['position_m'][2] <= b['center_m'][2]+b['size_m'][2]/2:ax.add_patch(Polygon(poly(b),color=['#999999','#4477aa','#ee7733'][col],alpha=.35))
   b=copy.deepcopy(g['objects'][0]);b.update(center_m=pred['position_m'],quaternion_wxyz=pred['quaternion_wxyz']);ax.add_patch(Polygon(poly(b),fc='#cc3311',alpha=.7));ax.set_title(label_g+' | '+label,fontsize=9);ax.set_aspect('equal');center=pred['position_m'];ax.set_xlim(center[0]-.12,center[0]+.12);ax.set_ylim(center[1]-.12,center[1]+.12);ax.set_xlabel('world x (m)');ax.set_ylabel('world y (m)');ax.grid(alpha=.15)
 fig.suptitle(scene+' | Independent GT diagnostic; gray outline = GT');fig.tight_layout();fig.savefig(o/f'{scene}_task_comparison.png',dpi=140);plt.close(fig)
# Corridor side-view projections reveal B1 false downward beam extrusion.
scene='v2_val_path_03';geometry=envs(scene);w=read(r/'validation_suite'/scene/'private/design_and_controls.json')['witness'];y=w['waypoints_m'][0][1]
fig,axs=plt.subplots(1,3,figsize=(13,4))
for ax,label,g in zip(axs,('GT','B v1','B v2'),geometry):
 for b in g['obstacles']:
  if b['id']=='table':continue
  c=np.array(corners(b));lo=c.min(0);hi=c.max(0)
  if lo[1]<=y<=hi[1]:ax.add_patch(Rectangle((lo[0],lo[2]),hi[0]-lo[0],hi[2]-lo[2],fc='#4477aa',alpha=.4))
 pts=np.array(w['waypoints_m']);ax.plot(pts[:,0],pts[:,2],color='#cc3311',lw=2,label='GT legal center path');ax.axhspan(.11-.026,.11+.026,color='#cc3311',alpha=.12);ax.set_xlim(.13,.78);ax.set_ylim(0,.29);ax.set_xlabel('world x (m)');ax.set_ylabel('height z (m)');ax.set_title(label);ax.grid(alpha=.2)
fig.suptitle(f'{scene} | corridor y={y:.3f} m; intersecting-box XZ bounds (not exact oblique cross sections)');fig.tight_layout();fig.savefig(o/'local_height_corridor.png',dpi=150);plt.close(fig)
# Task candidate aggregate, with denominators visible.
summary=read(r/'evaluation/validation/summary.json');fig,axs=plt.subplots(1,2,figsize=(12,4))
for index,metric in enumerate(('retention_given_GT_feasible','false_acceptance_given_GT_infeasible')):
 ax=axs[index];names=list(summary)
 for j,v in enumerate(('B1','B2')):ax.bar(np.arange(6)+(.16 if j else -.16),[summary[n]['scan'][v][metric]*100 for n in names],width=.32,label=v)
 ax.set_xticks(range(6),['path 1','path 2','path 3','yaw 1','yaw 2','yaw 3']);ax.set_ylabel('% sampled candidates');ax.set_title('GT legal candidates retained' if index==0 else 'GT illegal candidates accepted');ax.legend();ax.grid(axis='y',alpha=.2)
fig.suptitle('Finite predeclared samples; not a global feasibility proof');fig.tight_layout();fig.savefig(o/'task_rates.png',dpi=150);plt.close(fig)
