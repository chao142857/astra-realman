"""Short local skills under one coordinator. No simultaneous arm motions."""
from bimanual_demo.protocol import require

class Skills:
    def __init__(self,runtime):self.r=runtime
    def left_pick(self,a):
        r=self.r;require(r.state.phase=='left_pick','PICK_PHASE')
        r.move('left','source_approach',a);r.grip('left',1.,a)
        r.move('left','source_grasp',a);r.grip('left',.35,a)
        r.event('LEFT_HOLDING',a)
        r.move('left','source_lift',a)
    def left_present(self,a):
        r=self.r;require(r.state.handoff=='LEFT_HOLDING','PRESENT_REQUIRES_LEFT_HOLDING')
        r.move('left','left_handoff',a);r.event('LEFT_AT_HANDOFF',a)
        r.memory.store('pre_handoff',r.latest,a['object_id'],'Left presented object; pre handoff evidence',a['operation_id'])
    def right_receive(self,a):
        r=self.r
        if r.state.handoff=='LEFT_AT_HANDOFF':
            r.move('right','right_receive',a);r.event('RIGHT_AT_HANDOFF',a)
        if r.state.handoff=='RIGHT_APPROACH':
            record=r.grip('right',.35,a);r.state.right_grip_started(record)
        if r.state.handoff=='RIGHT_GRIP':r.event('RIGHT_HOLDING_CONFIRMED',a)
    def handoff(self,a):
        r=self.r
        require(r.state.handoff in ('LEFT_AT_HANDOFF','RIGHT_APPROACH','RIGHT_GRIP','RIGHT_HOLDING_CONFIRMED','LEFT_RELEASE'),'HANDOFF_PHASE')
        with r.recorder.timed(a['object_id'],'handoff_s'):
            self.right_receive(a)
            if r.state.handoff=='RIGHT_HOLDING_CONFIRMED':
                r.grip('left',1.,a);r.event('LEFT_RELEASED',a)
            if r.state.handoff=='LEFT_RELEASE':
                r.state.left_retract_started(a['operation_id'])
                r.move('left','left_retract',a);r.event('LEFT_CLEAR',a)
            require(r.state.handoff=='RIGHT_OWNS_OBJECT','HANDOFF_INCOMPLETE')
            r.recorder.objects[a['object_id']]['successful_handoff']=True
            r.memory.store('post_handoff',r.latest,a['object_id'],'Right ownership and left clearance confirmed',a['operation_id'])
    def right_place(self,a):
        r=self.r;obj=r.state.objects[a['object_id']]
        require(r.state.handoff=='RIGHT_OWNS_OBJECT' and obj['holder']=='right','PLACE_REQUIRES_OWNERSHIP_AND_CLEARANCE')
        require(a['destination']==obj['destination'],'WRONG_DESTINATION')
        r.move('right',a['destination']+'_approach',a);r.move('right',a['destination']+'_release',a)
        r.event('AT_DESTINATION',a);r.grip('right',1.,a);r.event('RIGHT_RELEASED',a)
        r.move('right','right_retract',a)
    def verify(self,a):
        self.r.event('SORT_CONFIRMED',a)
        self.r.recorder.objects[a['object_id']]['successful_sort']=True
        self.r.recorder.objects[a['object_id']]['finished']=__import__('time').monotonic()
    def recover(self,a):
        r=self.r
        with r.recorder.timed(a['object_id'],'recovery_s'):
            obs=r.observe(a['object_id']);e=r.observer.confirm('RECOVERY_ASSESSED',a['object_id'],a['operation_id'],r.state,obs)
            r.recorder.emit('RECOVERY_EVIDENCE',e);r.state.recover(e,a['operation_id'])
        # No automatic motion, release or retry. A NEW explicit high-level decision is required.
