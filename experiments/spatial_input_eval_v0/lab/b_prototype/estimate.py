"""Public RGB-D only; no imports from simulator, scoring, snapshots or private specs."""
import argparse, hashlib, json, math, time, shutil
from pathlib import Path
import numpy as np
from scipy import ndimage
from scipy.spatial.transform import Rotation
from PIL import Image, ImageDraw
VERSION='public_rgbd_boxes.v1'
CONFIG={'grid_m':0.005,'red_min':70,'red_ratio':1.5,'gray_channel_spread_max':18,'gray_min':30,'floor_exclusion_m':0.015,'top_band_m':0.003,'minimum_component_cells':8,'closing_iterations':1,'yaw_step_degrees':0.5,'footprint_frame':'observed_neutral_minimum_area_rectangle'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def backproject(depth,cal):
 h,w=depth.shape;v,u=np.indices((h,w));k=np.array(cal['intrinsic']);z=depth
 # OpenCV (right,down,forward) -> SAPIEN local (forward,left,up).
 local=np.stack([z,-(u-k[0,2])*z/k[0,0],-(v-k[1,2])*z/k[1,1]],-1)
 pose=cal['pose_base_xyz_wxyz'];q=pose[3:];rot=Rotation.from_quat([q[1],q[2],q[3],q[0]]).as_matrix()
 return local@rot.T+pose[:3]
def obb(points):
 best=None
 for degree in np.arange(0,90,CONFIG['yaw_step_degrees']):
  angle=np.deg2rad(degree);rot=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
  xy=points[:,:2]@rot;lo=xy.min(0);hi=xy.max(0);area=np.prod(hi-lo)
  if best is None or area<best[0]:best=(area,angle,rot,lo,hi)
 _,angle,rot,lo,hi=best;center=((lo+hi)/2)@rot.T;zlo,zhi=points[:,2].min(),points[:,2].max()
 return {'id':'target','center_m':[*center,(zlo+zhi)/2],'size_m':[*list(hi-lo),zhi-zlo],'quaternion_wxyz':[math.cos(angle/2),0,0,math.sin(angle/2)]}
def rectangles(mask):
 m=mask.copy();result=[]
 while m.any():
  y,x=np.argwhere(m)[0];x1=x
  while x1<m.shape[1] and m[y,x1]:x1+=1
  y1=y+1
  while y1<m.shape[0] and m[y1:y1+1,x:x1].all():y1+=1
  result.append((x,y,x1,y1));m[y:y1,x:x1]=False
 return result

def estimate(folder,out):
 start=time.perf_counter();out.mkdir(parents=True,exist_ok=False);context=read(folder/'context.json');assert context['geometry'] is None
 clouds=[];reds=[];grays=[];views=[];preview=[]
 for i,a in enumerate(context['attachments']):
  rgb=np.array(Image.open(folder/f'image-{i}.png').convert('RGB')).astype(float);depth=np.load(folder/f'depth-{i}.npy',allow_pickle=False);valid=np.load(folder/f'valid-{i}.npy',allow_pickle=False).astype(bool)
  assert sha(folder/f'image-{i}.png')==a['sha256']
  good=valid&np.isfinite(depth)&(depth>0)&(depth<10);p=backproject(depth,context['observations']['calibration'][a['camera_id']])
  red=good&(rgb[:,:,0]>CONFIG['red_min'])&(rgb[:,:,0]>CONFIG['red_ratio']*rgb[:,:,1])&(rgb[:,:,0]>CONFIG['red_ratio']*rgb[:,:,2])
  gray=good&(np.ptp(rgb,axis=2)<CONFIG['gray_channel_spread_max'])&(rgb.min(2)>CONFIG['gray_min'])
  clouds.append(p[good]);reds.append(p[red]);grays.append(p[gray]);views.append({'camera':a['camera_id'],'valid_depth_pixels':int(good.sum()),'red_pixels':int(red.sum()),'neutral_pixels':int(gray.sum())})
  im=rgb.astype(np.uint8);im[red]=[255,70,70];im[gray]=((im[gray].astype(float)+[30,70,230])/2).astype(np.uint8);preview.append(Image.fromarray(im).resize((480,360)))
 cloud=np.concatenate(clouds);red=np.concatenate(reds);gray=np.concatenate(grays)
 # Dominant horizontal height is estimated from observations, not simulator state.
 bins=np.round(cloud[:,2]/.002).astype(int);zplane=float(np.median(cloud[bins==np.bincount(bins-bins.min()).argmax()+bins.min(),2]))
 gray=gray[gray[:,2]>zplane+CONFIG['floor_exclusion_m']]
 missing=['Back/bottom surfaces are not guaranteed observed.','Floor/table omitted after dominant-height removal.','Upright extrusion and top-surface visibility are assumptions; no certification of free space.','Public task volumes remain in task text; regions are not re-estimated.']
 objects=[obb(red)] if len(red)>=100 else [];obstacles=[];parts=[]
 if not objects:missing.append('Target estimate failed: insufficient red depth points.')
 # Disjoint top footprints preserve visible slots instead of enclosing empty space.
 step=CONFIG['grid_m']
 if len(gray):
  frame=obb(gray[::20]);q=frame['quaternion_wxyz'];angle=2*math.atan2(q[3],q[0]);rot=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
  zbottom=float(gray[:,2].min());zmax=float(gray[:,2].max());hist,edges=np.histogram(gray[:,2],bins=np.arange(zbottom,zmax+.003,.002))
  peaks=np.flatnonzero((hist>=np.roll(hist,1))&(hist>=np.roll(hist,-1))&(hist>=max(100,hist.max()*.04)))
  for peak in peaks:
   top=float((edges[peak]+edges[peak+1])/2)
   if top-zbottom<.01:continue
   pts=gray[abs(gray[:,2]-top)<CONFIG['top_band_m']];ij=np.floor((pts[:,:2]@rot)/step).astype(int);origin=ij.min(0)-2;ij-=origin
   mask=np.zeros(tuple(ij.max(0)[::-1]+3),bool);mask[ij[:,1],ij[:,0]]=True;mask=ndimage.binary_closing(mask,iterations=CONFIG['closing_iterations'])
   labels,n=ndimage.label(mask)
   for label in range(1,n+1):
    component=labels==label
    if component.sum()<CONFIG['minimum_component_cells']:continue
    for x,y,x1,y1 in rectangles(component):
     lo=(origin+np.array([x,y]))*step;hi=(origin+np.array([x1,y1]))*step
     obstacles.append({'id':f'observed_obstacle_{len(obstacles):03d}','center_m':[*(((lo+hi)/2)@rot.T),(zbottom+top)/2],'size_m':[*list(hi-lo),top-zbottom],'quaternion_wxyz':q})
   parts.append({'observed_top_m':top,'footprint_cells':int(mask.sum())})
 else:missing.append('No neutral obstacle depth samples above floor.')
 elapsed=time.perf_counter()-start
 geometry={'source':'RECONSTRUCTION','frame':'robot_base','units':'m','objects':objects,'regions':[],'obstacles':obstacles,'renderings':[]}
 write(out/'geometry.json',geometry);write(out/'diagnostic_public.json',{'version':VERSION,'config':CONFIG,'views':views,'target_points':len(red),'neutral_points_above_floor':len(gray),'estimated_floor_height_m':zplane,'top_layers':parts,'missing_and_assumptions':missing,'segmentation_used':False,'geometry_estimation_s':elapsed})
 prepare=time.perf_counter();context['geometry']=geometry;write(out/'context.json',context)
 for i in range(3):shutil.copyfile(folder/f'image-{i}.png',out/f'image-{i}.png')
 canvas=Image.new('RGB',(1440,390),'white')
 for i,im in enumerate(preview):canvas.paste(im,(i*480,30))
 ImageDraw.Draw(canvas).text((10,8),'RGB threshold masks: red target / blue neutral candidates (NO simulator segmentation)',fill='black');canvas.save(out/'mask_preview.png')
 write(out/'timing.json',{'geometry_estimation_s':elapsed,'input_preparation_and_preview_s':time.perf_counter()-prepare,'total_s':time.perf_counter()-start,'clock':'perf_counter; wall time; includes local I/O','host':__import__('platform').node()})
 return geometry
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--public',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 m=read(a.public/'manifest.json')
 for f in m['files']:assert sha(a.public/f['file'])==f['sha256']
 for folder in sorted(x for x in a.public.iterdir() if x.is_dir()):
  g=estimate(folder,a.output/folder.name);print(folder.name,len(g['objects']),len(g['obstacles']),flush=True)
 write(a.output/'freeze.json',{'version':VERSION,'estimator_sha256':sha(Path(__file__)),'config':CONFIG,'files':[{'file':str(p.relative_to(a.output)),'sha256':sha(p)} for p in sorted(a.output.rglob('*')) if p.is_file()],'new_astra_requests':0})
