"""Bounded RGB keyframes and explicit synthetic observation evidence."""
import base64,copy,hashlib,json,time,uuid
from pathlib import Path
from bimanual_demo.protocol import require
# Tiny fixture PNG; never presented as real laboratory imagery.
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
SLOTS=('previous_action_before','previous_action_after','last_clear_object_view','last_clear_destination_view','pre_handoff','post_handoff')
class Keyframes:
    def __init__(self,revision):self.revision=copy.deepcopy(revision);self.frames={};self.invalidated=[]
    def store(self,slot,obs,object_id,reason,operation_id=None):
        require(slot in SLOTS and obs['revision']==self.revision,'KEYFRAME_SLOT_OR_REVISION')
        require(reason and object_id,'KEYFRAME_PROVENANCE')
        self.frames[(object_id,slot)]={'object_id':object_id,'reason_selected':reason,'observation_id':obs['observation_id'],
             'timestamp':obs['timestamp'],'operation_id':operation_id,'revision':copy.deepcopy(self.revision),
             'images':copy.deepcopy(obs['images']),'kind':'historical','source':obs['source']}
    def invalidate(self,revision):
        self.invalidated.extend({'object_id':key[0],'slot':key[1],'reason':'REVISION_CHANGED'} for key in self.frames)
        self.frames.clear();self.revision=copy.deepcopy(revision)
    def projection(self,object_id):return [copy.deepcopy(v) for (obj,_),v in self.frames.items() if obj==object_id]
    def attachments(self,current,object_id,slot=None,max_images=4):
        require(current['revision']==self.revision,'CURRENT_REVISION')
        images=[dict(copy.deepcopy(i),kind='current',observation_id=current['observation_id']) for i in current['images']]
        # Four current views are never displaced by history; budget extensions require separate validation.
        if slot and len(images)<max_images:
            frame=self.frames.get((object_id,slot))
            if frame:
                require(frame['timestamp']<=current['timestamp'],'FUTURE_HISTORY')
                images.append(dict(copy.deepcopy(frame['images'][0]),kind='history',observation_id=frame['observation_id'],reason_selected=frame['reason_selected']))
        require(len(images)<=max_images,'ATTACHMENT_BUDGET')
        for i,image in enumerate(images):
            require(hashlib.sha256(Path(image['path']).read_bytes()).hexdigest()==image['sha256'],'IMAGE_HASH')
            image['input_index']=i+1
        return images

class SyntheticObserver:
    """Fixture scene oracle. Deliberately separate from SDK ACK; test events may be denied."""
    def __init__(self,root,arms,classes,revision):
        self.root=Path(root);self.arms=arms;self.classes=classes;self.revision=revision;self.fail_events=set();self.recovery=None
    def capture(self):
        oid=uuid.uuid4().hex;folder=self.root/'observations'/oid;folder.mkdir(parents=True)
        images=[];now=time.time()
        for role in ('left_wrist','additional_view','tabletop','overhead'):
            p=folder/(role+'.png');p.write_bytes(PNG)
            images.append({'camera_id':'synthetic-'+role,'role':role,'timestamp':now,'path':str(p),
                          'sha256':hashlib.sha256(PNG).hexdigest(),'observation_id':oid,'source':'SYNTHETIC_1PX_FIXTURE'})
        states={name:arm.read_state() for name,arm in self.arms.items()}
        obs={'observation_id':oid,'timestamp':now,'source':'SYNTHETIC_OBSERVER','revision':copy.deepcopy(self.revision),
             'images':images,'arms':states,'arm_sample_span_s':max(x['timestamp'] for x in states.values())-min(x['timestamp'] for x in states.values())}
        (folder/'observation.json').write_text(json.dumps(obs,indent=2)+'\n');return obs
    def confirm(self,event,obj,operation_id,state,obs):
        # This explicit oracle declaration is NOT inferred from read_state or gripper opening.
        e={'evidence_id':uuid.uuid4().hex,'source':'synthetic_observer','confirmed':event not in self.fail_events,
           'event':event,'object_id':obj,'operation_id':operation_id,'state_version':state.version,
           'revision':copy.deepcopy(self.revision),'observation_id':obs['observation_id'],'timestamp':time.time(),
           'camera_hashes':[i['sha256'] for i in obs['images']],
           'description':'Scripted synthetic event oracle; NOT real vision, contact sensing or physical validation.'}
        if event=='IDENTITY_CLASS_CONFIRMED':e['semantic_class']=self.classes[obj]
        if event=='SORT_CONFIRMED':e['destination']={'fruit':'plate','clutter':'box'}[self.classes[obj]]
        if event=='RECOVERY_ASSESSED':e.update(self.recovery or {})
        return e
