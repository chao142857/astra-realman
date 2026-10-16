"""Independent replay scoring and comparisons; no decisions, no engine stepping."""
import argparse,json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from calibrate_right_contact import read_rows
from right_grip_hold_score import score
from evaluate_process import evaluate


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parent;data=root/'evidence/right_grip_repair_20261016'
    baseline=root/'evidence/full_handoff_restore_20261015/full_numeric_known_d3_urdf_effort_04'
    old=read_rows(baseline/'physics.jsonl');reference={r['step']:r for r in old}
    report={'real_generation_requests':0,'historical_scores_changed':False,'candidate_budget':3,'cases':{}}
    base_hold=[r for r in old if 7468<r['step']<=7968]
    report['original_failure_engineering_2s_score']=score(base_hold,reference=reference[7468])
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(3,1,figsize=(12,10),sharex=True)
    for folder in sorted(data.iterdir()):
        if not (folder/'result.json').exists():continue
        result=json.loads((folder/'result.json').read_text());rr=read_rows(folder/'physics.jsonl');idx={r['step']:r for r in rr}
        checks={}
        for name,stored in result['engineering_hold'].items():
            first,last=stored['range_steps'];samples=[r for r in rr if first<=r['step']<=last]
            actual=score(samples,required_s=stored['required_s'],reference=idx[7468])
            assert actual==stored,(folder.name,name)
            checks[name]=actual
        old_score=evaluate(folder);assert old_score==result['historical_process_score_unchanged']
        prefix=[r for r in rr if r['step']<=6698]
        def maximum(f):return max(float(np.max(abs(np.asarray(f(r))-f(reference[r['step']))))) for r in prefix)
        item={'result_status':result['status'],'error':result.get('error'),'earliest_failed_stage':result.get('attempted_stage'),
            'last_step':result['last_step'],'independent_historical_score_exact_match':True,
            'independent_engineering_hold':checks,'normal_opening_regression':result.get('normal_opening_regression'),
            'prefix_before_controller_change':{'samples':len(prefix),'left_qpos_max_diff':maximum(lambda r:np.array(r['arms']['left']['qpos'])),
                'right_qpos_max_diff':maximum(lambda r:np.array(r['arms']['right']['qpos'])),
                'cube_pose_max_diff':maximum(lambda r:np.array(r['object_pose']))},
            'first_10_archived_numeric_proposals_equal':all(json.loads(f.read_text())==json.loads((baseline/f.parent.name/f.name).read_text()) for f in folder.glob('reference_*/proposal_PRIVATE.json') if int(f.parent.name.split('_')[1])<10),
            'numeric_proposals_count':len(list(folder.glob('reference_*/proposal_PRIVATE.json'))),
            'old_full_process_score':old_score,'controller_change':result.get('controller_change'),
            'private_transport_reference':result['private_transport_reference'] if 'private_transport_reference' in result else 'original_single_targets'}
        report['cases'][folder.name]=item
        samples=[r for r in rr if 7018<=r['step']<=9218]
        x=[(r['step']-7018)*.004 for r in samples]
        axs[0].plot(x,[r['arms']['right']['actual_pad_gap_m']*1000 for r in samples],label=folder.name)
        axs[1].plot(x,[r['object_pose'][2]*1000 for r in samples])
        axs[2].plot(x,[int(r['bilateral_contact']['right']) for r in samples])
    axs[0].legend(fontsize=7);axs[0].set_ylabel('Actual representative gap (mm)');axs[1].set_ylabel('Cube z (mm)');axs[2].set_ylabel('Right bilateral contact');axs[2].set_xlabel('Simulation seconds since left release start')
    for ax in axs:ax.grid(alpha=.3)
    fig.tight_layout();fig.savefig(a.output/'hold_comparison.png',dpi=140);plt.close(fig)
    candidates={json.loads((f/'result.json').read_text())['candidate'] for f in data.iterdir() if (f/'result.json').exists()}
    assert len(candidates)<=3;report['distinct_controller_candidates_attempted']=sorted(candidates)
    (a.output/'independent_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:{'status':v['result_status'],'stage':v['earliest_failed_stage'],'hold':{n:s['pass'] for n,s in v['independent_engineering_hold'].items()}} for k,v in report['cases'].items()},indent=2))


if __name__=='__main__':main()
