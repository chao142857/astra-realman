"""Bounded source-mesh vs original sphere diagnosis. No model edits or hardware.

Triangle SAT is evaluated after a full AABB BVH traversal, without convex-hull
replacement. Contact and surface crossing are reported separately from sphere
overlap. A source STL is evidence of a nominal model, not of physical assembly.
"""
import argparse, hashlib, json, os, sys, time
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'aspire_realman_phase2a/src'),str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src'),str(ROOT/'.cache/curobo')]
import numpy as np
import trimesh, yaml
from PIL import Image, ImageDraw
from aspire_realman.codec import rpy_matrix
from aspire_realman_phase2a.model import sha

EPS=1e-8

def origin(node):
    t=np.eye(4)
    if node is not None:
        t[:3,3]=[float(x) for x in node.get('xyz','0 0 0').split()]
        t[:3,:3]=rpy_matrix([float(x) for x in node.get('rpy','0 0 0').split()])
    return t

def fk(root,q):
    known={'base_link':np.eye(4)};pending=list(root.findall('joint'))
    while pending:
        deferred=[]
        for j in pending:
            parent=j.find('parent').get('link');child=j.find('child').get('link')
            if parent not in known:deferred.append(j);continue
            r=np.eye(4)
            if j.get('type') in ('revolute','continuous'):
                axis=np.array([float(x) for x in j.find('axis').get('xyz').split()]);axis/=np.linalg.norm(axis)
                x,y,z=axis;k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
                angle=q[j.get('name')];r[:3,:3]=np.eye(3)+np.sin(angle)*k+(1-np.cos(angle))*(k@k)
            known[child]=known[parent]@origin(j.find('origin'))@r
        if len(deferred)==len(pending):raise ValueError('DISCONNECTED_URDF')
        pending=deferred
    return known

def transform(points,t):return points@t[:3,:3].T+t[:3,3]

class BVH:
    def __init__(self,triangles,ids=None):
        ids=np.arange(len(triangles)) if ids is None else ids
        pts=triangles[ids];self.lo=pts.min((0,1));self.hi=pts.max((0,1));self.ids=ids;self.children=None
        if len(ids)>24:
            centers=pts.mean(1);axis=np.ptp(centers,axis=0).argmax();order=np.argsort(centers[:,axis]);half=len(ids)//2
            self.children=(BVH(triangles,ids[order[:half]]),BVH(triangles,ids[order[half:]]))

def triangle_sat(a,b):
    """Vectorized SAT, including coplanar in-plane separating axes."""
    ea=np.roll(a,-1,axis=1)-a;eb=np.roll(b,-1,axis=1)-b
    na=np.cross(ea[:,0],ea[:,1]);nb=np.cross(eb[:,0],eb[:,1])
    axes=np.concatenate((na[:,None],nb[:,None],np.cross(ea[:,:,None],eb[:,None]).reshape(-1,9,3),
                         np.cross(na[:,None],ea),np.cross(nb[:,None],eb)),axis=1)
    norms=np.linalg.norm(axes,axis=2);axes=axes/np.maximum(norms[...,None],1e-30)
    pa=np.einsum('nvi,nki->nkv',a,axes);pb=np.einsum('nvi,nki->nkv',b,axes)
    separated=((pa.max(2)<pb.min(2)-EPS)|(pb.max(2)<pa.min(2)-EPS))&(norms>1e-20)
    return ~separated.any(1)

def crossing_points(a,b):
    # Strict finite-segment Moller-Trumbore: witnesses of non-coplanar crossing,
    # not a penetration depth (and not a physical interference verdict).
    out=[]
    for x,y in ((a,b),(b,a)):
        for e in range(3):
            p=x[:,e];d=x[:,(e+1)%3]-p;u=y[:,1]-y[:,0];v=y[:,2]-y[:,0]
            h=np.cross(d,v);det=np.einsum('ni,ni->n',u,h);safe=np.abs(det)>1e-18
            inv=np.divide(1.,det,out=np.zeros_like(det),where=safe);s=p-y[:,0]
            alpha=np.einsum('ni,ni->n',s,h)*inv;cross=np.cross(s,u)
            beta=np.einsum('ni,ni->n',d,cross)*inv;t=np.einsum('ni,ni->n',v,cross)*inv
            hit=safe&(alpha>1e-7)&(beta>1e-7)&(alpha+beta<1-1e-7)&(t>1e-7)&(t<1-1e-7)
            out.extend((p[hit]+t[hit,None]*d[hit]).tolist())
    return out

