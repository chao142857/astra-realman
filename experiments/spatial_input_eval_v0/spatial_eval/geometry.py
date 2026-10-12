"""3D oriented boxes and exact continuous SAT for translation at fixed orientation."""
import itertools
import math
from .schema import fields, vector, quaternion

def dot(a,b): return sum(x*y for x,y in zip(a,b))
def sub(a,b): return [x-y for x,y in zip(a,b)]
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(v): return math.sqrt(dot(v,v))
def axes(q):
    w,x,y,z=q
    return [[1-2*(y*y+z*z),2*(x*y+w*z),2*(x*z-w*y)],
            [2*(x*y-w*z),1-2*(x*x+z*z),2*(y*z+w*x)],
            [2*(x*z+w*y),2*(y*z-w*x),1-2*(x*x+y*y)]]

def validate_geometry(g):
    fields(g, ['source','frame','units','objects','regions','obstacles','renderings'])
    if g['units']!='m' or g['frame']!='robot_base' or g['source'] not in ('SIMULATOR_TRUTH','INDEPENDENT_MEASUREMENT','RECONSTRUCTION','SYNTHETIC_FIXTURE_TRUTH'):raise ValueError('GEOMETRY_FRAME_UNITS_SOURCE')
    for group in ('objects','regions','obstacles'):
        if not isinstance(g[group], list): raise ValueError('GEOMETRY_LIST')
        ids=set()
        for b in g[group]:
            fields(b, ['id','center_m','size_m','quaternion_wxyz'])
            if not isinstance(b['id'],str) or not b['id'] or b['id'] in ids: raise ValueError('GEOMETRY_ID')
            ids.add(b['id']);vector(b['center_m'],3);vector(b['size_m'],3);quaternion(b['quaternion_wxyz'])
            if min(b['size_m']) <= 0: raise ValueError('POSITIVE_SIZE_REQUIRED')
    # Reserved rendering extension; V0 accepts only structured text. Never silently ignore images.
    if g['renderings'] != []: raise ValueError('GEOMETRY_RENDERINGS_NOT_IMPLEMENTED_V0')
    return g

def box(identity, center, size, q=None):
    return {'id':identity,'center_m':center,'size_m':size,'quaternion_wxyz':q or [1,0,0,0]}

def corners(b):
    aa=axes(b['quaternion_wxyz'])
    return [[b['center_m'][j]+sum(s[i]*b['size_m'][i]/2*aa[i][j] for i in range(3)) for j in range(3)]
            for s in itertools.product((-1,1),repeat=3)]

def contains(region, b, tol=0):
    aa=axes(region['quaternion_wxyz'])
    return all(abs(dot(sub(p,region['center_m']),aa[i])) <= region['size_m'][i]/2+tol
               for p in corners(b) for i in range(3))

def radius(b, aa, axis):
    return sum(b['size_m'][i]/2*abs(dot(aa[i],axis)) for i in range(3))

def swept_collision(b, end, obstacle, clearance=0):
    """Intersection at any t in [0,1], including touch; no waypoint sampling gaps."""
    aa,bb=axes(b['quaternion_wxyz']),axes(obstacle['quaternion_wxyz'])
    tests=aa+bb+[cross(a,c) for a in aa for c in bb]
    delta=sub(b['center_m'],obstacle['center_m']);vel=sub(end,b['center_m'])
    lo,hi=0.,1.
    for axis in tests:
        length=norm(axis)
        if length < 1e-10: continue
        axis=[x/length for x in axis]
        r=radius(b,aa,axis)+radius(obstacle,bb,axis)+clearance
        d,v=dot(delta,axis),dot(vel,axis)
        if abs(v)<1e-14:
            if abs(d)>r+1e-12:return False
        else:
            t0,t1=sorted(((-r-d)/v,(r-d)/v))
            lo,hi=max(lo,t0),min(hi,t1)
            if lo>hi+1e-12:return False
    return True

def angle(q,r):
    return 2*math.acos(min(1.,abs(dot(q,r))))

def projected_interval(b, axis):
    values=[p[axis] for p in corners(b)]
    return min(values),max(values)
