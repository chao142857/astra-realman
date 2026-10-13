"""Project frozen estimated boxes onto their original public RGB; no GT access."""
import argparse,json,itertools
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from scipy.spatial.transform import Rotation
from spatial_eval.geometry import corners
p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
for folder in sorted(x for x in a.inputs.iterdir() if x.is_dir()):
 context=json.loads((folder/'context.json').read_text());canvas=Image.new('RGB',(1440,390),'white')
 for i,attachment in enumerate(context['attachments']):
  im=Image.open(folder/f'image-{i}.png').convert('RGB');draw=ImageDraw.Draw(im);cal=context['observations']['calibration'][attachment['camera_id']];pose=cal['pose_base_xyz_wxyz'];q=pose[3:];rot=Rotation.from_quat([q[1],q[2],q[3],q[0]]).as_matrix();k=np.array(cal['intrinsic'])
  for boxes,color in [(context['geometry']['obstacles'],'#2255ff'),(context['geometry']['objects'],'#ffee00')]:
   for box in boxes:
    points=(np.array(corners(box))-pose[:3])@rot;z=points[:,0]
    if (z<=0).any():continue
    uv=np.stack([-points[:,1]/z*k[0,0]+k[0,2],-points[:,2]/z*k[1,1]+k[1,2]],1)
    for x,y in itertools.combinations(range(8),2):
     if (x^y) in (1,2,4):draw.line([tuple(uv[x]),tuple(uv[y])],fill=color,width=2)
  canvas.paste(im.resize((480,360)),(480*i,30))
 ImageDraw.Draw(canvas).text((10,8),folder.name+' | yellow=estimated target; blue=estimated obstacles; NO GT',fill='black');canvas.save(a.output/f'{folder.name}_rgb_overlay.png')
