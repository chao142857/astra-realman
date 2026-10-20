"""Frozen-parameter cross-observation REGION check, not tracked SAM3 masks.

The final-frame mask is used only as a fixed RGB pixel support on OTHER frames.
No new segmentation, ROI tracking, best-parameter/target selection or baseline
rewrite. Pixel overlap is a diagnostic correspondence, never object identity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image
from geometry_diagnostics import euclidean_components,knn_mean_distance,geometry,distribution,pixel_bounds
from rgbd_evidence import artifact,camera_points


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture-root',type=Path,required=True)
    p.add_argument('--baseline-report',type=Path,required=True)
    p.add_argument('--aspire-source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[2]
    a.output.resolve().relative_to(root);a.output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(a.aspire_source/'src'))
    baseline=json.loads(a.baseline_report.read_text())
    prediction=baseline['runs'][2]['predictions'][0]
    maskpath=Path(prediction['mask']['path']);assert artifact(maskpath)['sha256']==prediction['mask']['sha256']
    support=np.array(Image.open(maskpath))>0
    inventory=[];rows=[];protected={str(a.baseline_report):artifact(a.baseline_report)['sha256'],str(maskpath):artifact(maskpath)['sha256']}
    for path in sorted(a.capture_root.glob('live-*/[fl]*/snapshot.json')):
        meta=json.loads(path.read_text());rgbpath=path.parent/'rgb.png';zpath=path.parent/'aligned-depth-m.npy'
        for file in [path,rgbpath,zpath]:protected[str(file)]=artifact(file)['sha256']
        for name in ('rgb.png','aligned-depth-m.npy'):
            assert artifact(path.parent/name)['sha256']==meta['assets'][name]['sha256']
        rgb=np.array(Image.open(rgbpath).convert('RGB'));z=np.load(zpath,allow_pickle=False)
        item={'snapshot':artifact(path),'rgb_sha256':artifact(rgbpath)['sha256'],
            'depth_sha256':artifact(zpath)['sha256'],'color_frame_number':meta['color_frame_number'],
            'depth_frame_number':meta['depth_frame_number'],'host_receipt_epoch_s':meta['captured_at'],
            'role':meta['role'],'serial':meta['serial'],'independent_scene_verified':False,
            'matching_per_observation_target_mask_available':False,'support_mask_sha256':artifact(maskpath)['sha256']}
        if item['rgb_sha256']==prediction['source_rgb_sha256']:
            item['skipped']='ORIGINAL_FINAL_FRAME_NOT_REPROCESSED';inventory.append(item);continue
        assert support.shape==z.shape==rgb.shape[:2]
        assert meta['intrinsics']==meta['aligned_depth_intrinsics']['matrix']
        assert not any(meta['intrinsics_detail']['distortion_coefficients'])
        points,v,u=camera_points(z,np.asarray(meta['intrinsics']),support)
        if not 17<=len(points)<=10000:raise ValueError('REGION_SIZE_OUTSIDE_FROZEN_DIAGNOSTIC_BOUND')
        started=time.perf_counter();variants=[]
        def describe(name,labels):
            groups=[]
            for label in np.unique(labels[labels>0]):
                chosen=labels==label
                groups.append({'id':int(label),'points':int(chosen.sum()),'pixel_bounds_xyxy':pixel_bounds(v[chosen],u[chosen]),
                    'depth':distribution(points[chosen,2]),'geometry':geometry(points[chosen],rgb[v[chosen],u[chosen]],meta['optical_frame'])})
            raster=np.zeros(z.shape,np.int32);raster[v,u]=labels
            variants.append(({'method':name,'retained':int((labels>0).sum()),'excluded':int((labels==0).sum()),'groups':groups},raster))
        for radius in (.005,.010,.020):describe('xyz_cc_'+str(int(radius*1000))+'mm',euclidean_components(points,radius))
        distances=knn_mean_distance(points,16)
        for sigma in (1,2,3):describe('sor_k16_std'+str(sigma),(distances<=distances.mean()+sigma*distances.std(ddof=0)).astype(np.int32))
        item.update(valid_region_points=len(points),support_pixels=int(support.sum()),
            valid_region_fraction=float(len(points)/support.sum()),region_pixel_bounds_xyxy=pixel_bounds(v,u),
            region_depth=distribution(points[:,2]),elapsed_ms=(time.perf_counter()-started)*1000,
            methods=[r for r,_ in variants])
        inventory.append(item);rows.append((item,variants))
    comparisons=[]
    # Consecutive saved observations only. The label raster gives an explicit
    # coverage relation despite absent target tracking/camera-pose certification.
    for (left,lv),(right,rv) in zip(rows,rows[1:]):
        for (lm,lr),(rm,rr) in zip(lv,rv):
            pairs,counts=np.unique(np.column_stack((lr[support],rr[support])),axis=0,return_counts=True)
            edges=[];lg={g['id']:g for g in lm['groups']};rg={g['id']:g for g in rm['groups']}
            for (i,j),n in zip(pairs,counts):
                if not i or not j:continue
                x,y=lg[int(i)],rg[int(j)];ox,oy=x['geometry']['obb'],y['geometry']['obb']
                edge={'from':int(i),'to':int(j),'shared_rgb_pixels':int(n),
                    'pixel_jaccard':float(n/(x['points']+y['points']-n)), 'center_delta_m':None,'corresponding_axis_angles_deg':None}
                if ox and oy:
                    edge['center_delta_m']=(np.asarray(oy['center_m'])-ox['center_m']).tolist()
                    edge['corresponding_axis_angles_deg']=np.rad2deg(np.arccos(np.clip(np.abs(np.sum(
                        np.asarray(ox['axes_columns_in_optical_frame'])*np.asarray(oy['axes_columns_in_optical_frame']),axis=0)),0,1))).tolist()
                edge['pca_axis_ambiguity_warning']=x['geometry'].get('pca_axis_ambiguity_warning',True) or y['geometry'].get('pca_axis_ambiguity_warning',True)
                edges.append(edge)
            comparisons.append({'from':left['snapshot']['path'],'to':right['snapshot']['path'],'method':lm['method'],
                'split_candidates_by_pixel_overlap':sorted({e['from'] for e in edges if sum(f['from']==e['from'] for f in edges)>1}),
                'merge_candidates_by_pixel_overlap':sorted({e['to'] for e in edges if sum(f['to']==e['to'] for f in edges)>1}),
                'overlaps':edges,'object_correspondence_verified':False})
    assert all(artifact(Path(path))['sha256']==sha for path,sha in protected.items())
    report={'status':'FIXED_REGION_CROSS_OBSERVATION_CHECK_NOT_TARGET_OR_INDEPENDENT_SCENE_VALIDATION',
        'fixed_parameters':{'xyz_radius_m':[.005,.010,.020],'sor_k':16,'sor_std':[1,2,3],'sor_ddof':0},
        'selection':'none; original per-frame target masks absent; final Mask is ONLY fixed image support',
        'inventory':inventory,'comparisons':comparisons,'source_hashes_unchanged':True,
        'sam3_calls':0,'hardware_connections':0,'world_pose':None,'accuracy_qualified':False}
    dest=a.output/'cross-observation.json';dest.write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({'status':report['status'],'observations_checked':len(rows),'report':artifact(dest)}))


if __name__=='__main__':main()
