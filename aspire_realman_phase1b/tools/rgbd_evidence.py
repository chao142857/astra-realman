"""Offline sealed evidence; no acquisition, state synthesis or World transform."""
from pathlib import Path
import hashlib,json
import numpy as np
from PIL import Image,ImageDraw,ImageFont
RGB_SHA='cbed0a959c83a159cf39cb4501d3d8bdf50beea454d7c19ae450107fd23a2c06'
DEPTH_SHA='6d27e56122cac9de7c5244a48462661f792399d9fb79a9933f26267bc151b18c'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_snapshot(path):
    path=Path(path).resolve();meta=json.loads(path.read_text());root=path.parent
    for name,a in meta['assets'].items():
        f=Path(a['path']).resolve()
        if f.parent!=root or sha(f)!=a['sha256']:raise ValueError('SEALED_ASSET_HASH_OR_PATH_MISMATCH:'+name)
    if meta['assets']['rgb.png']['sha256']!=RGB_SHA or meta['assets']['aligned-depth-m.npy']['sha256']!=DEPTH_SHA:
        raise ValueError('PHASE_1A_LAST_FRAME_IDENTITY_MISMATCH')
    rgb=np.array(Image.open(root/'rgb.png').convert('RGB'));z=np.load(root/'aligned-depth-m.npy',allow_pickle=False)
    raw=np.load(root/'aligned-z16.npy',allow_pickle=False)
    capture=json.loads((root.parent/'report.json').read_text());scale=capture['profile']['depth_scale_m_per_z16']
    if z.dtype!=np.float32 or raw.dtype!=np.uint16 or z.shape!=rgb.shape[:2]:raise ValueError('RGBD_SHAPE_OR_DTYPE_MISMATCH')
    residual=float(np.max(np.abs(z-raw.astype(np.float32)*scale)))
    if residual>1e-6:raise ValueError('Z16_METRE_SCALE_MISMATCH')
    if meta['alignment']!='depth_to_color' or meta['intrinsics']!=meta['aligned_depth_intrinsics']['matrix']:
        raise ValueError('NOT_ALIGNED_TO_COLOR')
    if any(meta['intrinsics_detail']['distortion_coefficients']):raise ValueError('NONZERO_DISTORTION_REQUIRES_SUPPORTED_DEPROJECTION')
    provenance={'snapshot':str(path),'snapshot_sha256':sha(path),'rgb_sha256':RGB_SHA,'depth_sha256':DEPTH_SHA,
      'rgb_pixel_sha256':hashlib.sha256(rgb.tobytes()).hexdigest(),'serial':meta['serial'],
      'color_frame_number':meta['color_frame_number'],'depth_frame_number':meta['depth_frame_number'],
      'color_depth_skew_ms':abs(meta['color_timestamp_ms']-meta['depth_timestamp_ms']),
      'frame':meta['optical_frame'],'depth_scale_m_per_z16':scale,'z16_scale_max_residual_m':residual,
      'mode':'SEALED_REAL_RGBD_NOT_LIVE','world_transform':None,'current_robot_state':None}
    return rgb,z,meta,provenance

def stats(z,selector):
    valid=selector & np.isfinite(z)&(z>0);v=z[valid]
    return {'pixels':int(selector.sum()),'valid_pixels':int(valid.sum()),'valid_fraction':float(valid.sum()/selector.sum()) if selector.any() else None,
      'positive_depth_p0_p1_p25_p50_p75_p99_p100_m':np.percentile(v,[0,1,25,50,75,99,100]).tolist() if v.size else None,
      'depth_band_valid_fractions':{name:float(((v>=lo)&(v<hi)).mean()) if v.size else None for name,lo,hi in
       [('0_to_1m',0,1),('1_to_1.5m',1,1.5),('1.5_to_2.3m',1.5,2.3),('2.3m_and_above',2.3,float('inf'))]}}

def rectangle(shape,xyxy):
    x0,y0,x1,y1=xyxy;s=np.zeros(shape,bool);s[y0:y1,x0:x1]=True;return s

