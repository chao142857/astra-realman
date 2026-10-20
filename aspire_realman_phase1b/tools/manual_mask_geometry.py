"""Real image hand annotation -> visible optical cloud -> native ASPIRE PCA OBB.
Pipeline validation only. No SAM3 score, RobotState, World transform or hardware.
"""
import argparse,json,sys
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from rgbd_evidence import *
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot',type=Path,required=True)
p.add_argument('--annotation',type=Path,required=True);p.add_argument('--aspire-source',type=Path,required=True)
p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.resolve().relative_to(Path(__file__).resolve().parents[2]);a.output.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(a.aspire_source/'src'))
rgb,z,meta,prov=load_snapshot(a.snapshot);annotation=json.loads(a.annotation.read_text())
if annotation['rgb_sha256']!=prov['rgb_sha256'] or annotation['mask_source']!='MANUAL_VISUAL_POLYGON_NOT_SAM3':raise ValueError('MANUAL_ANNOTATION_PROVENANCE_MISMATCH')
mask_image=Image.new('L',(rgb.shape[1],rgb.shape[0]),0);ImageDraw.Draw(mask_image).polygon([tuple(p) for p in annotation['polygon_xy_pixels']],fill=255)
mask_image.save(a.output/'manual-mask.png');mask=np.asarray(mask_image)>0
geometry=mask_geometry(rgb,z,meta,mask,a.output,'manual-banana')
points,v,u=camera_points(z,np.array(meta['intrinsics']),mask);k=np.array(meta['intrinsics'])
projected=np.column_stack((points[:,0]/points[:,2]*k[0,0]+k[0,2],points[:,1]/points[:,2]*k[1,1]+k[1,2]))
error=float(np.max(np.abs(projected-np.column_stack((u,v))))) if len(points) else None
obb=geometry['obb'];checks={'deprojection_reprojection_max_error_px':error,'roundtrip_is_not_external_accuracy_test':True,'all_points_positive_optical_z':bool(np.all(points[:,2]>0)),'axes':'+X right, +Y down, +Z forward','alignment':meta['alignment']}
if obb:
 from cap_harness.geometry import quaternion_wxyz_to_matrix
 rotation=quaternion_wxyz_to_matrix(obb['quaternion_wxyz']);local=(points-np.array(obb['center_m']))@rotation
 checks.update(obb_rotation_determinant=float(np.linalg.det(rotation)),obb_encloses_all_valid_points=bool(np.all(np.abs(local)<=np.array(obb['extents_m'])/2+1e-8)))
 assert checks['obb_encloses_all_valid_points'] and error<1e-8
blend=rgb.copy();blend[mask]=(rgb[mask]*.55+np.array([255,40,180])*.45).astype(np.uint8)
valid=mask&np.isfinite(z)&(z>0);within=np.zeros_like(rgb);within[valid]=rgb[valid]
canvas=Image.new('RGB',(1280,580),'#eeeeee');canvas.paste(Image.fromarray(blend),(0,40));canvas.paste(Image.fromarray(within),(640,40))
d=ImageDraw.Draw(canvas);font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
d.text((8,10),'MANUAL visual polygon; NOT SAM3 / not ground truth',font=font,fill='black')
d.text((648,10),'Same manual Mask AND sensor-valid depth pixels',font=font,fill='black')
d.text((8,532),f'Manual mask pixels={int(mask.sum())}; valid={geometry["valid_fraction"]:.1%}; camera frame only; no World/TCP.',font=font,fill='black')
d.text((8,555),'All positive depth returns retained, including distant samples; OBB describes visible returns, not certified object size.',font=font,fill='black')
canvas.save(a.output/'manual-mask-geometry-preview.jpg',quality=90)
# Simple orthographic X/Z point plot; all points used for OBB, stride only in plot.
plot=Image.new('RGB',(800,580),'white');pd=ImageDraw.Draw(plot);xyz=points[::max(1,len(points)//4000)]
lo=points[:,[0,2]].min(0);hi=points[:,[0,2]].max(0);span=np.maximum(hi-lo,.001)
for pt in xyz:
 x,zv=pt[[0,2]];px=60+(x-lo[0])/span[0]*680;py=70+(zv-lo[1])/span[1]*430
 pd.ellipse((px-1,py-1,px+1,py+1),fill='#204090')
pd.rectangle((60,70,740,500),outline='black');pd.text((60,12),'Manual-mask visible cloud: camera X vs Z (m)',font=font,fill='black')
pd.text((60,525),f'X [{lo[0]:.3f},{hi[0]:.3f}] m; Z [{lo[1]:.3f},{hi[1]:.3f}] m (increases downward)',font=font,fill='black')
plot.save(a.output/'manual-cloud-xz-preview.png')
result={'status':'MANUAL_MASK_PIPELINE_VALIDATED_NOT_SAM3_BASELINE','provenance':prov,'annotation':annotation,
 'annotation_file':artifact(a.annotation),'mask':artifact(a.output/'manual-mask.png'),'geometry':geometry,
 'coordinate_checks':checks,'sam3_inference_completed':False,'world_pose':None,'robot_state':None,
 'geometry_accuracy_qualified':False,'objects_depth_ground_truth':None,
 'visualizations':{f.name:artifact(f) for f in a.output.glob('*preview*')}}
(a.output/'manual_geometry_report.json').write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps(result,indent=2))
