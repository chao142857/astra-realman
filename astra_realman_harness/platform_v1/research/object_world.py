"""Training-free, bounded silhouette occupancy. No depth, model, or simulator imports.

A visual hull is POSSIBLE occupancy, not an object center, surface reconstruction,
amodal mask, or collision certificate. Only complete observed silhouettes carve.
Occluded/unassociated views never declare free space. Task admission stays unknown.
"""
import time
import cv2
import numpy as np
from .contracts import clone, digest
from .da3_geometry import calibrated_cameras, CAMERAS

BACKEND = 'object_silhouette_world_v1'


def encode_mask(mask):
    x = np.asarray(mask, bool).ravel().astype(np.int8)
    edges = np.flatnonzero(np.diff(np.r_[0, x, 0]))
    return {'shape': list(mask.shape), 'runs': edges.reshape(-1, 2).tolist()}


def decode_mask(record):
    h, w = record['shape']
    if not 0 < h * w <= 4096 * 4096:
        raise ValueError('MASK_SHAPE')
    out = np.zeros(h * w, np.uint8)
    last = 0
    for a, b in record['runs']:
        if not last <= a < b <= h * w:
            raise ValueError('MASK_RUNS')
        out[a:b] = 1
        last = b
    return out.reshape(h, w)


def project(points, ext, k):
    p = np.asarray(points).reshape(-1, 3) @ ext[:3, :3].T + ext[:3, 3]
    uvw = p @ k.T
    return uvw[:, :2] / np.maximum(uvw[:, 2:], 1e-10), p[:, 2]


def occupancy_points(occupancy):
    return np.asarray(occupancy['origin_m']) + (np.asarray(occupancy['indices'], float) + .5) * occupancy['voxel_m']


def render_support(occupancy, ext, k, shape):
    """Union of projected voxel cubes (not a smoothed point-center mask)."""
    out = np.zeros(shape, np.uint8)
    if not occupancy or not occupancy['indices']:
        return out
    points = occupancy_points(occupancy)
    corners = np.array([[a, b, c] for a in [-1, 1] for b in [-1, 1] for c in [-1, 1]])
    uv, z = project((points[:, None] + corners * occupancy['voxel_m'] / 2).reshape(-1, 3), ext, k)
    uv = uv.reshape(-1, 8, 2)
    z = z.reshape(-1, 8)
    h, w = shape
    for pixels, depth in zip(uv, z):
        if np.any(depth <= 1e-5) or not np.isfinite(pixels).all():
            continue
        if pixels[:, 0].max() < 0 or pixels[:, 0].min() >= w or pixels[:, 1].max() < 0 or pixels[:, 1].min() >= h:
            continue
        poly = cv2.convexHull(np.rint(np.clip(pixels, -10000, 10000)).astype(np.int32))
        cv2.fillConvexPoly(out, poly, 1)
    return out


def mask_quality(mask, cfg):
    if mask.sum() < cfg['min_mask_pixels']:
        return 'INSUFFICIENT_MASK_SUPPORT'
    ys, xs = np.where(mask)
    if min(xs.min(), ys.min()) <= 1 or xs.max() >= mask.shape[1]-2 or ys.max() >= mask.shape[0]-2:
        return 'CLIPPED_SILHOUETTE'
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    areas = sorted(stats[1:, cv2.CC_STAT_AREA], reverse=True)
    if n > 2 and areas[1] >= cfg['max_mask_component_ratio'] * areas[0]:
        return 'AMBIGUOUS_MASK_COMPONENTS'
    return None


