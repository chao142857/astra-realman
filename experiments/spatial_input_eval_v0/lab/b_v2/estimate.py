"""Public RGB-D upright-box hypothesis; no GT, simulator, task answers or network."""
import argparse,hashlib,json,math,time,shutil
from pathlib import Path
import numpy as np
from scipy import ndimage
from scipy.spatial.transform import Rotation
from PIL import Image
VERSION='public_rgbd_local_planes.v2'
CONFIG={'inspired_by':'B v1 four-scene GT task audit; these scenes are development-only','pixel_center_offset':.5,'mask_erosion_pixels':1,'depth_neighbor_discontinuity_m':.02,'gray_spread':18,'red_ratio':1.5,'component_voxel_m':.004,'component_connectivity_dilation':1,'minimum_component_points':80,'normal_alignment_degrees':8,'plane_gap_m':.001,'min_plane_points':20,'cell_min_top_points':12,'boundary_support_band_m':.001,'cell_edge_exclusion_m':.001,'floor_exclusion_m':.008,'free_ray_tolerance_pixel_footprint_factor':1.0,'reliability_boundary_clearance_fraction':.5,'geometry_prior':'upright piecewise rectangular solids supported by visible top/side planes; interiors are hypotheses, not directly observed occupancy'}
def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rotation(q):return Rotation.from_quat([q[1],q[2],q[3],q[0]]).as_matrix()
def points(depth,cal):
 v,u=np.indices(depth.shape);k=np.array(cal['intrinsic']);z=depth;off=CONFIG['pixel_center_offset'];local=np.stack([z,-(u+off-k[0,2])*z/k[0,0],-(v+off-k[1,2])*z/k[1,1]],-1);pose=cal['pose_base_xyz_wxyz'];return local@rotation(pose[3:]).T+pose[:3]
def normals(p,depth,camera):
 du=np.roll(p,-1,axis=1)-np.roll(p,1,axis=1);dv=np.roll(p,-1,axis=0)-np.roll(p,1,axis=0);n=np.cross(du,dv);length=np.linalg.norm(n,axis=2);n/=np.maximum(length[:,:,None],1e-12);n*=np.where(np.sum(n*(np.array(camera)-p),axis=2)>0,1,-1)[:,:,None]
 valid=length>1e-10
 for axis in (0,1):
  for sign in (-1,1):valid&=abs(depth-np.roll(depth,sign,axis))<CONFIG['depth_neighbor_discontinuity_m']
 valid[[0,-1],:]=False;valid[:,[0,-1]]=False
 return n,valid

def frame(normal):
 vertical=normal[abs(normal[:,2])<.15]
 if len(vertical)<20:return 0.
 ang=np.arctan2(vertical[:,1],vertical[:,0]);return (np.angle(np.mean(np.exp(4j*ang)))/4)%(math.pi/2)
def matrix(angle):return np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
def patches(p,n,view,pixel):
 result=[];axis=np.argmax(abs(n),axis=1);aligned=np.max(abs(n),axis=1)>math.cos(math.radians(CONFIG['normal_alignment_degrees']))
 for ax in range(3):
  for sign in (-1,1):
   ids=np.flatnonzero(aligned&(axis==ax)&(n[:,ax]*sign>0));ids=ids[np.argsort(p[ids,ax])]
   if not len(ids):continue
   groups=np.split(ids,np.flatnonzero(np.diff(p[ids,ax])>CONFIG['plane_gap_m'])+1)
   for group in groups:
    if len(group)<CONFIG['min_plane_points']:continue
    values=p[group,ax];level=float(np.median(values));residual=np.abs(values-level);views={str(v):{'n':int((view[group]==v).sum()),'median_m':float(np.median(values[view[group]==v]))} for v in np.unique(view[group])};spread=float(np.ptp([v['median_m'] for v in views.values()]))
    result.append({'axis':ax,'sign':sign,'level_m':level,'support_n':len(group),'residual_p95_m':float(np.quantile(residual,.95)),'view_support':views,'view_spread_m':spread,'uncertainty_proxy_m':max(float(np.quantile(residual,.95)),spread/2,float(np.median(pixel[group]))/2),'indices':group})
 return result