def mesh_intersections(a,b):
    ta=np.asarray(a.triangles);tb=np.asarray(b.triangles);stack=[(BVH(ta),BVH(tb))];hits=[];witnesses=[];tested=0
    while stack:
        x,y=stack.pop()
        if np.any(x.hi<y.lo-EPS) or np.any(y.hi<x.lo-EPS):continue
        if x.children is not None or y.children is not None:
            if x.children is not None and (y.children is None or len(x.ids)>=len(y.ids)):
                stack.extend((c,y) for c in x.children)
            else:stack.extend((x,c) for c in y.children)
            continue
        i,j=np.meshgrid(x.ids,y.ids,indexing='ij');i=i.ravel();j=j.ravel();aa=ta[i];bb=tb[j]
        candidate=np.all((aa.max(1)>=bb.min(1)-EPS)&(bb.max(1)>=aa.min(1)-EPS),axis=1)
        i,j=i[candidate],j[candidate];tested+=len(i)
        if not len(i):continue
        mask=triangle_sat(ta[i],tb[j]);i,j=i[mask],j[mask]
        hits.extend(zip(i.tolist(),j.tolist()))
        witnesses.extend(crossing_points(ta[i],tb[j]))
    gap=np.maximum(np.maximum(a.bounds[0]-b.bounds[1],b.bounds[0]-a.bounds[1]),0.)
    # Check containment separately if surfaces do not cross. Winding is only
    # meaningful for watertight, consistently wound mesh solids.
    containment={}
    for name,x,y in [('a_in_b',a,b),('b_in_a',b,a)]:
        if not y.is_watertight or not y.is_winding_consistent:
            containment[name]={'status':'UNAVAILABLE_NON_WATERTIGHT_OR_INCONSISTENT'};continue
        p=x.vertices[0];v=np.asarray(y.triangles)-p
        n=np.linalg.norm(v,axis=2)
        num=np.einsum('ni,ni->n',v[:,0],np.cross(v[:,1],v[:,2]))
        den=n.prod(1)+np.einsum('ni,ni->n',v[:,0],v[:,1])*n[:,2]+np.einsum('ni,ni->n',v[:,1],v[:,2])*n[:,0]+np.einsum('ni,ni->n',v[:,2],v[:,0])*n[:,1]
        winding=float(np.arctan2(num,den).sum()/(2*np.pi))
        containment[name]={'status':'ONE_VERTEX_WINDING_DIAGNOSTIC','winding':winding,'inside':abs(winding)>.5}
    return {'surface_intersecting_triangle_pairs':len(hits),'strict_crossing_witness_count':len(witnesses),
            'strict_crossing_witnesses_first_32':witnesses[:32],'triangle_aabb_candidates_tested':tested,
            'aabb_distance_lower_bound_m':float(np.linalg.norm(gap)),
            'containment':containment,'tolerance_m':EPS,
            'status':'SOURCE_MESH_SURFACE_CROSSING' if witnesses else 'SOURCE_MESH_CONTACT_OR_COPLANAR_INTERSECTION' if hits else 'NO_SOURCE_MESH_SURFACE_INTERSECTION',
            'caveat':'Surface crossing is not a penetration depth. Non-watertight containment and intentional mechanical contacts require CAD interpretation.'}

def load_mesh(link):
    meshes=[];sources=[]
    for collision in link.findall('collision'):
        g=collision.find('geometry');node=g.find('mesh')
        if node is None:continue
        p=Path(node.get('filename'));m=trimesh.load_mesh(p,process=True)
        m.apply_scale([float(v) for v in node.get('scale','1 1 1').split()]);m.apply_transform(origin(collision.find('origin')))
        meshes.append(m);sources.append({'path':str(p),'sha256':sha(p),'collision_origin':origin(collision.find('origin')).tolist(),'scale':node.get('scale','1 1 1')})
    return trimesh.util.concatenate(meshes),sources

