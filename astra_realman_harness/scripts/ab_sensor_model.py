"""Run-scoped vanilla adapter using existing infer worker; no WorldHead/GT input."""
import base64,hashlib,io,json,math,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from platform_v1.research.contracts import clone,digest
from platform_v1.research.broker import output_contract
from platform_v1.research.jobs import ProcessJob
from platform_v1.research.model_context import observation_view,MAX_CONTEXT_BYTES
from platform_v1.research import pnp_proposal,chunk_plan
from sim_skills.full_pnp.infer_process import sandbox_command
from sim_skills.full_pnp.wire import strict_json
from sim_skills.full_pnp.protocol import validate_actions
from scripts.structured_outputs import encoded,validate_local

def add_rgbd_inputs(store,oid,folder,attachments,blobs):
    data={}
    for c in ('assembly','fixed','wrist'):
        z,valid,meta=store.depth(oid,c);good=valid & np.isfinite(z) & (z>0)
        vals=z[good];lo=float(vals.min()) if len(vals) else 0.;hi=float(vals.max()) if len(vals) else 1.
        grey=np.zeros(z.shape,np.uint8);grey[good]=1+np.rint(254*np.clip((z[good]-lo)/max(hi-lo,1e-9),0,1)).astype(np.uint8)
        pic=Image.fromarray(grey).convert('RGB');draw=ImageDraw.Draw(pic);draw.rectangle((0,0,pic.width,22),fill='black');draw.text((4,3),f'{c} optical Z: dark={lo:.4f}m bright={hi:.4f}m; black=invalid',fill='yellow')
        name='depth-'+c+'.png';pic.save(folder/name);raw=(folder/name).read_bytes();h=hashlib.sha256(raw).hexdigest();o=store.get(oid)
        attachments.append({'id':oid+':'+c+':depth:'+h,'camera':c,'file':name,'sha256':h,'source_sha256':meta['depth']['sha256'],'observation_id':oid,'captured_monotonic':o['captured_monotonic'],'execution_epoch':o['execution_epoch'],'sensor_kind':'depth_visualization','width':pic.width,'height':pic.height})
        blobs.append(base64.b64encode(raw).decode())
        grid=z[::16,::16];mask=good[::16,::16]
        data[c]={'unit':'m','convention':'opencv optical Z','sample_grid_uv':'u=16*column,v=16*row; original full RGB/K coordinates','values_m':[[round(float(v),4) if ok else None for v,ok in zip(row,m)] for row,m in zip(grid,mask)],'full_resolution':list(z.shape[::-1]),'valid_fraction':float(good.mean()),'depth_sha256':meta['depth']['sha256'],'validity_sha256':meta['validity']['sha256'],'aligned_RGB_sha256':meta['aligned_rgb_sha256'],'display_range_m':[lo,hi],'display_top_22_rows_legend':'numeric grid retains samples there; original raw depth retained host-side'}
    data['backprojection']='From original K: optical [X,Y,Z]=[(u-cx)*Z/fx,(v-cy)*Z/fy,Z]. SAPIEN local camera vector=[Z,-X,-Y]; rotate by camera world wxyz quaternion then add camera world xyz. No object extraction or identity is supplied by this shared sensor projection.'
    return data

def history_entry(observation,actions,feedback,answer=None):
    return {'observation':observation_view(observation,'action'),'image_hashes':{r['camera']:r['sha256'] for r in observation['rgb']},'actions':clone(actions),'feedback':{k:clone(feedback[k]) for k in ('kind','ok','error_code','completed_monotonic','execution_outcome','actions') if k in feedback},'own_model_answer':({k:clone(answer[k]) for k in ('decision','phase','reason','assumptions','unknowns') if k in answer} if answer else None),'historical_not_current':True}

