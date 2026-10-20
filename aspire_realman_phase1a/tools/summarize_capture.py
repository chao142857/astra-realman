"""Small shareable evidence. Raw images and per-frame logs stay on yanglab."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('report',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
d=json.loads(a.report.read_text());rows=d['samples']
def percentiles(values):return dict(zip(['min','p50','p95','max'],np.percentile(values,[0,50,95,100]).tolist()))
def image_stats(sample):
    parent=Path(sample['assets']['rgb.png']['path']).parent
    z=np.load(parent/'aligned-depth-m.npy',allow_pickle=False)
    crop=z[z.shape[0]//4:z.shape[0]*3//4,z.shape[1]//4:z.shape[1]*3//4]
    return {'central_half_image_valid_fraction':float((crop>0).mean()),
            'central_half_positive_depth_p1_p50_p99_m':np.percentile(crop[crop>0],[1,50,99]).tolist() if np.any(crop>0) else None}
summary={k:v for k,v in d.items() if k not in ['samples','first','last']}
summary.update(raw_report={'path':str(a.report.resolve()),'bytes':a.report.stat().st_size,'sha256':hashlib.sha256(a.report.read_bytes()).hexdigest()},
    evidence_scope='Derived statistics and selected native MCP results; not the complete per-frame/raw asset archive',
    frame_count=len(rows),first_quality=rows[0],last_quality=rows[-1],
    capture_span_s=rows[-1]['received_monotonic_s']-rows[0]['received_monotonic_s'],
    fresh_frame_count=sum(not r['stale'] for r in rows),
    exposed_global_time_verified_count=sum(r['exposure_freshness_verified'] for r in rows),
    invalid_or_unmeasured_robot_state_count=len(rows),
    depth_valid_fraction=percentiles([r['depth_valid_fraction'] for r in rows]),
    oldest_device_frame_or_receipt_age_at_quality_eval_ms=percentiles([r['age_ms'] for r in rows]),
    color_depth_skew_ms=percentiles([r['device_color_depth_skew_ms'] for r in rows]),
    delivered_interval_ms=percentiles(np.diff([r['received_monotonic_s'] for r in rows])*1000),
    device_color_frame_range=[rows[0]['color_frame_number'],rows[-1]['color_frame_number']],
    device_depth_frame_range=[rows[0]['depth_frame_number'],rows[-1]['depth_frame_number']],
    first_assets=d['first'],last_assets=d['last'],first_depth_roi=image_stats(d['first']),last_depth_roi=image_stats(d['last']),
    missing_physical_devices={'left_wrist':'254522073676','overhead':'344422071480','right_wrist':'348522072063'},
    usb_descriptor_serial='027223021284',usb_descriptor_is_not_sdk_calibration_key=True,
    world_localization_accuracy='UNVERIFIED; historical extrinsics not loaded; no metric World result',
    time_limitations='global_time is SDK host-correlated time, not independent exposure synchronization or cross-camera/arm synchronization proof')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(summary,indent=2,allow_nan=False))
print(json.dumps({'output':str(a.output),'bytes':a.output.stat().st_size,'frame_count':len(rows)}))