def carve(views, observation, cfg, kind, plane):
    ext, k = calibrated_cameras(observation)
    low = np.array(cfg['domain_min_m'], float); high = np.array(cfg['domain_max_m'], float)
    step = float(cfg['voxel_m'])
    if step < .002 or np.any(high <= low) or not np.isfinite([*low, *high, step]).all():
        raise ValueError('BOUNDED_GRID_REQUIRED')
    # First version explicitly supports the public horizontal table; never silently
    # reinterprets an arbitrary plane as z=0.
    if not np.allclose(plane['normal'], [0, 0, 1]) or abs(plane['offset']) > 1e-9:
        raise ValueError('UNSUPPORTED_PUBLIC_PLANE')
    if kind == 'region':
        low[2] = -step/2
        high[2] = low[2] + step
    dims = np.ceil((high-low) / step).astype(int)
    if np.prod(dims) > 10_000_000:
        raise ValueError('GRID_MEMORY_BUDGET')
    full = [v for v in views if v['carving_allowed']]
    diag = {'constraining_views': [v['camera'] for v in full], 'rejected_views':
            {v['camera']: v['reason'] for v in views if not v['carving_allowed']},
            'candidate_grid_cells': int(np.prod(dims))}
    if len(full) < cfg['min_views']:
        return None, 'INSUFFICIENT_COMPLETE_SILHOUETTES', diag
    centers = [np.linalg.inv(ext[CAMERAS.index(v['camera'])])[:3, 3] for v in full]
    baseline = max(np.linalg.norm(a-b) for a in centers for b in centers)
    diag['max_baseline_m'] = float(baseline)
    if baseline < cfg['min_baseline_m']:
        return None, 'INSUFFICIENT_BASELINE', diag
    masks = []
    for v in full:
        m = decode_mask(v['mask']); d = cfg['mask_margin_px']
        masks.append(cv2.dilate(m, np.ones((2*d+1, 2*d+1), np.uint8)))
    kept = []
    # Bound peak memory independently of workspace size.
    for start in range(0, int(np.prod(dims)), 65536):
        ids = np.arange(start, min(start+65536, int(np.prod(dims))))
        index = np.array(np.unravel_index(ids, dims)).T
        xyz = low + (index+.5)*step
        if kind == 'region': xyz[:, 2] = -plane['offset']
        good = np.ones(len(xyz), bool)
        for v, m in zip(full, masks):
            i = CAMERAS.index(v['camera']); uv, depth = project(xyz, ext[i], k[i])
            pix = np.rint(uv).astype(int); h, w = m.shape
            inside = (depth > 0) & (pix[:, 0] >= 0) & (pix[:, 0] < w) & (pix[:, 1] >= 0) & (pix[:, 1] < h)
            support = np.zeros(len(xyz), bool)
            support[inside] = m[pix[inside, 1], pix[inside, 0]] > 0
            good &= support
        if good.any(): kept.append(index[good])
    if not kept:
        return None, 'EMPTY_INTERSECTION_MASK_OR_ASSOCIATION_CONFLICT', diag
    index = np.concatenate(kept)
    points = low + (index+.5)*step
    lo = points.min(0)-step/2; hi = points.max(0)+step/2
    extent = hi-lo
    diag.update(possible_voxels=len(index), extent_m=extent.tolist())
    # Search-volume clipping is missing information, not an estimated boundary.
    axes = [0, 1] if kind == 'region' else [0, 1, 2]
    touches = any(index[:, a].max() >= dims[a]-1 or (a != 2 and index[:, a].min() == 0) for a in axes)
    if touches or max(extent) > cfg['max_extent_m']:
        return None, 'UNBOUNDED_OR_TOO_BROAD_OCCUPANCY', diag
    rays = [(points.mean(0)-c)/np.linalg.norm(points.mean(0)-c) for c in centers]
    angle = max(np.degrees(np.arccos(np.clip(a@b, -1, 1))) for a in rays for b in rays)
    diag['max_ray_angle_deg'] = float(angle)
    if angle < cfg['min_ray_angle_deg']:
        return None, 'INSUFFICIENT_RAY_ANGLE', diag
    occupancy = {'origin_m': low.tolist(), 'voxel_m': step, 'indices': index.tolist(),
        'semantics': 'POSSIBLE_OCCUPANCY_NOT_OCCUPIED_CERTAINTY', 'domain_min_m': low.tolist(),
        'domain_max_m': high.tolist(), 'outside_domain': 'unknown',
        'bounds_world_m': [lo.tolist(), hi.tolist()], 'plane_constraint': clone(plane),
        'plane_support_status': 'supported' if lo[2] <= step+cfg['plane_uncertainty_m'] else 'unknown'}
    diag['build_reprojection'] = {}
    for v in full:
        i = CAMERAS.index(v['camera']); mask = decode_mask(v['mask'])
        projected = render_support(occupancy, ext[i], k[i], mask.shape)
        inter = int((projected & mask).sum())
        recall = inter / max(1, int(mask.sum()))
        diag['build_reprojection'][v['camera']] = {'recall': recall,
            'precision': inter/max(1, int(projected.sum())), 'iou': inter/max(1, int((projected | mask).sum()))}
        if recall < cfg['min_reprojection_recall']:
            return None, 'SILHOUETTES_NOT_MUTUALLY_EXPLAINED', diag
    return occupancy, 'COARSE_SILHOUETTE_CONSTRAINT', diag