def own_history_view(history):
    # Keep EVERY subtask event, no sliding-window loss of transport/release facts.
    rows=[]
    for event in history:
        o=event['observation'];state=o['state'];answer=event.get('own_model_answer') or {}
        rows.append({'observation_id':o['observation_id'],'execution_epoch':o['execution_epoch'],
            'captured_monotonic':o['captured_monotonic'],'pose_world_xyz_wxyz':[*state['actual_grasp_center_world'],*state['flange_pose_world'][3:]],
            'pad_gap_m':state['actual_pad_gap_m'],
            'actions':clone(event['actions']),
            'feedback':{k:clone(event['feedback'][k]) for k in ('kind','ok','error_code','completed_monotonic','execution_outcome') if k in event['feedback']},
            'action_completed':[x['completed'] for x in event['feedback'].get('actions',[])],
            'decision':answer.get('decision'),'phase':answer.get('phase')})
    return {'scope':'OWN_SUBTASK_PUBLIC_OBSERVATIONS_ONLY_HISTORICAL_NOT_CURRENT',
        'source_history_sha256':digest(history),'start':rows[0] if rows else None,'events':rows,
        'latest_model_reason':(history[-1].get('own_model_answer') or {}).get('reason') if history else None}

def add_history_images(store,history,folder,attachments,blobs):
    # Preserve the observable initial held state; retain release boundary + latest
    # in a second labelled panel. Six CURRENT RGB/depth attachments stay intact.
    if not history:return
    release=next((i for i,e in enumerate(history) if any(a['type']=='gripper' and a['opening']>=.5 for a in e['actions'])),None)
    indices=sorted(set(([max(0,release-1),release] if release is not None else [])+list(range(max(0,len(history)-2),len(history)))))
    groups=[[history[0]],[history[i] for i in indices if i!=0]]
    for j,group in enumerate(groups):
        if not group:continue
        panel=Image.new('RGB',(960,260*len(group)));sources=[]
        for row,event in enumerate(group):
            oid=event['observation']['observation_id'];o=store.get(oid)
            for i,c in enumerate(('assembly','fixed','wrist')):
                raw,meta=store.image(oid,c);im=Image.open(io.BytesIO(raw)).convert('RGB').resize((320,240));panel.paste(im,(i*320,row*260+20))
                sources.append({'observation_id':oid,'camera':c,'sha256':meta['sha256']})
            ImageDraw.Draw(panel).text((4,row*260+3),oid+(' SUBTASK START' if j==0 else ' OWN HISTORY')+' assembly/fixed/wrist',fill='white')
        name='history-'+str(j)+'.png';panel.save(folder/name);raw=(folder/name).read_bytes();h=hashlib.sha256(raw).hexdigest()
        first=group[0]['observation'];attachments.append({'id':first['observation_id']+':history:'+h,'camera':'history','file':name,'sha256':h,
            'observation_id':first['observation_id'],'captured_monotonic':first['captured_monotonic'],'execution_epoch':first['execution_epoch'],
            'width':panel.width,'height':panel.height,'historical':True,'source_images':sources});blobs.append(base64.b64encode(raw).decode())

def instruction():
    return pnp_proposal.transport_instruction(vanilla=True)