def camera_points(z,k,mask):
    v,u=np.nonzero(mask&np.isfinite(z)&(z>0));depth=z[v,u]
    return np.column_stack(((u-k[0,2])*depth/k[0,0],(v-k[1,2])*depth/k[1,1],depth)),v,u

def write_cloud(path,points,colors):
    header=f'ply\nformat binary_little_endian 1.0\nelement vertex {len(points)}\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n'
    rows=np.empty(len(points),dtype=[('xyz','<f4',(3,)),('rgb','u1',(3,))]);rows['xyz']=points;rows['rgb']=colors
    with Path(path).open('wb') as f:f.write(header.encode());f.write(rows.tobytes())

def artifact(path):
    p=Path(path);return {'path':str(p.resolve()),'bytes':p.stat().st_size,'sha256':sha(p)}

def comparison(rgb,z,out):
    h,w=z.shape;valid=np.isfinite(z)&(z>0);t=np.clip((z-.3)/2.7,0,1)
    # Fixed displayed scale 0.3..3.0m, near red / far blue; invalid black.
    color=np.stack((255*(1-t),255*(1-np.abs(t-.5)*2),255*t),axis=2).astype(np.uint8);color[~valid]=0
    panels=[Image.fromarray(rgb),Image.fromarray(color),Image.fromarray(np.repeat((valid*255).astype(np.uint8)[...,None],3,axis=2))]
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
    canvas=Image.new('RGB',(w*3,h+100),'#eeeeee');draw=ImageDraw.Draw(canvas)
    labels=['Sealed real RGB: central ROI outlined','Aligned depth Z: red 0.3m -> blue 3.0m','Sensor validity: finite Z > 0 (NOT SAM3)']
    for i,p in enumerate(panels):
        canvas.paste(p,(i*w,38));draw.text((i*w+8,10),labels[i],fill='black',font=font)
        draw.rectangle((i*w+w//4,38+h//4,i*w+3*w//4-1,38+3*h//4-1),outline='#ff00ff',width=2)
    draw.text((8,h+48),'Same frame: color #174 / depth #91; metres; no World transform. Depth >3m saturates blue; zero is black.',fill='black',font=font)
    draw.text((8,h+73),'Original files stay on yanglab. Magenta ROI = x[160:480], y[120:360]. No object segmentation is implied.',fill='black',font=font)
    canvas.save(out/'rgb-depth-validity.png');canvas.resize((1440,435)).save(out/'rgb-depth-validity-preview.jpg',quality=88)
    # Show where the central 1.5..2.3m measurements actually lie in the RGB.
    selected=valid&(z>=1.5)&(z<2.3);overlay=rgb.copy();overlay[selected]=(rgb[selected]*.4+np.array([255,255,0])*.6).astype(np.uint8)
    im=Image.fromarray(overlay);d=ImageDraw.Draw(im);d.rectangle((160,120,479,359),outline='magenta',width=2)
    im.save(out/'depth-1p5-to-2p3m-overlay.png')


def mask_geometry(rgb,z,meta,mask,out,name):
    from cap_harness.contracts import PointCloud
    from cap_harness.geometry import estimate_geometry
    s=stats(z,mask);k=np.array(meta['intrinsics']);points,v,u=camera_points(z,k,mask)
    result={**s,'frame':meta['optical_frame'],'world_pose':None,'scope':'visible depth returns only; not complete object shape or certified accuracy',
            'point_count':len(points),'obb':None}
    if len(points):
        path=out/(name+'-visible-cloud.ply');write_cloud(path,points,rgb[v,u]);result['cloud']=artifact(path)
        result['point_xyz_min_max_m']=[points.min(0).tolist(),points.max(0).tolist()]
    if len(points)>=4:
        try:
            g=estimate_geometry(PointCloud(points=points,colors=rgb[v,u],frame=meta['optical_frame']))
            result['obb']={'method':'unchanged ASPIRE PCA estimate_geometry','center_m':g.pose.position.tolist(),
               'quaternion_wxyz':g.pose.quaternion_wxyz.tolist(),'extents_m':g.extents.tolist(),'frame':g.pose.frame,
               'point_count':g.point_count,'is_complete_object_obb':False,'world_transform_applied':False}
        except ValueError as exc:result['obb_error']=str(exc)
    return result
