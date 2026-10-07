"""Input-only image provenance and lossless history plumbing, not new E2/E3 arms."""
import copy
import hashlib
import json
import time
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def pack_history(history):
    from e3_history_screen import pack
    return pack(history)


def unpack_history(value):
    from e3_history_screen import unpack
    return unpack(value)


def history_projection(history, *, mode='raw', budget_bytes=65536):
    start = time.monotonic()
    if mode not in ('raw', 'lossless') or budget_bytes <= 0:raise ValueError('HISTORY_PROJECTION_OPTIONS')
    raw = canonical(history)
    packed = pack_history(history)
    if canonical(unpack_history(packed)) != raw:raise ValueError('ROUND_TRIP_FAILED')
    compact = canonical(packed)
    useful = len(compact.encode()) < len(raw.encode()) and len(compact.encode()) <= budget_bytes
    use_compact = mode == 'lossless' and useful
    selected = packed if use_compact else copy.deepcopy(history)
    pointers = []
    def visit(v, path=''):
        if isinstance(v, dict):
            for k, item in v.items():visit(item, path+'/'+k.replace('~','~0').replace('/','~1'))
        elif isinstance(v, list):
            for i, item in enumerate(v):visit(item,path+'/'+str(i))
        else:pointers.append(path)
    visit(history)
    meta = {'requested_mode': mode, 'actual_mode': 'lossless' if use_compact else 'raw',
            'fallback': 'NOT_SMALLER_OR_BUDGET' if mode == 'lossless' and not useful else None,
            'raw_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'raw_bytes': len(raw.encode()), 'packed_bytes': len(compact.encode()),
            'selected_bytes': len(canonical(selected).encode()), 'budget_bytes': budget_bytes,
            'eligible': len(canonical(selected).encode()) <= budget_bytes,
            'round_trip_exact': True, 'retained_pointers': pointers, 'deleted_pointers': [],
            'projection_wall_time_s': time.monotonic()-start,
            'scope': 'transport codec only; no T2/T3 selection or semantic summary'}
    return selected, meta


def image_projection(images, output, *, cameras=('assembly','fixed','wrist'), resize=None,
                     roi=None, online_phase=None):
    """ROI must arrive with explicit online provenance; this function has no evaluator."""
    from PIL import Image
    start = time.monotonic()
    if not cameras or len(set(cameras)) != len(cameras) or any(c not in images for c in cameras):
        raise ValueError('CAMERA_SELECTION')
    if resize is not None and (len(resize) != 2 or any(type(x) is not int or not 1 <= x <= 640 for x in resize)):
        raise ValueError('RESIZE_RANGE')
    if roi is not None and (roi.get('source') not in ('online_detector','human_current_image') or
                            not roi.get('observation_id') or not roi.get('evidence_ref')):
        raise ValueError('ONLINE_ROI_EVIDENCE_REQUIRED')
    out = Path(output); out.mkdir(parents=True, exist_ok=False)
    records = []
    for index, camera in enumerate(cameras):
        parent = Path(images[camera]); data = parent.read_bytes()
        with Image.open(parent) as img:
            img.load()
            if img.format != 'PNG':raise ValueError('PNG_REQUIRED')
            original_size = list(img.size)
            box = None
            if roi is not None and camera == roi.get('camera'):
                box = roi['xyxy']
                if len(box) != 4 or any(type(x) is not int for x in box) or not (0 <= box[0] < box[2] <= img.width and 0 <= box[1] < box[3] <= img.height):
                    raise ValueError('ROI_BOUNDS')
                img = img.crop(box)
            if resize is not None:img = img.resize(resize, Image.Resampling.LANCZOS)
            dest = out / ('image-%d.png' % index)
            if box is None and resize is None:dest.write_bytes(data)
            else:img.convert('RGB').save(dest)
            records.append({'input_index': index+1, 'camera':camera, 'file':str(dest),
                'parent_sha256':hashlib.sha256(data).hexdigest(),
                'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
                'parent_size':original_size, 'size':list(img.size), 'roi_xyxy':box,
                'roi_provenance':copy.deepcopy(roi) if box else None, 'resize':resize,
                'online_phase':online_phase, 'temporal_role':'current'})
    return records, {'projection_wall_time_s':time.monotonic()-start, 'attachment_count':len(records)}
