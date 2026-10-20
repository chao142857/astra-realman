"""Compact derived visual for inspection; original RGB-D remains sealed."""
import argparse,json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();out=a.directory
report=json.loads((out/'depth_report.json').read_text());font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',15)
canvas=Image.new('RGB',(1280,580),'#eeeeee');d=ImageDraw.Draw(canvas)
canvas.paste(Image.open(out/'manual-inspection-rois.png'),(0,40));canvas.paste(Image.open(out/'depth-1p5-to-2p3m-overlay.png'),(640,40))
d.text((8,10),'Manual RGB regions for diagnosis; NOT SAM3 masks',font=font,fill='black')
d.text((648,10),'Yellow pixels: actual aligned Z in [1.5, 2.3)m',font=font,fill='black')
d.text((8,530),'Central ROI median Z=1.957m; 88.8% of valid central samples are in [1.5,2.3)m.',font=font,fill='black')
d.text((8,553),'Table region valid=3.2%; screen region valid=90.4%; banana neighborhood median=0.495m (ROI only).',font=font,fill='black')
canvas.save(out/'depth-spatial-evidence-preview.jpg',quality=88)