def plot_pair(path,meshes,balls,label):
    image=Image.new('RGB',(1440,600),'white');d=ImageDraw.Draw(image);colors=[(79,134,211),(233,139,55)]
    d.text((12,8),label,fill='black');d.text((12,26),'Orthographic nominal mesh projections; highlighted original sphere pair. NOT measured assembly.',fill='black')
    for view,(ix,iy,iz) in enumerate(((0,1,2),(0,2,1),(1,2,0))):
        points=np.concatenate([m.vertices for m in meshes]);lo=points[:,[ix,iy]].min(0);hi=points[:,[ix,iy]].max(0)
        span=max(hi-lo);scale=420/span;center=(lo+hi)/2;offset=np.array([view*480+240,320])
        def proj(v):return (v[:,[ix,iy]]-center)*np.array([scale,-scale])+offset
        faces=[]
        for k,m in enumerate(meshes):
            xy=proj(m.vertices)
            for face in m.faces:faces.append((m.vertices[face,iz].mean(),xy[face],k))
        for _,tri,k in sorted(faces,key=lambda x:x[0]):d.polygon([tuple(p) for p in tri],fill=colors[k])
        for k,b in enumerate(balls):
            x,y=proj(np.asarray([b['center_reference_m']]))[0];r=b['radius_m']*scale
            d.ellipse([x-r,y-r,x+r,y+r],outline=(200,0,150) if k==0 else (0,150,60),width=2)
        d.text((view*480+10,565),'XYZ'[ix]+' / '+'XYZ'[iy]+' [m]; same scale within each view',fill='black')
    image.save(path)

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--vendor',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.resolve().relative_to(ROOT);a.output.mkdir(parents=True,exist_ok=False)
    m=json.loads(a.manifest.read_text());u=Path(next(p for p in m['source_sha256'] if p.endswith('urdf')))
    y=Path(next(p for p in m['source_sha256'] if p.endswith('yml')));root=ET.parse(u).getroot();k=yaml.safe_load(y.read_text())['robot_cfg']['kinematics']
    links={l.get('name'):l for l in root.findall('link')};cache={}
    for n in ['Link5','ctag_base_link','ctag_Left_1_Link','ctag_Left_2_Link','ctag_Right_1_Link','ctag_Right_2_Link']:
        cache[n]=load_mesh(links[n])
    vendor_gripper=a.vendor/'crt_ctag2f90d_gripper_visualization/urdf/crt_ctag2f90d_gripper_visualization.urdf'
    vg=ET.parse(vendor_gripper).getroot()
    report={'status':'BLOCKED_PHYSICAL_GEOMETRY_EVIDENCE','physical_commands_sent':0,
        'source_sha256':{**m['source_sha256'],str(vendor_gripper):sha(vendor_gripper)},
        'frozen_model_sha256':{str(a.manifest):sha(a.manifest),m['urdf']['path']:sha(m['urdf']['path']),m['config']['path']:sha(m['config']['path'])},
        'joint_records':[{'name':j.get('name'),'type':j.get('type'),'xml':ET.tostring(j,encoding='unicode')} for j in root.findall('joint')],
        'manufacturer_gripper_mimics':{j.get('name'):j.find('mimic').attrib for j in vg.findall('joint') if j.find('mimic') is not None},
        'mesh_sources':{n:{'sources':v[1],'vertices':len(v[0].vertices),'faces':len(v[0].faces),'watertight':bool(v[0].is_watertight),'bounds_link_m':v[0].bounds.tolist()} for n,v in cache.items()},
        'method':'Original STL triangles (not convex hull), independent URDF FK; full BVH triangle SAT with coplanar axes + strict edge/triangle witnesses; epsilon 1e-8 m. No ignore/radius/geometry change.',
        'cases':[]}
    # Deterministic analytic sensitivity grid, NOT a feasibility random search.
    for q6 in [-np.pi,-np.pi/2,0.,np.pi/2,np.pi]:
        for master in [0.,-.455,-.91]:
            q={f'joint{i+1}':v for i,v in enumerate(m['default_positions']['left'])};q['joint6']=q6
            q.update({n:master*float(row.get('multiplier',1))+float(row.get('offset',0)) for n,row in report['manufacturer_gripper_mimics'].items()})
            # Source names are prefixed in the assembly; apply original mimic ratios.
            for n in list(q):
                if n.endswith('_Joint') and not n.startswith('ctag_'):q['ctag_'+n]=q.pop(n)
            q['ctag_Left_1_Joint']=master
            t=fk(root,q)
            for x,z in [('Link5','ctag_base_link'),('ctag_Left_1_Link','ctag_Left_2_Link'),('ctag_Right_1_Link','ctag_Right_2_Link')]:
                if x!='Link5' and q6!=0.:continue # relative finger geometry invariant to upstream joint6
                if x=='Link5' and master!=0.:continue # the base geometry is independent of finger coordinates
                start=time.perf_counter();ref=x;inverse=np.linalg.inv(t[ref]);world_to_ref=inverse
                tx=world_to_ref@t[x];tz=world_to_ref@t[z]
                sx=np.array([v['center']+[v['radius']] for v in k['collision_spheres'][x]]);sz=np.array([v['center']+[v['radius']] for v in k['collision_spheres'][z]])
                cx=transform(sx[:,:3],tx);cz=transform(sz[:,:3],tz)
                depth=sx[:,None,3]+sz[None,:,3]-np.linalg.norm(cx[:,None]-cz[None],axis=2);i,j=np.unravel_index(np.argmax(depth),depth.shape)
                balls=[{'link':n,'index_within_link':int(index),'center_link_m':s[index,:3].tolist(),'center_reference_m':c[index].tolist(),'radius_m':float(s[index,3])} for n,index,s,c in [(x,i,sx,cx),(z,j,sz,cz)]]
                row={'joint6_rad':q6,'gripper_master_rad':master,'gripper_configuration':'SOURCE_MANUFACTURER_MIMIC_CONSISTENT','links':[x,z],'reference_frame':ref,
                    'T_base_link':{n:t[n].tolist() for n in [x,z,'Link6','ctag_base']},'T_reference_link':{x:tx.tolist(),z:tz.tolist()},
                    'worst_original_sphere_pair':balls,'sphere_overlap_m':float(depth[i,j]),'positive_sphere_pairs':int((depth>0).sum())}
                mx=cache[x][0].copy();mz=cache[z][0].copy();mx.apply_transform(tx);mz.apply_transform(tz)
                # Upstream q6 does not change finger-link relative mesh geometry.
                row['mesh_comparison']=mesh_intersections(mx,mz)
                row['elapsed_s']=time.perf_counter()-start
                image=f'pair-{len(report["cases"]):02d}.png';row['mesh_comparison_image']=image
                plot_pair(a.output/image,[mx,mz],balls,f'{x} / {z}; q6={q6:.6f}; master={master:.3f}; sphere overlap={depth[i,j]*1000:.3f} mm')
                report['cases'].append(row)
                (a.output/'result.json').write_text(json.dumps(report,indent=2))
                print(json.dumps({k:row[k] for k in ('links','joint6_rad','gripper_master_rad','sphere_overlap_m','mesh_comparison','elapsed_s')}),flush=True)
    # Algorithm sanity checks use closed boxes, separated, crossing and coplanar contact.
    box=trimesh.creation.box();shift=box.copy();shift.apply_translation([2,0,0]);cross=box.copy();cross.apply_translation([.4,.3,.2]);touch=box.copy();touch.apply_translation([1,0,0])
    fixtures={n:mesh_intersections(box,v) for n,v in [('separated',shift),('crossing',cross),('touching',touch)]}
    assert fixtures['separated']['surface_intersecting_triangle_pairs']==0
    assert fixtures['crossing']['strict_crossing_witness_count']>0
    assert fixtures['touching']['surface_intersecting_triangle_pairs']>0
    report['algorithm_fixtures']=fixtures
    assert all(sha(path)==digest for path,digest in report['frozen_model_sha256'].items())
    assert all(sha(path)==digest for path,digest in report['source_sha256'].items())
    (a.output/'result.json').write_text(json.dumps(report,indent=2));print('COMPLETE_BLOCKED_PHYSICAL_GEOMETRY_EVIDENCE')

if __name__=='__main__':main()
