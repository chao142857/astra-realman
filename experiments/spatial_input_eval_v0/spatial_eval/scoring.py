"""Independent truth evaluator. No string similarity and no reference trajectory."""
import copy
from .geometry import contains, swept_collision, angle, norm, sub, projected_interval


def evaluate(snapshot, task, prediction):
    truth=snapshot['ground_truth']
    if truth is None:return {'status':'NOT_SCORED','error_types':['GROUND_TRUTH_UNAVAILABLE'],'score':None,'constraints':{}}
    objects={b['id']:b for b in truth['objects']};regions={b['id']:b for b in truth['regions']}
    if task['kind']=='understanding':
        answers={a['question_id']:a for a in prediction['answers']};rows=[]
        tol=task['tolerance_m']
        for q in task['questions']:
            a=answers[q['question_id']];b=objects[q['object_id']];kind=q['type'];error=None
            if kind=='relation':
                i='xyz'.index(q['axis']);d=b['center_m'][i]-objects[q['other_id']]['center_m'][i]
                expected='equal' if abs(d)<=tol else 'less' if d<0 else 'greater'
                actual=a['relation'];ok=actual==expected
            elif kind in ('position','size'):
                expected=b['center_m'] if kind=='position' else b['size_m'];actual=a['vector_m']
                error=norm(sub(actual,expected));ok=error<=tol
            elif kind=='height':
                lo,hi=projected_interval(b,2)
                expected=b['center_m'][2] if q['reference']=='center' else hi if q['reference']=='top' else lo
                actual=a['scalar_m'];error=abs(actual-expected);ok=error<=tol
            elif kind=='gap':
                i='xyz'.index(q['axis']);lo,hi=projected_interval(b,i);lo2,hi2=projected_interval(objects[q['other_id']],i)
                expected=max(lo2-hi,lo-hi2,0.);actual=a['scalar_m'];error=abs(actual-expected);ok=error<=tol
            else:
                region=regions[q['region_id']];hyp=copy.deepcopy(b)
                hyp.update(center_m=region['center_m'],quaternion_wxyz=q['quaternion_wxyz'])
                expected=contains(region,hyp);actual=a['fits'];ok=actual==expected
            rows.append({'question_id':q['question_id'],'type':kind,'expected':expected,'actual':actual,
                         'within_tolerance':ok,'geometric_error_m':error})
        relation=[r for r in rows if r['type']=='relation'];errors=[r['geometric_error_m'] for r in rows if r['geometric_error_m'] is not None]
        score=sum(r['within_tolerance'] for r in rows)/len(rows)
        return {'status':'SCORED','score':score,'success':score==1,'constraints':{r['question_id']:r['within_tolerance'] for r in rows},
                'relation_accuracy':sum(r['within_tolerance'] for r in relation)/len(relation) if relation else None,
                'mean_geometric_error_m':sum(errors)/len(errors) if errors else None,
                'within_tolerance_ratio':score,'details':rows,
                'error_types':['UNDERSTANDING:'+r['question_id'] for r in rows if not r['within_tolerance']]}
    c=task['constraints'];correct=prediction['object_id']==c['object_id'];checks={'correct_object':correct}
    if prediction['object_id'] not in objects:
        return {'status':'SCORED','score':0.,'success':False,'constraints':checks,'error_types':['UNKNOWN_OBJECT']}
    solids={b['id']:b for b in truth['obstacles'] if b['id']!=prediction['object_id']}
    solids.update({k:b for k,b in objects.items() if k!=prediction['object_id']})
    obstacles=list(solids.values())
    held=copy.deepcopy(objects[prediction['object_id']]);held.update(center_m=prediction['position_m'],quaternion_wxyz=prediction['quaternion_wxyz'])
    # Membership and obstacle checks do not expand legal space by measurement tolerance.
    checks['entire_volume_in_allowed_region']=contains(regions[c['allowed_region_id']],held)
    checks['placement_collision_free']=not any(swept_collision(held,held['center_m'],o,c['clearance_m']) for o in obstacles)
    orient_error=angle(held['quaternion_wxyz'],c['required_quaternion_wxyz']) if c['required_quaternion_wxyz'] else None
    checks['required_orientation']=orient_error is None or orient_error<=c['orientation_tolerance_rad']
    collisions=[]
    if task['kind']=='path':
        waypoints=prediction['waypoints_m'];checks['path_ends_at_placement']=norm(sub(waypoints[-1],held['center_m']))<=1e-9
        points=[c['start_position_m'],*waypoints]
        checks['path_in_workspace']=True
        for i,p in enumerate(points):
            moving=copy.deepcopy(held);moving['center_m']=p
            checks['path_in_workspace'] &= contains(regions[c['workspace_region_id']],moving)
            if i+1<len(points):
                for o in obstacles:
                    if swept_collision(moving,points[i+1],o,c['clearance_m']):collisions.append({'segment':i,'obstacle_id':o['id']})
        checks['continuous_path_collision_free']=not collisions
    success=all(checks.values())
    return {'status':'SCORED','score':float(success),'success':success,'constraints':checks,
            'orientation_error_rad':orient_error,'collisions':collisions,
            'error_types':[k for k,v in checks.items() if not v]}
