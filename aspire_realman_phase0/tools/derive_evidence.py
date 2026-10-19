"""Derive small reviewable evidence from locally cached read-only source text.
Run only inside the new workspace. Original logs/assets are never changed.
"""
import hashlib,json,pathlib,subprocess
R=pathlib.Path(__file__).resolve().parents[2]
OUT=R/'aspire_realman_phase0/evidence'
x=json.loads((R/'.cache/deployed_files.json').read_text())
def write(name,data):
 (OUT/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
def entry(suffix):
 hits=[(p,v) for p,v in x.items() if p.endswith(suffix)]
 if len(hits)!=1:raise ValueError((suffix,len(hits)))
 p,v=hits[0];return p,v,json.loads(v['text'])
write('deployed_file_manifest.json',{p:{k:v for k,v in d.items() if k!='text'} for p,d in x.items()})
cal=[]
for name in ['three_camera_calibration_20261011.json','right_wrist_calibration_20261017.json']:
 p,v,d=entry('/'+name)
 for c in list(d.get('cameras',{}).values()) or [d]:
  cal.append({'serial':c['serial'],'role':c['role'],'parent_frame':c['parent_frame'],
  'optical_frame':'realsense:'+c['serial']+':color_optical',
  'T_parent_camera_optical':c['T_parent_camera_optical'],
  'evidence_status':'ESTIMATED_NOT_INDEPENDENTLY_CERTIFIED',
  'historical_validation_status':c.get('validation_status',c.get('status')),
  'current_mount_validity':'NOT_RECONFIRMED_20261020',
  'source_path':p,'source_sha256':v['sha256'],
  'metrics':c.get('metrics', {k:val for k,val in c.items() if 'rms' in k or 'validation' in k}),
  'execution_authorization':False})
write('camera_transform_inventory.json',{'convention':'T_destination_source, homogeneous column vectors, translation metres','cameras':cal,'common_world_transform':None,'physical_tcp_transforms':{'left':None,'right':None}})
runs={}
for p,d in x.items():
 if '/logs/parallel-arms-' not in p:continue
 run=p.split('/logs/')[1].split('/')[0]
 v=runs.setdefault(run,{'root':p.split('/'+run+'/')[0]+'/'+run,'raw_file_fingerprints':{}})
 v['raw_file_fingerprints'][p.split('/'+run+'/')[1]]={k:d[k] for k in ['bytes','sha256']}
 if p.endswith('/summary.json'):v['summary']=json.loads(d['text'])
 if p.endswith('/launch_manifest.json'):
  m=json.loads(d['text']);v['implementation_sha256']=m['implementation_sha256'];v['git_revision']=m['git_revision'];v['model']=m['model'];v['effort']=m['effort']
  v['actual_argv']=m['actual_argv'];v['camera_configuration']=m['camera_configuration']
impl=[v['implementation_sha256'] for v in runs.values()]
for v in runs.values():
 m=v.pop('implementation_sha256');v['implementation_count']=len(m);v['implementation_map_digest']=hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest();v['critical_source_hashes']={k:val for k,val in m.items() if k in ['arm_stack.py','left_executor.py','arm_worker.py','realman_api2_readonly.py','parallel_arms.py','parallel_history.py','real_hardware_gui.py','experiment_launch.py','astra_gui.py','camera_session.py','shared_cameras.py']}
write('historical_runs.json',{'scope':'Original root summaries/manifests plus one step-001 AFTER observation and model input per run; no image rereview or full trajectory audit this phase. Summaries are not independent physical success proof.','implementation_count':[len(m) for m in impl],'implementation_maps_equal':all(m==impl[0] for m in impl),'runs':runs})
p,v,d=entry('/parallel-arms-20261018T142729-853ffbe2/step-001/after/observation.json')
keys=['arm','joint_deg','ee_pose','work_frame','tool_frame','system_error','timestamp','frame_snapshot_stable','snapshot_atomic','gripper_state']
snapshot={'mode':'REPLAY_METADATA_ONLY','observation_id':d['observation_id'],'captured_at':d['captured_at'],
 'canonical_states':{a:{k:s[k] for k in keys} for a,s in d['canonical_states'].items()},
 'cameras':d['cameras'], 'provenance':{'source_path':p,'raw_file_sha256':v['sha256'],'kind':'field projection of one recorded AFTER observation; no assets copied; not a complete raw log'}}
write('replay_snapshot.json',snapshot)
up=R/'.cache/ASPIRE'
files=['AGENTS.md','README.md','pyproject.toml','scripts/start_system2_agent.sh','src/cap_harness/api.py','src/cap_harness/contracts.py','src/cap_harness/protocols.py','src/cap_harness/agent/embedded.py','src/cap_harness/agent/server.py','src/cap_harness/agent/mcp.py','src/cap_harness/agent/session.py','src/cap_harness/yam_real/adapter.py','src/cap_harness/yam_real/codec.py','src/cap_harness/providers/curobo/service.py','.agents/skills/cap-tool-usage/SKILL.md','.agents/skills/manipulation-tasks/SKILL.md']
write('upstream_lock.json',{'repository':'https://github.com/NVlabs/ASPIRE','commit':subprocess.check_output(['git','-C',str(up),'rev-parse','HEAD'],text=True).strip(),'release_commit_subject':'ASPIRE v1.0 release','python_requirement':'>=3.10,<3.13','files':{f:hashlib.sha256((up/f).read_bytes()).hexdigest() for f in files},'submodules_initialized':False,'model_weights_downloaded':False,'upstream_source_modified':False})
