"""Shared beliefs: every success/ownership transition requires bound observation evidence."""
import copy,time
from bimanual_demo.protocol import require,DESTINATIONS

class TaskState:
    def __init__(self,objects,revision):
        self.version=0;self.revision=copy.deepcopy(revision);self.active_object=None;self.phase='idle';self.handoff='IDLE'
        self.arms={'left':None,'right':None};self.completed_objects=[];self.failed_objects=[];self.events=[]
        self.objects={obj:{'object_id':obj,'subtype':subtype,'semantic_class':'unknown','destination':None,
                          'holder':'none','holder_valid':True,'stage':'unprocessed','visibility':'unknown','evidence':[],
                          'prediction':None,'confidence':None} for obj,subtype in objects.items()}
        self.fault=None;self.observation=None;self.observation_hashes=[];self.accepted_evidence=set()
    def snapshot(self):
        return copy.deepcopy({k:v for k,v in self.__dict__.items() if k!='accepted_evidence'})
    def bind_observation(self,obs):
        require(obs['revision']==self.revision,'OBSERVATION_REVISION')
        require(type(obs['timestamp']) in (int,float) and 0<=time.time()-obs['timestamp']<=60,'OBSERVATION_TIME')
        require(set(obs['arms'])=={'left','right'},'OBSERVATION_ARMS')
        self.observation=obs['observation_id'];self.observation_hashes=[i['sha256'] for i in obs['images']];self.arms=copy.deepcopy(obs['arms'])
    def admit(self,a):
        require(a['state_version']==self.version and a['revision']==self.revision,'STALE_DECISION')
        if self.fault:require(a['action'] in ('RECOVER','OBSERVE'),'RECOVERY_REQUIRED')
        obj=a['object_id']
        if obj is not None:require(obj in self.objects,'UNKNOWN_OBJECT')
        if a['action'] not in ('OBSERVE','SELECT_OBJECT'):require(obj==self.active_object,'ACTIVE_OBJECT_MISMATCH')
    def evidence(self,e,event,obj,op):
        require(e.get('source') in ('synthetic_observer','validated_observer','operator_observation'),'NOT_OBSERVATION_EVIDENCE')
        require(e.get('confirmed') is True,'EVENT_NOT_CONFIRMED:'+event)
        require(e.get('event')==event and e.get('object_id')==obj and e.get('operation_id')==op,'EVIDENCE_BINDING')
        require(e.get('revision')==self.revision and e.get('observation_id')==self.observation,'STALE_EVIDENCE')
        require(e.get('state_version')==self.version,'EVIDENCE_STATE_VERSION')
        require(type(e.get('timestamp')) in (int,float) and 0<=time.time()-e['timestamp']<=60,'EVIDENCE_TIME')
        require(e.get('evidence_id') not in self.accepted_evidence,'EVIDENCE_REPLAY')
        require(e.get('evidence_id') and e.get('camera_hashes') and e.get('description'),'EVIDENCE_SOURCE_REQUIRED')
        require(e['camera_hashes']==self.observation_hashes,'EVIDENCE_IMAGE_BINDING')
        self.accepted_evidence.add(e['evidence_id']);self.events.append(copy.deepcopy(e))
        self.objects[obj]['evidence'].append(copy.deepcopy(e))
    def select(self,a,e):
        obj=a['object_id'];require(self.active_object is None,'AN_OBJECT_IS_ACTIVE')
        require(self.objects[obj]['stage']=='unprocessed','ALREADY_PROCESSED')
        require(e.get('semantic_class')==a['semantic_class'],'CLASS_EVIDENCE_MISMATCH')
        self.evidence(e,'IDENTITY_CLASS_CONFIRMED',obj,a['operation_id'])
        x=self.objects[obj];x.update(semantic_class=a['semantic_class'],destination=DESTINATIONS[a['semantic_class']],visibility='visible')
        self.active_object=obj;self.phase='left_pick';self.version+=1
    def confirm(self,event,e,op):
        obj=self.active_object;require(obj is not None,'NO_ACTIVE_OBJECT');x=self.objects[obj]
        allowed={
          'LEFT_HOLDING':self.phase=='left_pick',
          'LEFT_AT_HANDOFF':self.handoff=='LEFT_HOLDING',
          'RIGHT_AT_HANDOFF':self.handoff=='LEFT_AT_HANDOFF',
          'RIGHT_HOLDING_CONFIRMED':self.handoff=='RIGHT_GRIP',
          'LEFT_RELEASED':self.handoff=='RIGHT_HOLDING_CONFIRMED',
          'LEFT_CLEAR':self.handoff=='LEFT_RETRACT',
          'AT_DESTINATION':self.handoff=='RIGHT_OWNS_OBJECT',
          'RIGHT_RELEASED':self.phase=='right_at_destination',
          'SORT_CONFIRMED':self.phase=='verify',
        }
        require(allowed.get(event,False),'EVENT_ORDER:'+event)
        if event=='SORT_CONFIRMED':require(e.get('destination')==x['destination'],'SORT_DESTINATION_EVIDENCE')
        self.evidence(e,event,obj,op)
        if event=='LEFT_HOLDING':x.update(holder='left',stage='left_grasped');self.handoff='LEFT_HOLDING';self.phase='left_present'
        elif event=='LEFT_AT_HANDOFF':x['stage']='handoff_ready';self.handoff=event;self.phase='handoff'
        elif event=='RIGHT_AT_HANDOFF':self.handoff='RIGHT_APPROACH'
        elif event=='RIGHT_HOLDING_CONFIRMED':self.handoff=event # ownership still left until release evidence
        elif event=='LEFT_RELEASED':self.handoff='LEFT_RELEASE';x.update(holder='right',stage='right_grasped')
        elif event=='LEFT_CLEAR':self.handoff='RIGHT_OWNS_OBJECT';self.phase='right_place'
        elif event=='AT_DESTINATION':x['stage']='sorting';self.phase='right_at_destination'
        elif event=='RIGHT_RELEASED':x['holder']='none';self.phase='verify'
        elif event=='SORT_CONFIRMED':
            x.update(stage='placed',visibility='visible');self.completed_objects.append(obj)
            if obj in self.failed_objects:self.failed_objects.remove(obj)
            self.active_object=None;self.phase='idle';self.handoff='IDLE'
        self.version+=1
    def left_retract_started(self,operation_id):
        require(self.handoff=='LEFT_RELEASE','LEFT_RETRACT_ORDER')
        self.events.append({'event':'LEFT_RETRACT','operation_id':operation_id,'source':'SKILL_EXECUTION_INTENT','object_result':'unconfirmed'})
        self.handoff='LEFT_RETRACT';self.version+=1
    def contradict(self,e,op):
        require(self.active_object is not None,'NO_ACTIVE_OBJECT')
        self.evidence(e,'BELIEF_CONTRADICTED',self.active_object,op)
        self.fail('OBSERVATION_CONTRADICTS_PRIOR_BELIEF')
    def right_grip_started(self,record):
        require(self.handoff=='RIGHT_APPROACH','RIGHT_GRIP_ORDER')
        require(record['arm_id']=='right' and record['kind']=='set_gripper','RIGHT_GRIP_RECORD')
        self.handoff='RIGHT_GRIP';self.version+=1
    def fail(self,reason):
        self.fault={'reason':reason,'handoff_at_fault':self.handoff,'phase_at_fault':self.phase}
        if self.active_object:
            x=self.objects[self.active_object];x['stage_before_failure']=x['stage'];x['stage']='failed';x['holder_valid']=False
            if self.active_object not in self.failed_objects:self.failed_objects.append(self.active_object)
        self.phase='RECOVER';self.version+=1
    def recover(self,e,op):
        require(self.fault is not None,'NOT_IN_RECOVERY');obj=self.active_object
        holder=e.get('holder');checkpoint=e.get('checkpoint')
        # Resume only at explicit independently observed checkpoints, never from a failed ACK.
        options={'LEFT_HOLDING':('left','left_present','left_grasped'),
                 'LEFT_AT_HANDOFF':('left','handoff','handoff_ready'),
                 'RIGHT_HOLDING_CONFIRMED':('left','handoff','handoff_ready'),
                 'LEFT_RELEASE':('right','handoff','right_grasped'),
                 'RIGHT_OWNS_OBJECT':('right','right_place','right_grasped')}
        require(checkpoint in options and holder==options[checkpoint][0],'RECOVERY_CHECKPOINT')
        if checkpoint=='RIGHT_HOLDING_CONFIRMED':require(e.get('both_holding') is True,'BOTH_HOLDING_EVIDENCE')
        self.evidence(e,'RECOVERY_ASSESSED',obj,op)
        x=self.objects[obj];x.update(holder=holder,holder_valid=True,stage=options[checkpoint][2]);self.handoff=checkpoint;self.phase=options[checkpoint][1]
        self.fault=None;self.version+=1
    def invalidate_revision(self,new_revision):
        self.revision=copy.deepcopy(new_revision)
        for x in self.objects.values():x.update(visibility='unknown',prediction=None)
        self.fail('CAMERA_LAYOUT_OR_CALIBRATION_CHANGED')
