"""Read-only independent checks and figures for the finite chunk experiments."""
import argparse,gzip,hashlib,json,subprocess
from pathlib import Path
import numpy as np
from right_grip_hold_score import score


def rows(path):
    with path.open() as f:
        for line in f:
            if line.strip():yield json.loads(line)


def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent;e=a.evidence.resolve();out=e/'independent_analysis';out.mkdir(exist_ok=False)
    result={'real_model_requests':0,'production_bridge_connections':0,'not_model_task_success':True,'cases':{}}
    for name in ['held_tracking_01','held_tracking_02','fixed_orientation_release_03']:
        d=e/name;report=json.loads((d/'acceptance.json').read_text());data=list(rows(d/'physics.jsonl'));by={r['step']:r for r in data}
        item={'reported_status':report['status'],'error':report.get('error'),'last_step':data[-1]['step'],
            'max_reported_active_pad_penetration_mm':max([-p['separation']*1000 for r in data for c in r['contacts']
                if 'target_cube' in c['names'] and any('Support_Link' in x for x in c['names']) for p in c['points']]+[0]),
            'independent_scores_equal':{},'tracking':{}}
        for key in ['explicit_hold_7s','long_segment_independent_hold','bend_independent_hold']:
            if key not in report:continue
            s=report[key];lo,hi=s['range_steps'];check=score([r for r in data if lo<=r['step']<=hi],
                required_s=s['required_s'],reference=by[lo-1])
            assert check==s,(name,key);item['independent_scores_equal'][key]=True
        for file in sorted(d.glob('chunk_*/receipt.json')):
            r=json.loads(file.read_text());groups=r['groups'];tr=[t for g in groups for t in g.get('tracking',{}).values()]
            item['tracking'][file.parent.name]={'ok':r['ok'],'reason':r.get('reason'),
                'generated_groups_attempted':r['numeric_groups_attempted'],
                'max_cross_track_mm':1000*max((t['max_position_cross_track_m'] for t in tr),default=0),
                'max_orientation_endpoint_distance_deg':np.degrees(max((t['max_orientation_endpoint_distance_rad'] for t in tr),default=0)),
                'max_endpoint_position_error_mm':1000*max((t['endpoint'].get('position_error_m',0) for t in tr),default=0)}
        if (d/'single_long_segment_input.json').exists():
            proposal=json.loads((d/'single_long_segment_input.json').read_text())
            points=proposal['stages'][0]['actions'][0]['waypoints_world_wxyz'];assert len(points)==1
            case=next(c for c in report['cases'] if c['case']=='single_long_segment')
            r=json.loads((d/f"chunk_{case['chunk']:03d}/receipt.json").read_text())
            commands=[g['commands']['right']['pose'] for g in r['groups']];assert commands[-1]==points[0]
            start=np.array(by[case['start_step']]['arms']['right']['actual_grasp_center_world']);goal=np.array(points[0][:3]);v=goal-start
            xyz=np.array([x[:3] for x in commands]);line_error=np.linalg.norm(np.cross(xyz-start,v),axis=1)/np.linalg.norm(v)
            steps=np.linalg.norm(np.diff(np.vstack([start,xyz]),axis=0),axis=1)
            assert line_error.max()<1e-12 and steps.max()<=.005+1e-12
            item['single_target_evidence']={'caller_waypoints':1,'generated_nodes':len(commands),'endpoint_exact_numeric_values_preserved':True,
                'max_generated_node_line_error_m':float(line_error.max()),'max_generated_position_step_m':float(steps.max()),
                'source_of_all_generated_positions':'uniform linear interpolation between measured TCP and the single supplied endpoint'}
        if name=='held_tracking_01':
            old=root/'evidence/right_grip_repair_20261016/candidate1_no_native_damping_01/physics.jsonl'
            prefix=[x for x in rows(old) if x['step']<=data[-1]['step']]
            equal=len(prefix)==len(data) and all(x['object_pose']==y['object_pose'] and all(x['arms'][s]['qpos']==y['arms'][s]['qpos'] for s in ['left','right']) for x,y in zip(prefix,data))
            assert equal;item['left_close_physics_identical_to_legacy_prefix']=True
            item['meaning']='Explicit end-contact contract rejected an unchanged legacy table-close state; not a controller physics regression.'
        if name=='held_tracking_02':
            item['first_physical_stop']={'step':data[-1]['step'],'phase':data[-1]['phase'],
                'proposal':'held_user_bend_and_yaw_input.json','safety_threshold_unchanged_mm':2}
        if name=='fixed_orientation_release_03':
            item['normal_release']=report.get('release');item['empty_close_negative']=report.get('empty_close_negative')
        result['cases'][name]=item
        if name!='held_tracking_01':plot_case(out,name,d,data,report)
        del data,by
    # Historical result directories, criteria, assets and ledgers stay read-only.
    historical=root/'evidence/right_grip_repair_20261016'
    manifest=json.loads((historical/'verification/archive_manifest.json').read_text())
    assert all(hashlib.sha256((historical/k).read_bytes()).hexdigest()==v['sha256'] for k,v in manifest.items())
    tracked=subprocess.check_output(['git','ls-files'],cwd=root).decode().splitlines()
    protected={}
    for rel in tracked:
        if rel.endswith('ledger.json') or rel in ['process_criteria_v1.json','transfer_criteria_v1.json','workspace_criteria_v1.json','scene_v4_ready_transfer_1100.json','carry_collision.py','evaluate_process.py']:
            expected=subprocess.check_output(['git','show','d81c831:'+str(Path('experiments/rm65_handoff_v1')/rel)],cwd=root)
            actual=(root/rel).read_bytes();assert actual==expected,rel;protected[rel]=hashlib.sha256(actual).hexdigest()
    result['historical_integrity']={'prior_archive_files_unchanged':len(manifest),'protected_hashes':protected}
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


def plot_case(out,name,d,data,report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    start=next(c['start_step'] for c in report['cases'] if c['case']=='single_long_segment')
    data=[r for r in data if r['step']>=start]
    xyz=np.array([r['arms']['right']['actual_grasp_center_world'] for r in data]);t=np.array([r['sim_time_s'] for r in data])-start*.004
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    axs[0].plot(xyz[:,0],xyz[:,1],label='actual measured TCP',lw=1)
    for f in [d/'single_long_segment_input.json',d/'held_user_bend_and_yaw_input.json',d/'held_user_bend_fixed_orientation_input.json']:
        if not f.exists():continue
        p=json.loads(f.read_text())['stages'][0]['actions'][0]['waypoints_world_wxyz'];p=np.asarray(p)
        axs[0].scatter(p[:,0],p[:,1],marker='x',s=70,label=f.stem)
    axs[0].set(xlabel='world x (m)',ylabel='world y (m)',title='Specified endpoints and actual TCP');axs[0].axis('equal');axs[0].legend(fontsize=6)
    pen=np.array([max([-p['separation']*1000 for c in r['contacts'] if 'target_cube' in c['names'] and any('Support_Link' in x for x in c['names']) for p in c['points']]+[0]) for r in data])
    axs[1].plot(t,pen,lw=.8,label='reported active pad contact penetration');axs[1].axhline(2,color='r',ls='--',label='unchanged physical protection')
    axs[1].set(xlabel='physics time after tracking begins (s)',ylabel='penetration (mm)',title='Actual native contact samples');axs[1].legend(fontsize=7)
    fig.suptitle(name+' | engineering acceptance, NOT Astra');fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=150);plt.close(fig)


if __name__=='__main__':main()
