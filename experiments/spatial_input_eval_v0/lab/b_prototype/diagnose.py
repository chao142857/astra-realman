"""Independent, post-freeze evaluator. Reads GT; writes only a separate diagnostics directory."""
import argparse,json,hashlib,itertools,math,time
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from PIL import Image,ImageDraw
from spatial_eval.geometry import validate_geometry,corners

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def rot(b):q=b['quaternion_wxyz'];return Rotation.from_quat([q[1],q[2],q[3],q[0]]).as_matrix()
def inside(points,boxes):
 result=np.zeros(len(points),bool)
 for b in boxes:result|=(np.abs((points-np.array(b['center_m']))@rot(b))<=np.array(b['size_m'])/2+1e-10).all(1)
 return result

def main(suite,estimates,out):
 out.mkdir(parents=True,exist_ok=False);freeze=read(estimates/'freeze.json')
 for f in freeze['files']:assert sha(estimates/f['file'])==f['sha256']
 rows=[]
 for folder in sorted(p for p in estimates.iterdir() if p.is_dir()):
  scene=folder.name;g=read(folder/'geometry.json');validate_geometry(g)
  # GT is first accessed only after B was frozen. No writes to the estimates.
  truth=read(suite/scene/'snapshot.json')['ground_truth'];target=next(b for b in truth['objects'] if b['id']=='target');estimate=g['objects'][0] if g['objects'] else None
  row={'scene':scene,'target_detected':bool(estimate),'obstacle_boxes':len(g['obstacles']),'timing':read(folder/'timing.json'),'gt_fed_back_to_estimator':False}
  if estimate:
   a=np.array(corners(estimate));b=np.array(corners(target));haus=max(cKDTree(a).query(b)[0].max(),cKDTree(b).query(a)[0].max())
   row['target_errors']={'center_vector_l2_m':float(np.linalg.norm(np.array(estimate['center_m'])-target['center_m'])),'size_sorted_vector_l2_m':float(np.linalg.norm(np.sort(estimate['size_m'])-np.sort(target['size_m']))),'height_scalar_abs_m':abs(estimate['size_m'][2]-target['size_m'][2]),'corner_set_hausdorff_m':float(haus),'note':'Sorted dimensions and corner-set comparison are invariant to cuboid axis relabeling; not a signed yaw error.'}
  obstacles=[b for b in truth['obstacles'] if b['id']!='table'];allcorners=np.array([c for b in obstacles+g['obstacles'] for c in corners(b)])
  step=.01;lo=np.floor(allcorners.min(0)/step)*step-step;hi=allcorners.max(0)+step
  grid=np.stack(np.meshgrid(*[np.arange(lo[i]+step/2,hi[i],step) for i in range(3)],indexing='ij'),-1).reshape(-1,3)
  predicted=inside(grid,g['obstacles']);actual=inside(grid,obstacles);inter=int((predicted&actual).sum());union=int((predicted|actual).sum())
  row['obstacle_occupancy']={'sampling_grid_m':step,'grid_points':len(grid),'intersection_points':inter,'predicted_points':int(predicted.sum()),'gt_points':int(actual.sum()),'precision':inter/int(predicted.sum()) if predicted.any() else None,'recall_coverage':inter/int(actual.sum()) if actual.any() else None,'iou':inter/union if union else None,'excluded_table':'Explicit missing surface; not silently treated as reconstructed. Metrics cover task-relevant non-table obstacles only.','per_gt_obstacle':[]}
  for b in obstacles:
   mask=inside(grid,[b]);n=int(mask.sum());row['obstacle_occupancy']['per_gt_obstacle'].append({'id':b['id'],'sampled_volume_points':n,'covered_fraction':int((mask&predicted).sum())/n if n else None})
  # Independent GT overlay, never a model input.
  canvas=Image.new('RGB',(900,650),'white');draw=ImageDraw.Draw(canvas)
  boxes=obstacles+[target];xy=np.array([c[:2] for b in boxes+g['obstacles']+g['objects'] for c in corners(b)]);low=xy.min(0)-.05;high=xy.max(0)+.05;scale=min(820/(high[0]-low[0]),530/(high[1]-low[1]))
  def point(p):return (40+(p[0]-low[0])*scale,610-(p[1]-low[1])*scale)
  for collection,color in [(boxes,'#aaaaaa'),(g['obstacles'],'#2266cc'),(g['objects'],'#dd2222')]:
   for b in collection:
    aa=rot(b);c=np.array(b['center_m']);half=np.array(b['size_m'])/2;poly=[point(c+aa@np.array([sx*half[0],sy*half[1],0])) for sx,sy in [(-1,-1),(-1,1),(1,1),(1,-1)]];draw.line(poly+[poly[0]],fill=color,width=2)
  draw.text((20,15),scene+' | INDEPENDENT DIAGNOSTIC ONLY',fill='black');draw.text((20,35),'gray=GT; blue=estimated obstacles; red=estimated target; top view',fill='black');canvas.save(out/f'{scene}_geometry.png')
  rows.append(row)
 for f in freeze['files']:assert sha(estimates/f['file'])==f['sha256']
 write(out/'geometry_diagnostics.json',{'version':'b_independent_diagnostics.v1','estimates_freeze_sha256':sha(estimates/'freeze.json'),'inputs_unchanged_after_diagnostics':True,'new_astra_requests':0,'rows':rows,'limitations':['10 mm sampled occupancy is a coarse volume diagnostic, not exact geometric clearance or collision certification.','Unseen interiors are extruded under an upright-object assumption; phantom occupancy and missed geometry are possible.','No GT diagnostic is fed back to this frozen input version.']})
 print(json.dumps(rows,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True);p.add_argument('--estimates',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.suite,a.estimates,a.output)
