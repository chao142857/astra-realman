"""Bounded, hardware-free probe of the exact cuRobo backend and RM65 assets."""
import argparse,json,os,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'aspire_realman_phase2a/src'),str(ROOT/'aspire_realman_phase05/src'),str(ROOT/'.cache/ASPIRE/src'),str(ROOT/'.cache/curobo')]
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--planner',action='store_true');p.add_argument('--warp-cubin',action='store_true')
    p.add_argument('--expect-start-infeasible',action='store_true');p.add_argument('--search-samples',type=int,default=0)
    p.add_argument('--http-gate',action='store_true',help='negative fixture: native CAP -> actual GPU gate -> zero Stub ticks');a=p.parse_args()
    a.output.resolve().relative_to(ROOT);a.output.mkdir(parents=True,exist_ok=False)
    result={'scope':'SYNTHETIC_OFFLINE_ONLY','physical_commands_sent':0,'ok':False,'stages':{},'manifest':str(a.manifest)}
    started=time.perf_counter()
    try:
        import torch
        result['environment']={'torch':torch.__version__,'cuda_runtime':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),'capability':torch.cuda.get_device_capability(0)}
        torch.cuda.reset_peak_memory_stats()
        import warp as wp
        result['environment']['warp']=wp.__version__
        wp.config.kernel_cache_dir=str(ROOT/'.cache/warp')
        if a.warp_cubin:wp.config.cuda_output='cubin'
        import curobo._src.runtime as runtime
        runtime.cache_dir=str(ROOT/'.cache/curobo-runtime')
        from aspire_realman_phase2a.model import load_manifest,NAMES,ARMS
        from aspire_realman_phase2a.adapter import OfflineRealManAdapter
        from cap_harness.providers.curobo.client import CuRoboProvider
        from cap_harness.providers.curobo import service
        m=load_manifest(a.manifest);os.environ['ASPIRE_REALMAN_MODEL_MANIFEST']=str(a.manifest)
        adapter=OfflineRealManAdapter(m,a.output/'stub-ledger')
        state=adapter.get_robot_state();context=adapter.get_planning_context()
        payload=CuRoboProvider()._base_payload(state,context)
        from curobo.kinematics import Kinematics,KinematicsCfg
        from curobo.types import JointState
        t=time.perf_counter();kin=Kinematics(KinematicsCfg.from_robot_yaml_file(m['config']['path']))
        q=torch.tensor([sum([m['default_positions'][arm] for arm in ARMS],[])],device='cuda',dtype=torch.float32)
        fk=kin.compute_kinematics(JointState.from_position(q,joint_names=list(NAMES['left']+NAMES['right'])));torch.cuda.synchronize()
        poses={};errors={}
        for arm in ARMS:
            pose=fk.tool_poses.get_link_pose(m['end_effector_links'][arm])
            xyz=pose.position.detach().cpu().numpy().reshape(-1);quat=pose.quaternion.detach().cpu().numpy().reshape(-1)
            cpu=state.end_effector_poses[arm]
            import numpy as np
            errors[arm]={'position_m':float(np.linalg.norm(xyz-cpu.position)),'quaternion_abs_dot':float(abs(quat@cpu.quaternion_wxyz))}
            poses[arm]={'position':xyz.tolist(),'quaternion_wxyz':quat.tolist()}
        result['stages']['actual_gpu_fk']={'ok':all(v['position_m']<1e-5 and v['quaternion_abs_dot']>1-1e-5 for v in errors.values()),
            'elapsed_s':time.perf_counter()-t,'joint_names':kin.joint_names,'pose_comparison':errors,'poses':poses,'collision_spheres_shape':list(fk.robot_spheres.shape)}
        if a.planner:
            t=time.perf_counter();planner=service._planner(service.BaseRequest(**payload));torch.cuda.synchronize()
            feasibility=planner.graph_planner.check_samples_feasibility(q).detach().cpu().tolist()
            feasible=bool(np.asarray(feasibility).all())
            result['stages']['actual_gpu_planner']={'ok':feasible != a.expect_start_infeasible,'expected_feasible':not a.expect_start_infeasible,'elapsed_s':time.perf_counter()-t,'joint_names':planner.joint_names,'default_state_feasible':feasibility,
                'self_collision_check':True,'cross_arm_ignored_pairs':0}
            result['default_constraint_detail']=service._configuration_constraint_detail(planner,service._state(service.BaseRequest(**payload),planner))
            spheres=fk.robot_spheres.detach().cpu().numpy().reshape(-1,4)
            pairs=kin.config.self_collision_config.collision_pairs.detach().cpu().numpy().astype(int)
            params=kin.config.kinematics_config
            link_ids=params.link_sphere_idx_map.detach().cpu().numpy()
            link_names={v:k for k,v in params.link_name_to_idx_map.items()}
            overlap=spheres[pairs[:,0],3]+spheres[pairs[:,1],3]-np.linalg.norm(spheres[pairs[:,0],:3]-spheres[pairs[:,1],:3],axis=1)
            groups={};cross_count=0
            cross_mask=[]
            for indices,depth in zip(pairs,overlap):
                left,right=[link_names[int(link_ids[i])] for i in indices]
                cross=left.startswith('left_')!=right.startswith('left_');cross_mask.append(cross)
                if cross:cross_count+=1
                if depth<=0:continue
                key=left+' / '+right
                group=groups.setdefault(key,{'sphere_pairs':0,'max_penetration_m':0.})
                group['sphere_pairs']+=1;group['max_penetration_m']=max(group['max_penetration_m'],float(depth))
            result['default_sphere_overlap_groups']=groups;result['active_cross_arm_sphere_pairs']=cross_count
            # Query the actual cuRobo CUDA kernel with ALL original pairs intact.
            # Unit weight exposes its native squared-overlap diagnostic (not m).
            from curobo._src.cost.cost_self_collision import SelfCollisionCost
            from curobo._src.cost.cost_self_collision_cfg import SelfCollisionCostCfg
            cost=SelfCollisionCost(SelfCollisionCostCfg(weight=1.,self_collision_kin_config=kin.config.self_collision_config,store_pair_distance=True))
            cost.setup_batch_tensors(1,1);raw=cost.forward(fk.robot_spheres);torch.cuda.synchronize()
            pair_values=cost._pair_distance.detach().cpu().numpy().reshape(-1)
            cross_mask=np.array(cross_mask,bool)
            result['actual_gpu_pair_diagnostics']={'native_raw_cost':float(raw.item()),'native_metric':'squared sphere overlap, NOT meters',
                'cross_arm_pairs_evaluated':int(cross_mask.sum()),'cross_arm_positive_pairs':int((pair_values[cross_mask]>0).sum()),
                'cross_arm_max_native_metric':float(pair_values[cross_mask].max()),'same_arm_positive_pairs':int((pair_values[~cross_mask]>0).sum()),
                'original_pairs_unchanged':True}
            np.save(a.output/'actual-gpu-pair-values.npy',pair_values)
            if a.search_samples:
                if not 1<=a.search_samples<=512:raise ValueError('SEARCH_SAMPLE_BOUND_1_TO_512')
                rng=np.random.default_rng(20261020)
                lo=np.array([l['lower'] for arm in ARMS for l in m['joint_limits'][arm]])+.15
                hi=np.array([l['upper'] for arm in ARMS for l in m['joint_limits'][arm]])-.15
                candidates=rng.uniform(lo,hi,size=(a.search_samples,12))
                masks=planner.graph_planner.check_samples_feasibility(torch.tensor(candidates,device='cuda',dtype=torch.float32)).detach().cpu().numpy().reshape(-1).astype(bool)
                np.savez(a.output/'feasibility-search.npz',positions=candidates,feasible=masks)
                found=np.flatnonzero(masks)
                result['bounded_gpu_feasibility_search']={'seed':20261020,'samples':a.search_samples,'feasible_count':len(found)}
                if len(found):
                    selected=candidates[found[0]]
                    result['selected_feasible_positions']={arm:selected[i*6:(i+1)*6].tolist() for i,arm in enumerate(ARMS)}
            from curobo._src.geom.collision import wp_collision_kernel as wk
            result['warp_registration_overload_count']={name:len(getattr(getattr(wk,name),'user_overloads',{})) for name in ('is_obs_enabled','load_obstacle_transform','compute_local_sdf_with_grad')}
            if a.http_gate:
                sys.path.insert(0,str(ROOT/'aspire_realman_phase05/tests'))
                from http_support import loopback_server
                from aspire_realman_phase2a.runtime import build_runtime
                from cap_harness.contracts import SynchronizedTrajectory
                with loopback_server(service.app) as url:
                    provider=CuRoboProvider(url,max_retries=0,timeout_s=180)
                    native=build_runtime(m,a.output/'native-gate-ledger',provider)
                    try:
                        start=native.api.get_robot_state()
                        trajectory=SynchronizedTrajectory(joint_positions={arm:np.tile(start.joint_positions[arm],(2,1)) for arm in ARMS},
                            dt_s=.05,joint_names=NAMES,planner='NEGATIVE_CONTRACT_FIXTURE_NOT_A_PLANNED_TRAJECTORY',collision_aware=False,expected_start=start,embodiment='realman')
                        feedback=native.api.execute_trajectory(trajectory)
                        result['native_cap_gpu_execution_gate']={'ok':not feedback.ok and feedback.error.code.value=='planning_failed' and not native.adapter.transport.events,
                            'execution_ok':feedback.ok,'error':None if feedback.error is None else {'code':feedback.error.code.value,'message':feedback.error.message},
                            'gpu_checks':native.adapter.validator.records,'stub_ticks':len(native.adapter.transport.events),'hardware_commands_sent':0}
                    finally:native.close()
        result['ok']=all(v['ok'] for v in result['stages'].values()) and result.get('native_cap_gpu_execution_gate',{'ok':True})['ok']
        if a.http_gate:result['ok']=result['ok'] and result['actual_gpu_pair_diagnostics']['cross_arm_positive_pairs']>0
    except BaseException as exc:
        result['error']={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
        traceback.print_exc()
    finally:
        result['elapsed_s']=time.perf_counter()-started
        try:result['peak_allocated_bytes']=torch.cuda.max_memory_allocated();result['peak_reserved_bytes']=torch.cuda.max_memory_reserved()
        except Exception:pass
        (a.output/'result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['ok'] else 1)


if __name__=="__main__":main()
