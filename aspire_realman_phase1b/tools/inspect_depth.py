"""Actual sealed RGB-D inspection; ROIs/bands are diagnostics, never object masks."""
import argparse,json
from pathlib import Path
import numpy as np
from rgbd_evidence import *
p=argparse.ArgumentParser();p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.resolve().relative_to(Path(__file__).resolve().parents[2]);a.output.mkdir(parents=True,exist_ok=False)
rgb,z,meta,provenance=load_snapshot(a.snapshot);comparison(rgb,z,a.output)
regions={'whole_frame':[0,0,640,480],'central_roi':[160,120,480,360],
 'visually_selected_banana_neighborhood_NOT_SEGMENTATION':[75,245,260,290],
 'visually_selected_table_surface':[200,320,480,470],
 'visually_selected_background_screen':[280,80,480,230],
 'visually_selected_partial_blue_bowl_neighborhood':[500,245,640,290]}
regions.update({f'grid_row{r}_col{c}':[c*160,r*160,(c+1)*160,(r+1)*160] for r in range(3) for c in range(4)})
result={'status':'REAL_DEPTH_DIAGNOSTICS_ONLY','provenance':provenance,
 'regions':{n:{'xyxy':box,**stats(z,rectangle(z.shape,box))} for n,box in regions.items()},
 'sam3_segmentation_available':False,'target_geometry':None,'world_localization_qualified':False,
 'note':'Depth scale/registration consistency and distributions do not establish physical range or object identity.'}
points,v,u=camera_points(z,np.array(meta['intrinsics']),np.ones(z.shape,bool));write_cloud(a.output/'scene-visible-camera.ply',points,rgb[v,u])

from PIL import Image,ImageDraw,ImageFont
marked=Image.fromarray(rgb);draw=ImageDraw.Draw(marked);font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
for name,color in [('visually_selected_banana_neighborhood_NOT_SEGMENTATION','yellow'),('visually_selected_table_surface','cyan'),('visually_selected_background_screen','magenta')]:
 box=regions[name];draw.rectangle((box[0],box[1],box[2]-1,box[3]-1),outline=color,width=2);draw.text((box[0],box[1]-17),name.replace('visually_selected_','').replace('_NOT_SEGMENTATION',' ROI only'),fill=color,font=font)
marked.save(a.output/'manual-inspection-rois.png')
result['scene_cloud']=artifact(a.output/'scene-visible-camera.ply')
result['visualizations']={f.name:artifact(f) for f in a.output.glob('*.png')}
result['preview']=artifact(a.output/'rgb-depth-validity-preview.jpg')
(a.output/'depth_report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