def run_vanilla(owner,store,observation,root,index,history,deadline,prepare_only=False):
    folder=root/('vanilla-%03d'%index);folder.mkdir(parents=True,exist_ok=False);inp=folder/'input_only';inp.mkdir();(folder/'runtime').mkdir()
    oid=observation['observation_id'];attachments=[];blobs=[]
    for i,c in enumerate(('assembly','fixed','wrist')):
        raw,meta=store.image(oid,c);name='image-%d.png'%i;(inp/name).write_bytes(raw)
        attachments.append({'id':oid+':'+c+':'+meta['sha256'],'camera':c,'file':name,'sha256':meta['sha256'],'source_sha256':meta['sha256'],'observation_id':oid,'captured_monotonic':observation['captured_monotonic'],'execution_epoch':owner.epoch});blobs.append(base64.b64encode(raw).decode())
    depth=add_rgbd_inputs(store,oid,inp,attachments,blobs);add_history_images(store,history,inp,attachments,blobs)
    binding={'episode_id':owner.id,'request_id':'vanilla-%03d'%index,'execution_epoch':owner.epoch,'observation_ids':[oid],'evidence_ids':[]}
    wire={'task':{'id':'RUN_TRANSPORT_PLACE_FROM_HELD','revision':'1','stage':'T2_TRANSPORT_PREPLACE'},'version':'astra.vanilla_sensor_input.v1','role':'vanilla_astra','binding':binding,'instruction':instruction(),'observations':{oid:observation_view(observation,'action')},'attachments':attachments,'sensor_depth':depth,'own_subtask_history':own_history_view(history),'public_plane':{'normal':[0,0,1],'offset':0,'source':'public table plane'},'origin_pose_world':[*observation['state']['actual_grasp_center_world'],*observation['state']['flange_pose_world'][3:]],'rules':'Only current public sensors and own history. All actions require unchanged Owner/IK/collision/contact/STOP admission. No WorldHead, semantic subagent, GT or other-condition results.'}
    local,schema,audit=output_contract(pnp_proposal.schema(),binding,[a['id'] for a in attachments],[],echo_binding=False)
    data=json.dumps(wire,sort_keys=True,separators=(',',':'),allow_nan=False).encode();assert len(data)<=MAX_CONTEXT_BYTES,'VANILLA_CONTEXT_TOO_LARGE_NO_DISPATCH'
    payload_dict={'context':wire,'images':blobs,'schema':schema,'authoritative_schema':local}
    from scripts.codex_astra_mac_bridge import validate_payload
    validate_payload(payload_dict)
    payload=json.dumps(payload_dict,sort_keys=True,allow_nan=False).encode()
    (inp/'wire.json').write_bytes(data);(inp/'payload.json').write_bytes(payload);(folder/'schema.json').write_bytes(encoded(schema));(folder/'authoritative_schema.json').write_bytes(encoded(local))
    for f in inp.iterdir():f.chmod(0o444)
    if prepare_only:return {'context':wire,'bytes':len(data),'schema':schema,'model_calls':0}
    cmd,env=sandbox_command(folder,owner.infer_config);end=min(time.monotonic()+90,deadline)
    cmd+=['--sha256',hashlib.sha256(data).hexdigest(),'--payload-sha256',hashlib.sha256(payload).hexdigest(),'--deadline',str(end),'--mode','qualification']
    started=time.monotonic();job=ProcessJob(folder,cmd,env,end,cooperative=True)
    result=None
    try:
        while result is None:owner.idle();result=job.poll()
    finally:
        if result is None:job.cancel('OWNER_ENDED')
    (folder/'WORKER_ENVELOPE.json').write_text(json.dumps({k:v for k,v in result.items() if k!='bytes'},indent=2))
    record=strict_json(result['bytes']);(folder/'MODEL_RECORD.json').write_text(json.dumps(record,indent=2));raw=record.get('raw');(folder/'RAW.json').write_text(raw or '')
    if result.get('cancel_reason') or result.get('return_code') or record.get('error') or record.get('return_code') or not raw:raise RuntimeError('VANILLA_MODEL_FAILURE:'+str(record.get('error')))
    parsed=strict_json(raw);validate_local(parsed,local,schema);(folder/'PARSED.json').write_text(json.dumps(parsed,indent=2))
    if owner.epoch!=binding['execution_epoch']:raise ValueError('VANILLA_STALE_EPOCH')
    refs={a['id'] for a in attachments};answer=parsed['result']
    if not set(parsed['evidence_refs'])<=refs:raise ValueError('VANILLA_UNSENT_EVIDENCE')
    seen=set()
    for claim in answer['additional_claims']:
        key=(claim['waypoint_index'],claim['precondition'],claim['scope'])
        if key in seen:raise ValueError('DUPLICATE_ADDITIONAL_CLAIM')
        seen.add(key)
        if answer['proposal'] and claim['waypoint_index']>len(answer['proposal']['waypoints']):raise ValueError('CLAIM_WAYPOINT')
        if claim['status']=='supported_by_input':
            if not any(a['id'] in claim['evidence_refs'] and a['observation_id']==oid for a in attachments):raise ValueError('CURRENT_OBSERVATION_REF_REQUIRED')
            if claim['precondition']=='measured_join' and claim['waypoint_index']!=1:raise ValueError('FUTURE_JOIN_NOT_VERIFIED')
        if not set(claim['evidence_refs'])<=set(parsed['evidence_refs']):raise ValueError('VANILLA_UNBOUND_CLAIM')
        if claim['status']=='supported_by_input' and (not claim['evidence_refs'] or claim['scope']!='current' or claim['precondition']=='owner_admission'):raise ValueError('VANILLA_UNVERIFIED_CLAIM')
        if claim['status']=='conflict' and answer['decision']=='planned':raise ValueError('VANILLA_CONFLICT')
    actions=[]
    if answer['decision']=='planned':
        if not answer['assumptions']:raise ValueError('VANILLA_ASSUMPTIONS')
        if answer['mode']=='coarse':
            if answer['proposal'] is None or answer['fine_actions']:raise ValueError('VANILLA_COARSE_MIX')
            way=answer['proposal']['waypoints'];assert 1<=len(way)<=4
            term=answer['proposal']['termination']['kind'];assert len(way)==4 or term=='stage_terminal'
            if term=='stage_terminal' and way[-1]['boundary_after']=='none':raise ValueError('UNJUSTIFIED_STAGE_TERMINAL')
            for i,x in enumerate(way,1):
                if x['boundary_after']!='none' and (i!=len(way) or term!='stage_terminal'):raise ValueError('CROSSED_STAGE_BOUNDARY')
                if x['index']!=i or x['prediction_dependencies']!=list(range(1,i)) or x['nominal_end_offset_s']!=2*i:raise ValueError('VANILLA_PREFIX_CONTRACT')
            actions=[{'type':x['type'],'pose':clone(x['pose'])} for x in way]
        else:
            if answer['phase'] not in ('grasp','trial_lift','place','release','retreat'):raise ValueError('PNP_FINE_PHASE')
            if answer['proposal'] is not None or not answer['fine_actions']:raise ValueError('VANILLA_FINE_MIX')
            actions=clone(answer['fine_actions'])
        prev=wire['origin_pose_world']
        for i,a in enumerate(actions):
            validate_actions([a])
            if a['type']=='move_pose':
                dist,rot=chunk_plan.pose_error(prev,a['pose']);assert dist<=.05+1e-9 and rot<=.15+1e-9,'VANILLA_STEP_BOUND';prev=a['pose']
                if answer['mode']=='coarse' and dist<1e-9 and rot<1e-9:raise ValueError('NOOP_PADDING')
                if answer['mode']=='coarse' and dist<.02 and rot<.05 and not (i==len(actions)-1 and answer['proposal']['termination']['kind']=='stage_terminal'):raise ValueError('VANILLA_COARSE_MIN_STEP')
            if a['type']=='gripper' and i!=len(actions)-1:raise ValueError('VANILLA_GRIPPER_BARRIER')
    elif answer['proposal'] is not None or answer['fine_actions']:raise ValueError('VANILLA_NONPLAN_ACTIONS')
    return {'parsed':parsed,'raw':raw,'actions':actions,'source':{'producer':'MODEL_RAW','role':'vanilla_astra','request_id':binding['request_id'],'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'binding':binding},'usage':record.get('usage'),'wall_s':time.monotonic()-started,'wire_bytes':len(data)}