def ray_states(query,cameras):
 # A point before an observed surface is FREE; on the depth shell SURFACE;
 # points behind surfaces or outside views remain UNKNOWN (never automatically occupied).
 free=np.zeros(len(query),bool);surface=np.zeros(len(query),bool)
 for cam in cameras:
  cal=cam['cal'];pose=cal['pose_base_xyz_wxyz'];local=(query-pose[:3])@rotation(pose[3:]);z=local[:,0];k=np.array(cal['intrinsic']);u=np.rint(-local[:,1]/np.maximum(z,1e-9)*k[0,0]+k[0,2]-.5).astype(int);v=np.rint(-local[:,2]/np.maximum(z,1e-9)*k[1,1]+k[1,2]-.5).astype(int);h,w=cam['depth'].shape;valid=(z>0)&(u>=0)&(u<w)&(v>=0)&(v<h);idx=np.flatnonzero(valid);d=cam['depth'][v[idx],u[idx]];good=cam['valid'][v[idx],u[idx]]&(d>0);idx=idx[good];d=d[good];tol=np.maximum(d/k[0,0]*CONFIG['free_ray_tolerance_pixel_footprint_factor'],1e-5)
  free[idx]|=z[idx]<d-tol;surface[idx]|=abs(z[idx]-d)<=tol
 return np.where(surface,1,np.where(free,0,2))

def target_box(p,n,v,pixel):
 angle=frame(n);rot=matrix(angle);local=p@rot;ns=n@rot;patch=patches(local,ns,v,pixel);bounds=[];notes=[]
 for ax in range(3):
  bb=[]
  for sign in (-1,1):
   choices=[x for x in patch if x['axis']==ax and x['sign']==sign]
   if choices:bb.append(max(choices,key=lambda x:x['support_n'])['level_m'])
   else:bb.append(float(local[:,ax].min() if sign<0 else local[:,ax].max()));notes.append({'axis':ax,'side':sign,'status':'UNKNOWN_BEYOND_VISIBLE_EXTENT; no hidden face filled'})
  bounds.append(bb)
 lo,hi=np.array(bounds).T
 if np.any(hi<=lo):return None,{'failure':'nonpositive target size'},patch
 box={'id':'target','center_m':(((lo+hi)/2)@rot.T).tolist(),'size_m':(hi-lo).tolist(),'quaternion_wxyz':[math.cos(angle/2),0,0,math.sin(angle/2)]}
 return box,{'angle_rad':angle,'missing_faces':notes,'status':'observed-plane-supported box hypothesis; unknown faces are truncated to visible extent'},patch