def build(observation, entities, masks, cfg, public_plane, semantic_source):
    start = time.monotonic()
    if any(c.get('axes') != 'SAPIEN +x forward,+y left,+z up' for c in observation['calibration'].values()):
        raise ValueError('UNSUPPORTED_CAMERA_AXES')
    if observation['capture_span_s'] > cfg['max_capture_span_s']:
        raise ValueError('UNSYNCHRONIZED_BUILD')
    if not semantic_source or not entities:
        raise ValueError('INSTANCE_PROVENANCE_REQUIRED')
    if len({e['entity_id'] for e in entities}) != len(entities):
        raise ValueError('DUPLICATE_INSTANCE_ID')
    state = {'backend': BACKEND, 'observation_id': observation['observation_id'],
        'captured_monotonic': observation['captured_monotonic'], 'robot_state': clone(observation['state']),
        'entities': {}, 'geometry_only': False, 'task_identity_verified': False,
        'scene_healthy': True, 'semantic_source': semantic_source, 'history_semantics': 'build_current_silhouette_constraints',
        'geometry_quality': {'numeric_valid': 'unknown', 'self_consistent': 'unknown', 'task_usable': 'unknown',
            'observation_id': observation['observation_id'], 'grants_execution': False,
            'reason': ['VISUAL_HULL_NOT_CONTACT_OR_TASK_CLEARANCE_CERTIFICATE']}}
    for e in entities:
        identity = e['entity_id']; views = []
        for v in e['views']:
            camera = v['camera']; rec = masks.get((identity, camera))
            if rec is None: continue
            if rec['observation_id'] != observation['observation_id'] or not rec.get('producer') or not rec.get('image_sha256'):
                raise ValueError('MASK_SOURCE_BINDING')
            mask = decode_mask(rec['mask']); width, height = observation['calibration'][camera]['resolution']
            if mask.shape != (height, width): raise ValueError('MASK_PIXEL_COORDINATES')
            reason = mask_quality(mask, cfg)
            if e['identity_status'] != 'hypothesis': reason = 'UNKNOWN_INSTANCE_ASSOCIATION'
            if v['visibility'] != 'visible': reason = 'PARTIAL_OR_UNKNOWN_SILHOUETTE'
            views.append({**clone(v), **clone(rec), 'carving_allowed': reason is None, 'reason': reason,
                'captured_monotonic': observation['captured_monotonic']})
        # Competing identities with substantially overlapping visible masks are not
        # disambiguated merely because their labels or IDs differ.
        for v in views:
            own = decode_mask(v['mask'])
            for other in entities:
                rec = masks.get((other['entity_id'], v['camera']))
                if other['entity_id'] == identity or rec is None: continue
                alt = decode_mask(rec['mask'])
                if (own & alt).sum() > .25 * max(1, min(own.sum(), alt.sum())):
                    v.update(carving_allowed=False, reason='CROSS_INSTANCE_MASK_CONFLICT')
        occupancy, reason, diagnostics = carve(views, observation, cfg, e['kind'], public_plane)
        state['entities'][identity] = {**clone(e), 'instance_id': identity, 'views': views,
            'semantic_source': semantic_source, 'status': 'coarse' if occupancy else 'unknown',
            'point_world_m': None, 'uncertainty_radius_m': None,
            'uncertainty_semantics': 'bounded possible occupancy; 5mm discretization plus mask margin; not calibrated probability',
            'occupancy': occupancy, 'bounds_world_m': occupancy['bounds_world_m'] if occupancy else None,
            'measurement_kind': 'current_multiview_silhouette_constraint' if occupancy else 'unknown',
            'captured_monotonic': observation['captured_monotonic'], 'observation_id': observation['observation_id'],
            'motion': 'unknown', 'held_relation': 'unknown', 'visibility': {v['camera']: v['visibility'] for v in views},
            'reason': reason, 'diagnostics': diagnostics}
    any_coarse = any(e['occupancy'] for e in state['entities'].values())
    state['geometry_quality'].update(numeric_valid='pass' if any_coarse else 'unknown',
        self_consistent='pass' if any_coarse and all(e['occupancy'] for e in state['entities'].values()) else 'unknown')
    state['resource_metrics'] = {'geometry_build_s': time.monotonic()-start, 'DA3_calls': 0, 'Astra_calls': 0,
        'segmentation_calls_inside_build': 0, 'occupancy_serialized_bytes': len(str(state['entities']).encode())}
    state['rebuild_needed'] = any(e['status'] == 'unknown' for e in state['entities'].values())
    state['rebuild_dispatches_model'] = False
    return state
