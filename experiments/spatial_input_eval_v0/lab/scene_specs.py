"""Six deterministic static SAPIEN scenes; no robot, controller or model calls."""
import math
from spatial_eval.data import box, task, questions

IDENTITY = [1, 0, 0, 0]
TURN90 = [math.sqrt(.5), 0, 0, math.sqrt(.5)]


def container(region):
    x, y, z = region['center_m']; sx, sy, sz = region['size_m']; t = .015
    return [box('container_x_minus', [x-sx/2-t/2,y,z], [t,sy+2*t,sz]),
            box('container_x_plus', [x+sx/2+t/2,y,z], [t,sy+2*t,sz]),
            box('container_y_minus', [x,y-sy/2-t/2,z], [sx,t,sz]),
            box('container_y_plus', [x,y+sy/2+t/2,z], [sx,t,sz]),
            box('container_floor', [x,y,z-sz/2-t/2], [sx+2*t,sy+2*t,t])]


def scenes():
    result = []
    for index, label in enumerate(['relations', 'occlusion', 'narrow_container',
                                    'rotated_fit', 'placement', 'held_object_detour']):
        target = box('target', [.24,-.14,.075], [.08,.06,.10])
        other = box('other', [.48,.08,.10], [.09,.07,.16])
        goal = box('task_volume', [.70,.20,.10], [.20,.18,.18])
        obstacles = [box('table', [.45,0,-.025], [1.4,1.2,.04])]
        kind = 'placement'; required = IDENTITY
        witness = [.70,.20,.10]; waypoints = []
        if index == 1:
            target = box('target', [.43,.02,.07], [.065,.055,.10])
            other = box('other', [.20,-.187,.191], [.18,.20,.28])
        if index == 2:
            target = box('target', [.22,-.16,.075], [.12,.06,.08])
            goal = box('task_volume', [.70,.20,.10], [.09,.07,.18])
            obstacles += container(goal)
            # Impossible fit is an understanding task, paired with feasible placement
            # in a separate task-defined volume. No impossible planning gold label.
            placement = box('placement_volume', [.48,-.20,.10], [.20,.15,.18])
            witness = placement['center_m']
        elif index == 3:
            target = box('target', [.22,-.16,.075], [.16,.06,.05],
                         [math.cos(math.pi/8),0,0,math.sin(math.pi/8)])
            goal = box('task_volume', [.70,.20,.10], [.09,.20,.18])
            obstacles += container(goal)
            required = TURN90
        elif index == 4:
            goal = box('task_volume', [.68,.20,.10], [.24,.22,.18])
            other = box('other', [.735,.245,.10], [.08,.07,.13])
            witness = [.61,.15,.10]
        elif index == 5:
            kind = 'path'
            target = box('target', [.18,-.05,.12], [.06,.05,.06])
            other = box('other', [.30,.35,.08], [.07,.07,.12])
            goal = box('task_volume', [.72,-.05,.12], [.16,.16,.18])
            obstacles.append(box('barrier', [.45,-.05,.15], [.07,.34,.28]))
            witness = goal['center_m']
            waypoints = [[.18,-.32,.12],[.72,-.32,.12],witness]
        regions = [goal]
        if index == 2: regions.append(placement)
        if kind == 'path': regions.append(box('workspace', [.45,0,.26], [1.1,1.05,.50]))
        qs = questions('target', 'other')
        qs += [{'question_id':'relative_y','type':'relation','object_id':'target','other_id':'other','axis':'y'},
               {'question_id':'relative_z','type':'relation','object_id':'target','other_id':'other','axis':'z'},
               {'question_id':'fit_identity','type':'fit','object_id':'target','region_id':'task_volume','quaternion_wxyz':IDENTITY},
               {'question_id':'fit_rotated','type':'fit','object_id':'target','region_id':'task_volume','quaternion_wxyz':TURN90}]
        region_text = '; '.join(f"{r['id']}: center {r['center_m']} m, local full size {r['size_m']} m, wxyz {r['quaternion_wxyz']}" for r in regions)
        common = ('The red cuboid is target; the blue cuboid is other. Gray solids are obstacles. '
                  'Green outlines mark task regions and are visual annotations, not solids. '
                  'Frame robot_base coincides with the simulation world; +x forward, +y left, +z up. '
                  'These are static geometric tasks, with no robot reachability or support requirement. '
                  'Task-defined regions: '+region_text+'. ')
        c = {'object_id':'target','allowed_region_id':'placement_volume' if index==2 else 'task_volume',
             'clearance_m':.002,'required_quaternion_wxyz':required,'orientation_tolerance_rad':.05}
        if kind == 'path': c.update(start_position_m=target['center_m'],workspace_region_id='workspace')
        result.append({'scene_id':f'lab_s{index+1}_{label}', 'objects':[target,other],
                       'regions':regions,'obstacles':obstacles,
                       'tasks':[task('understanding','understand',questions=qs,instruction=common+'Answer every listed geometric question.'),
                                task(kind,'plan',constraints=c,instruction=common+'Choose any fully contained placement, avoiding all solids with the specified clearance. '+
                                     ('Move the held object from start to placement with a fixed orientation; include collision-free center waypoints.' if kind=='path' else 'Return no waypoints.'))],
                       'private_witness':{'object_id':'target','position_m':witness,'quaternion_wxyz':required,'waypoints_m':waypoints}})
    return result