def estimate(folder,out):
 t=time.perf_counter();out.mkdir(parents=True,exist_ok=False);ctx=read(folder/'context.json');assert ctx['geometry'] is None
 red=[];gray=[];cameras=[];view_qa=[]
 for i,a in enumerate(ctx['attachments']):
  rgb=np.array(Image.open(folder/f'image-{i}.png').convert('RGB'),float);depth=np.load(folder/f'depth-{i}.npy');valid=np.load(folder/f'valid-{i}.npy').astype(bool)&np.isfinite(depth)&(depth>.01)&(depth<5);cal=ctx['observations']['calibration'][a['camera_id']];p=points(depth,cal);n,nvalid=normals(p,depth,cal['pose_base_xyz_wxyz'][:3]);valid&=nvalid
  rm=(rgb[:,:,0]>70)&(rgb[:,:,0]>CONFIG['red_ratio']*rgb[:,:,1])&(rgb[:,:,0]>CONFIG['red_ratio']*rgb[:,:,2]);gm=(np.ptp(rgb,axis=2)<CONFIG['gray_spread'])&(rgb.min(2)>30)
  masks=[ndimage.binary_erosion(x,iterations=CONFIG['mask_erosion_pixels'])&valid for x in (rm,gm)]
  for mask,dst in zip(masks,[red,gray]):
   dst.append((p[mask],n[mask],np.full(mask.sum(),i),depth[mask]/cal['intrinsic'][0][0]))
  cameras.append({'depth':depth,'valid':valid,'cal':cal});view_qa.append({'camera_id':a['camera_id'],'red_points':int(masks[0].sum()),'neutral_points':int(masks[1].sum())})
 rp,rn,rv,rpx=[np.concatenate([x[j] for x in red]) for j in range(4)];gp,gn,gv,gpx=[np.concatenate([x[j] for x in gray]) for j in range(4)]
 missing=[];objects=[];reliability=[]
 if len(rp)>=80:
  box,info,patch=target_box(rp,rn,rv,rpx)
  if box:objects=[box]
  reliability.append({'id':'target','overall_solid_reliability':'INSUFFICIENT' if info.get('missing_faces') else 'SUPPORTED_NOT_CERTIFIED','critical_boundary_reliability':'INSUFFICIENT' if info.get('missing_faces') or any(len(x['view_support'])<2 or x['uncertainty_proxy_m']>=ctx['task']['constraints']['clearance_m']/2 for x in patch) else 'SUPPORTED_NOT_CERTIFIED','details':info,'planes':[{k:v for k,v in x.items() if k!='indices'} for x in patch]})
 else:missing.append('target: insufficient RGB/depth support')
 # Dominant observed horizontal plane only removes background; never an extrusion bottom.
 horizontal=gp[np.abs(gn[:,2])>.95];zbin=np.round(horizontal[:,2]/.002).astype(int);levels,count=np.unique(zbin,return_counts=True);floor=float(np.median(horizontal[zbin==levels[count.argmax()],2]));keep=gp[:,2]>floor+CONFIG['floor_exclusion_m'];gp,gn,gv,gpx=gp[keep],gn[keep],gv[keep],gpx[keep]
 step=CONFIG['component_voxel_m'];origin=gp.min(0)-2*step;indices=np.floor((gp-origin)/step).astype(int);shape=tuple(indices.max(0)+3);voxel=np.zeros(shape,bool);voxel[tuple(indices.T)]=True;labels,num=ndimage.label(ndimage.binary_dilation(voxel,iterations=CONFIG['component_connectivity_dilation']));label=labels[tuple(indices.T)];obstacles=[];component_log=[];rejected=[]
 for group in np.unique(label):
  mask=label==group
  if mask.sum()<CONFIG['minimum_component_points']:continue
  wp,wn,wv,wpx=gp[mask],gn[mask],gv[mask],gpx[mask];angle=frame(wn);rot=matrix(angle);p=wp@rot;n=wn@rot;patch=patches(p,n,wv,wpx)
  xy=[]
  for ax in (0,1):
   values=sorted(x['level_m'] for x in patch if x['axis']==ax)
   # Merge nearly coincident +/- faces only for arrangement boundaries, never snap to a grid.
   unique=[]
   for value in values:
    if not unique or value-unique[-1]>.0002:unique.append(value)
   if len(unique)<2:unique=[float(p[:,ax].min()),float(p[:,ax].max())];missing.append(f'component {int(group)} axis {ax}: no opposing fitted boundary pair')
   xy.append(unique)
  comp={'component':int(group),'points':int(mask.sum()),'angle_rad':angle,'planes':[{k:v for k,v in x.items() if k!='indices'} for x in patch]};component_log.append(comp)
  for ix in range(len(xy[0])-1):
   for iy in range(len(xy[1])-1):
    low=np.array([xy[0][ix],xy[1][iy]]);high=np.array([xy[0][ix+1],xy[1][iy+1]]);margin=min(CONFIG['cell_edge_exclusion_m'],float((high-low).min())/4)
    inside=((p[:,:2]>low+margin)&(p[:,:2]<high-margin)).all(1);top=inside&(n[:,2]>.98)
    if top.sum()<CONFIG['cell_min_top_points']:continue
    zhi=float(np.median(p[top,2]));support=[];supported=[]
    for ax in (0,1):
     other=1-ax
     for sign,bound in [(-1,low[ax]),(1,high[ax])]:
      eligible=[f for f in patch if f['axis']==ax and f['sign']==sign and abs(f['level_m']-bound)<CONFIG['boundary_support_band_m']]
      for face in eligible:
       ids=face['indices'];ids=ids[(p[ids,other]>low[other]+margin)&(p[ids,other]<high[other]-margin)]
       if len(ids)>=CONFIG['min_plane_points']:support.extend(ids.tolist());supported.append(face)
    if not support:rejected.append({'component':int(group),'xy_low':low.tolist(),'xy_high':high.tolist(),'reason':'UNKNOWN_BOTTOM_AND_SIDE_SUPPORT; no solid created'});continue
    zlo=float(p[support,2].min())
    if zhi-zlo<.001:continue
    # Ray-free contradiction rejects the proposed solid; do not silently hallucinate occupancy.
    sample=np.array([[low[0]+u*(high[0]-low[0]),low[1]+v*(high[1]-low[1]),zlo+w*(zhi-zlo)] for u in (.2,.5,.8) for v in (.2,.5,.8) for w in (.2,.5,.8)])@rot.T;states=ray_states(sample,cameras)
    if (states==0).any():rejected.append({'component':int(group),'xy_low':low.tolist(),'xy_high':high.tolist(),'reason':'OBSERVED_FREE_SPACE_CONTRADICTS_EXTRUSION','free_probes':int((states==0).sum())});continue
    identity=f'observed_obstacle_{len(obstacles):03d}';center=np.array([*((low+high)/2),(zlo+zhi)/2])@rot.T
    obstacles.append({'id':identity,'center_m':center.tolist(),'size_m':[*(high-low),zhi-zlo],'quaternion_wxyz':[math.cos(angle/2),0,0,math.sin(angle/2)]})
    uncertainty=max(x['uncertainty_proxy_m'] for x in supported);multiview=all(len(x['view_support'])>=2 for x in supported);clearance=ctx['task']['constraints']['clearance_m']
    reliability.append({'id':identity,'component':int(group),'top_support_n':int(top.sum()),'side_support_n':len(set(support)),'observed_z_extent_m':[zlo,zhi],'overall_solid_reliability':'INSUFFICIENT_UNOBSERVED_BOTTOM','bottom_status':'UNKNOWN_BELOW_OBSERVED_SIDE_EXTENT; no GT completion','interior_status':'UNKNOWN_OCCLUSION + upright-solid prior; not directly observed solid','ray_probe_states':{'surface':int((states==1).sum()),'free':int((states==0).sum()),'unknown':int((states==2).sum())},'boundary_uncertainty_proxy_m':uncertainty,'all_supported_faces_multiview':multiview,'critical_boundary_reliability':'INSUFFICIENT' if not multiview or uncertainty>=clearance*CONFIG['reliability_boundary_clearance_fraction'] else 'SUPPORTED_NOT_CERTIFIED','uncertainty_note':'proxy, not a calibrated probability or bound; grid size is NOT accuracy'})
 geometry={'source':'RECONSTRUCTION','frame':'robot_base','units':'m','objects':objects,'regions':[],'obstacles':obstacles,'renderings':[]}
 build_s=time.perf_counter()-t;write(out/'geometry.json',geometry);write(out/'reliability.json',{'version':VERSION,'config':CONFIG,'views':view_qa,'objects':reliability,'components':component_log,'unknown_or_rejected':rejected,'missing':missing,'estimated_floor_m':floor,'segmentation_used':False,'states':{'OBSERVED_SURFACE':'measured depth shell','OBSERVED_FREE':'point in front of measured surface by depth/pixel tolerance','UNKNOWN':'occluded/unseen/unsupported; solid box interiors remain explicit hypotheses'}})
 prep=time.perf_counter();ctx['geometry']=geometry;write(out/'context.json',ctx)
 for i in range(3):shutil.copyfile(folder/f'image-{i}.png',out/f'image-{i}.png')
 write(out/'timing.json',{'geometry_estimation_s':build_s,'input_preparation_s':time.perf_counter()-prep,'total_s':time.perf_counter()-t,'boxes':len(objects)+len(obstacles),'context_bytes':(out/'context.json').stat().st_size,'geometry_bytes':(out/'geometry.json').stat().st_size})
 return geometry
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--public',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 for x in read(a.public/'manifest.json')['files']:assert sha(a.public/x['file'])==x['sha256']
 for folder in sorted(x for x in a.public.iterdir() if x.is_dir()):
  g=estimate(folder,a.output/folder.name);print(folder.name,len(g['objects']),len(g['obstacles']),flush=True)
 write(a.output/'freeze.json',{'version':VERSION,'estimator_sha256':sha(__file__),'config':CONFIG,'files':[{'file':str(x.relative_to(a.output)),'sha256':sha(x)} for x in sorted(a.output.rglob('*')) if x.is_file()],'generation_requests':0})
