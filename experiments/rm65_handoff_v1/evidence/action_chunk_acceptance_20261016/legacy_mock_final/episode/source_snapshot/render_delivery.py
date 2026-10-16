"""Presentation only: juxtapose user reference and actual rendered captures. Never model input."""
import argparse,json,shutil
from pathlib import Path
from PIL import Image,ImageDraw
p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);a=p.parse_args();d=Path(__file__).parent;src=d/'evidence/numeric_baseline_01/initial_observation';out=d/'evidence/layout_delivery';out.mkdir(exist_ok=True)
ref=Image.open(a.reference).convert('RGB');preview=Image.open(src/'scene_preview_NOT_MODEL_INPUT.png').convert('RGB');ref.thumbnail((960,600));preview.thumbnail((960,600));canvas=Image.new('RGB',(1920,650),'white');canvas.paste(ref,((960-ref.width)//2,40));canvas.paste(preview,(960+(960-preview.width)//2,40));draw=ImageDraw.Draw(canvas);draw.text((20,15),'Laboratory reference: approximate arrangement, NOT metric calibration',fill='black');draw.text((980,15),'Actual SAPIEN render: shared scene / two RM65+CTAG',fill='black');canvas.save(out/'layout_comparison_NOT_MODEL_INPUT.png')
shutil.copy2(a.reference,out/'lab_reference_NOT_MODEL_INPUT.jpg')
for name in ['overhead','tabletop_front','left_wrist','right_wrist']:shutil.copy2(src/(name+'.png'),out/(name+'.png'))
for name in ['four_views.png','scene_preview_NOT_MODEL_INPUT.png','observation.json']:shutil.copy2(src/name,out/name)
(out/'provenance.json').write_text(json.dumps({'raw_capture_source':str(src),'presentation_only':True,'model_input_reference_photo':False,'differences':'0.72m engineering base spacing; simplified bare table/marker/cube; no monitor, cables, laptop or exact camera mounting asset; photograph is not calibrated.'},indent=2))
