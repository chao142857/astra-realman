"""Pilot 02 preregistered deterministic design. No model calls or answer-based selection."""
import copy
import math
from spatial_eval.data import box, task

I = [1., 0., 0., 0.]

def yaw(degrees):
    a = math.radians(degrees) / 2
    return [math.cos(a), 0., 0., math.sin(a)]


def answer(p, q=I, points=None):
    return {'object_id': 'target', 'position_m': list(p),
            'quaternion_wxyz': list(q), 'waypoints_m': copy.deepcopy(points or [])}


def pocket(center, outer_xy, inner_xy, height=.20):
    """Fill a rectangular volume except a rectangular pocket; positive-thickness solids."""
    x,y,z = center; ox,oy = outer_xy; ix,iy = inner_xy
    # Outer footprint is centered at (.62, 0); pocket can move in y independently.
    xmin,xmax=.62-ox/2,.62+ox/2; ymin,ymax=-oy/2,oy/2
    return [box('block_x_minus',[(xmin+x-ix/2)/2,0,z],[x-ix/2-xmin,oy,height]),
            box('block_x_plus',[(x+ix/2+xmax)/2,0,z],[xmax-x-ix/2,oy,height]),
            box('block_y_minus',[x,(ymin+y-iy/2)/2,z],[ix,y-iy/2-ymin,height]),
            box('block_y_plus',[x,(y+iy/2+ymax)/2,z],[ix,ymax-y-iy/2,height])]


def rotated_pocket(center, angle):
    a=math.radians(angle); result=[]
    for name,local,size in [('x_minus',[-.18,0,0],[.20,.55,.20]),
                            ('x_plus',[.18,0,0],[.20,.55,.20]),
                            ('y_minus',[0,-.1325,0],[.55,.20,.20]),
                            ('y_plus',[0,.1325,0],[.55,.20,.20])]:
        x,y,z=local
        p=[center[0]+x*math.cos(a)-y*math.sin(a),center[1]+x*math.sin(a)+y*math.cos(a),center[2]+z]
        result.append(box('block_'+name,p,size,yaw(angle)))
    return result


