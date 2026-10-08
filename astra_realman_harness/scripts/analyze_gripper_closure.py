#!/usr/bin/env python3
"""Read-only URDF/FK and saved-contact analysis. No scene/model/device imports."""
import argparse,hashlib,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
import trimesh

class Geometry:
    def __init__(self,assets,cfg,names):
        self.assets=Path(assets);self.cfg=cfg;self.names=names
        self.tree=ET.parse(self.assets/'configs/rm65_ctag_reference/assembly.urdf').getroot()
        self.pad={}
        for side in ('Left','Right'):
            m=trimesh.load(self.assets/f'vendor/target_models_20260921/crt_ctag2f90d_gripper_visualization/meshes/{side}_Support_Link.STL')
            v=m.vertices[m.vertices[:,1]>.04];self.pad['ctag_'+side+'_Support_Link']=v[v[:,0]<v[:,0].min()+.001]
    def fk(self,q):
        poses={'base_link':np.eye(4)};poses['base_link'][:3,3]=self.cfg['temporary_assembly']['base_world_xyz_m']
        pending=list(self.tree.findall('joint'));values=dict(zip(self.names,q))
        while pending:
            before=len(pending)
            for j in pending[:]:
                parent=j.find('parent').get('link')
                if parent not in poses:continue
                o=j.find('origin');T=np.eye(4)
                T[:3,3]=np.fromstring(o.get('xyz','0 0 0'),sep=' ')
                T[:3,:3]=Rotation.from_euler('xyz',np.fromstring(o.get('rpy','0 0 0'),sep=' ')).as_matrix()
                R=np.eye(4)
                if j.get('type')!='fixed':R[:3,:3]=Rotation.from_rotvec(np.fromstring(j.find('axis').get('xyz'),sep=' ')*values[j.get('name')]).as_matrix()
                poses[j.find('child').get('link')]=poses[parent]@T@R;pending.remove(j)
            if len(pending)==before:raise ValueError('URDF_DISCONNECTED')
        return poses
    def centers(self,poses):return np.array([(v@poses[n][:3,:3].T+poses[n][:3,3]).mean(0) for n,v in self.pad.items()])

