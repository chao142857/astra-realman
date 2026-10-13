#!/usr/bin/env python3
"""Contact sheet of actual simulator captures, for human inspection only."""
import argparse
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw
from spatial_eval.schema import write


def main():
    p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();assert not a.output.exists()
    paths=sorted(a.suite.glob('*/assets/front.png'));assert len(paths)==6
    sheet=Image.new('RGB',(720,900),'white');draw=ImageDraw.Draw(sheet)
    for i,path in enumerate(paths):
        x=i%2*360;y=i//2*300
        with Image.open(path) as im:sheet.paste(im.resize((360,270)),(x,y+30))
        draw.text((x+8,y+8),path.parent.parent.name,fill='black')
    sheet.save(a.output)
    write(a.output.with_suffix('.json'),{'source':'CONTACT_SHEET_OF_ACTUAL_SAPIEN_RGB','model_calls':0,
                                        'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})


if __name__=='__main__':main()