def specs():
    out=[]
    for mm in (3,10,30):
        for sign in (-1,1):
            p=[.62,sign*.11,.12]
            target=box('target',[.19,-.32,.09],[.08,.06,.08])
            region=box('task_volume',[.62,0,.12],[.42,.46,.18])
            m=mm/1000
            out.append({'scene_id':f'p02_a_m{mm:02d}_{"minus" if sign<0 else "plus"}',
                        'family':'A_PLACEMENT_MARGIN','pair_id':f'A_margin_{mm:02d}mm',
                        'design':{'nominal_per_side_gap_m':m,'pocket_side':sign},
                        'objects':[target], 'regions':[region],
                        'obstacles':pocket(p,[.42,.46],[.08+2*m,.06+2*m]),
                        'kind':'placement','orientation_policy':{'mode':'fixed','quaternion_wxyz':I,'tolerance_rad':.02},
                        'witness':answer(p), 'alternate_witnesses':[answer([p[0]+.0002,p[1],p[2]])],
                        'negative_controls':{'blocked_center':answer(region['center_m'])}})
    for sign in (-1,1):
        start=[.18,0,.12]; goal=[.76,0,.12]; side=sign*.20
        target=box('target',start,[.06,.06,.06])
        regions=[box('task_volume',goal,[.10,.12,.10]),box('workspace',[.48,0,.14],[.72,.56,.22])]
        barrier=box('barrier',[.48,-sign*.08,.14],[.07,.38,.24])
        # Gray rails mark the public workspace top; no opaque ceiling hides the gap.
        rails=[box('height_rail_minus',[.48,-.292,.26],[.744,.012,.012]),
               box('height_rail_plus',[.48,.292,.26],[.744,.012,.012])]
        w=answer(goal,points=[[.18,side,.12],[.76,side,.12],goal])
        out.append({'scene_id':f'p02_b_open_{"minus" if sign<0 else "plus"}',
                    'family':'B_BOUNDED_DETOUR','pair_id':'B_side_swap','design':{'open_side':sign},
                    'objects':[target],'regions':regions,'obstacles':[barrier,*rails], 'kind':'path',
                    'orientation_policy':{'mode':'fixed','quaternion_wxyz':I,'tolerance_rad':.02},
                    'witness':w,'alternate_witnesses':[answer(goal,points=[[.18,sign*.21,.12],[.76,sign*.21,.12],goal])],
                    'negative_controls':{'straight':answer(goal,points=[goal]),
                                         'overfly':answer(goal,points=[[.18,0,.45],[.76,0,.45],goal])}})
    for angle in (30,120):
        p=[.64,.04,.12]
        target=box('target',[.12,-.37,.09],[.14,.045,.065],yaw(20))
        out.append({'scene_id':f'p02_c_slot_{angle:03d}',
                    'family':'C_FREE_YAW','pair_id':'C_slot_rotation','design':{'private_slot_angle_deg':angle},
                    'objects':[target],'regions':[box('task_volume',p,[.28,.28,.16])],
                    'obstacles':rotated_pocket(p,angle),'kind':'placement',
                    'orientation_policy':{'mode':'upright_free_yaw','local_axis':[0,0,1],
                                          'world_axis':[0,0,1],'max_tilt_rad':.02},
                    'witness':answer(p,yaw(angle)),
                    'alternate_witnesses':[answer(p,yaw(angle+180)),answer(p,yaw(angle+1)),answer(p,yaw(angle-1)),
                                            answer(p,[-v for v in yaw(angle)])],
                    'negative_controls':{'wrong_paired_yaw':answer(p,yaw(angle+90)),
                                         'not_upright':answer(p,[0,1,0,0])}})
    for s in out:
        s['obstacles'].append(box('table',[.48,0,-.025],[1.6,1.5,.04]))
        policy=s['orientation_policy']
        c={'object_id':'target','allowed_region_id':'task_volume','clearance_m':.002,
           'required_quaternion_wxyz':policy.get('quaternion_wxyz'),
           'orientation_tolerance_rad':.02}
        if s['kind']=='path': c.update(start_position_m=s['objects'][0]['center_m'],workspace_region_id='workspace')
        region_text='; '.join(f"{r['id']}: center={r['center_m']} m, full_size={r['size_m']} m, wxyz={r['quaternion_wxyz']}" for r in s['regions'])
        instruction=('The red cuboid is target; gray solids are obstacles. Green wireframes mark public task volumes, not solids. '
                     'Choose any collision-free object-center placement fully inside task_volume with the specified SAT-axis clearance. '
                     'All positions use robot_base=simulation world, meters; +z up. Static geometry only; no support, robot or dynamics requirement. '
                     'Public volumes: '+region_text+'. ')
        if s['kind']=='path':
            instruction+=('Move at fixed orientation through workspace using center waypoints. The entire object must remain below the workspace top z=0.25 m '
                          'and above its bottom z=0.03 m along every segment; gray perimeter rails and green frame mark the height limit. ')
        else: instruction+='Return no waypoints. '
        if policy['mode']=='upright_free_yaw': instruction+='Keep the local +z axis within 0.02 radians of world +z; choose yaw freely using this scene. No target quaternion is prescribed. '
        s['task']=task(s['kind'],'plan',constraints=c,instruction=instruction)
    return out


def policies(s):
    """Predeclared scene-blind baselines, never deriving a solution from obstacle geometry."""
    center=next(r for r in s['regions'] if r['id']=='task_volume')['center_m']
    q=I; result={'normal_center_identity':answer(center,q)}
    region=next(r for r in s['regions'] if r['id']=='task_volume')
    size=s['objects'][0]['size_m']
    corner=[center[i]-region['size_m'][i]/2+size[i]/2+.004 for i in range(3)]
    result['fixed_region_lower_corner_identity']=answer(corner)
    if s['family']=='A_PLACEMENT_MARGIN':
        result['fixed_minus_landing']=answer([.62,-.11,.12])
        result['fixed_plus_landing']=answer([.62,.11,.12])
    elif s['family']=='B_BOUNDED_DETOUR':
        for name,side in [('fixed_minus_detour',-.20),('fixed_plus_detour',.20)]:
            result[name]=answer(center,points=[[.18,side,.12],[.76,side,.12],center])
        for p in result.values():
            if not p['waypoints_m']: p['waypoints_m']=[p['position_m']]
        result['high_overfly']=answer(center,points=[[.18,0,.45],[.76,0,.45],center])
    else:
        for a in (0,30,90,120): result[f'fixed_yaw_{a:03d}']=answer(center,yaw(a))
        result['retain_initial_yaw']=answer(center,s['objects'][0]['quaternion_wxyz'])
    return result