def read(p):return json.loads(p.read_text())
def rows(p):return [json.loads(s) for s in p.read_text().splitlines()]
def analyze(assets,archive,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);archive=Path(archive)
    results=[];curves={}
    for name in ('z30-opening0','z30-opening045','z40-opening0','z40-opening045'):
        folder=archive/name;raw=rows(folder/'contact_trace.jsonl')
        data=[x for x in raw if x['kind']=='PRE_CLOSURE' or x['phase']=='closure' and x['kind']=='AFTER_STEP_BEFORE_MONITOR']
        g=Geometry(assets,read(folder/'scene/assembly_config.json'),data[0]['state']['joint_names'])
        geometry=read(folder/'loaded_collision_geometry.json');series=[];errors=[];sweeps={n:[] for n in g.pad};pads={n:[] for n in g.pad}
        for row in data:
            s=row['state'];p=g.fk(s['qpos']);centers=g.centers(p);flange=p['Link6']
            errors.append(float(np.max(np.abs(centers-np.array(s['actual_pad_centers_world'])))))
            for n,v in g.pad.items():
                pads[n].append(v@p[n][:3,:3].T+p[n][:3,3])
                for sh in geometry[n]:
                    local=sh['local_pose'];vtx=np.array(sh['vertices'])*sh['scale']
                    R=Rotation.from_quat(np.roll(local[3:],-1)).as_matrix()
                    vtx=vtx@R.T+local[:3];sweeps[n].append(vtx@p[n][:3,:3].T+p[n][:3,3])
            c=centers.mean(0);local=flange[:3,:3].T@(c-flange[:3,3])
            cp=[z for ct in row['contacts'] if 'target_cube' in ct['names'] and any('Support_Link' in n for n in ct['names']) for z in ct['points']]
            series.append({'step':s['sim_step'],'t_s':(s['sim_step']-data[0]['state']['sim_step'])*.004,
              'master_rad':s['gripper_master_rad'],'command_target_rad':row['master_drive_target_rad'],
              'opening_from_actual_master_not_command':1+s['gripper_master_rad']/.91,
              'pad_gap_m':s['actual_pad_gap_m'],'pad_centers_world_m':centers.tolist(),'center_in_flange_m':local.tolist(),
              'center_world_m':c.tolist(),'bilateral':row['bilateral_contact'],
              'min_separation_m':min([z['separation_m'] for z in cp],default=None),
              'max_impulse_Ns':max([float(np.linalg.norm(z['impulse_api_Ns'])) for z in cp],default=None)})
        a,b=series[0],series[-1];p0=g.fk(data[0]['state']['qpos'])['Link6']
        articulation=p0[:3,:3]@(np.array(b['center_in_flange_m'])-a['center_in_flange_m'])
        total=np.array(b['center_world_m'])-a['center_world_m']
        bounds=lambda seq:np.array([np.concatenate(seq).min(0),np.concatenate(seq).max(0)]).tolist()
        latch=next((x for x in raw if x['kind']=='LATCH_AFTER_TARGET_CHANGE'),None)
        bilateral=next((x for x in series if x['bilateral']),None)
        results.append({'case':name,'label':'OFFLINE_ENGINEERING_MEASUREMENT','fk_actual_pad_max_error_m':max(errors),
          'center_displacement_xyz_m':total.tolist(),'articulation_at_fixed_initial_flange_xyz_m':articulation.tolist(),
          'arm_motion_and_cross_term_xyz_m':(total-articulation).tolist(),
          'start':a,'terminal':b,'first_bilateral':bilateral,'latch_step':latch['state']['sim_step'] if latch else None,
          'sampled_support_swept_AABB_world_m':{n:bounds(v) for n,v in sweeps.items()},
          'sampled_distal_pad_swept_AABB_world_m':{n:bounds(v) for n,v in pads.items()},
          'minimum_support_vertex_height_above_table_m':min(np.concatenate(v)[:,2].min() for v in sweeps.values()),
          'minimum_recorded_contact_separation_m':min(x['min_separation_m'] for x in series if x['min_separation_m'] is not None),
          'sweep_limits':'sampled actual closure until end/abort; AABB is an envelope, not signed object distance or proof all unsampled states are safe'})
        with (output/(name+'.json')).open('x') as f:json.dump(series,f,indent=2)
        curves[name]=series
    # Ideal mimic kinematics at the measured initial arm pose. No physics rollout.
    ref=archive/'z40-opening045';d=rows(ref/'contact_trace.jsonl')[0];g=Geometry(assets,read(ref/'scene/assembly_config.json'),d['state']['joint_names'])
    sweep=[]
    for opening in np.linspace(1,0,101):
        values=dict(zip(g.names,d['state']['qpos']));values[g.cfg['gripper_master']]=-.91*(1-opening)
        pending=[j for j in g.tree.findall('joint') if j.find('mimic') is not None];resolved={g.cfg['gripper_master']}
        while pending:
            progress=False
            for j in pending[:]:
                m=j.find('mimic')
                if m.get('joint') not in resolved:continue
                values[j.get('name')]=values[m.get('joint')]*float(m.get('multiplier','1'))+float(m.get('offset','0'))
                resolved.add(j.get('name'));pending.remove(j);progress=True
            if not progress:raise ValueError('MIMIC_CYCLE')
        q=[values[n] for n in g.names];c=g.centers(g.fk(q))
        sweep.append({'opening_command':float(opening),'master_rad':values[g.cfg['gripper_master']],
           'ideal_mimic_pad_gap_m':float(np.linalg.norm(c[0]-c[1])),'ideal_center_world_m':c.mean(0).tolist()})
    report={'scope':'READ_ONLY_KINEMATICS_AND_PRIOR_ENGINEERING_CONTACTS','real_model_calls':0,'hardware_calls':0,'new_physics_runs':0,
      'cases':results,'ideal_mimic_sweep':sweep,'ideal_sweep_semantics':'unloaded FK, fixed arm; not measured reachable closure under contact',
      'conclusion':'Closure articulation changes the pad-center TCP. Command opening is not the actual gap under contact latch. No universal Z40 claim; no threshold/control change justified by this measurement alone.'}
    with (output/'analysis.json').open('x') as f:json.dump(report,f,indent=2)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(11,8),constrained_layout=True)
    for name,series in curves.items():
        t=[x['t_s'] for x in series]
        axes[0,0].plot(t,[(x['center_world_m'][2]-series[0]['center_world_m'][2])*1000 for x in series],label=name)
        axes[0,1].plot([x['master_rad'] for x in series],[x['pad_gap_m']*1000 for x in series],label=name)
        axes[1,0].plot(t,[None if x['min_separation_m'] is None else x['min_separation_m']*1000 for x in series],label=name)
        axes[1,1].plot([x['pad_centers_world_m'][1][0]*1000 for x in series],[x['pad_centers_world_m'][1][2]*1000 for x in series],label=name)
    for ax,title in zip(axes.flat,['Pad-center dz (mm) / physical time (s)','Actual gap (mm) / actual master (rad)','Contact separation (mm) / time (s)','Right distal pad X/Z path (mm)']):ax.set_title(title);ax.grid(alpha=.3)
    axes[1,0].axhline(-2,color='r',ls='--');axes[0,0].legend(fontsize=8)
    fig.suptitle('ENGINEERING MEASUREMENT: unchanged controls / actual archived qpos')
    fig.savefig(output/'closure_geometry.png',dpi=150);plt.close(fig)
    print(json.dumps([{'case':x['case'],'dz_mm':x['center_displacement_xyz_m'][2]*1000,'articulation_dz_mm':x['articulation_at_fixed_initial_flange_xyz_m'][2]*1000,'fk_error_um':x['fk_actual_pad_max_error_m']*1e6} for x in results]))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assets',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();analyze(a.assets,a.archive,a.output)
