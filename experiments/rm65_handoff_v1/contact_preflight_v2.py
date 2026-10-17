"""Contact-dependent gripper safety. Never edits a goal, servo or collision rule.

The empty-space closing ramp is not a predicted contact trajectory. Arm paths
and other fixed motions retain their preflight; deferred closure is checked
against the measured shared scene before/after every 4ms physics step, including
settling. Only the original pad/object ACM exceptions are permitted.
"""
import json

VERSION='rm65.contact_dependent_preflight.v2'


def refresh_actual_scene(world,commands):
    # Preserve the holder selected by the original group-start prepare(). A new
    # pad contact during table closure is not by itself a carried-body claim.
    # Refresh existing holder-relative FCL data to the actual measured pose.
    holder=getattr(world,'collision_holder',None)
    if holder is not None:
        import mplib
        p=world.arms[holder].links['Link6'].get_pose();obj=world.cube.get_pose()
        world.collision_holder_relative_pose=mplib.Pose(p.p,p.q).inv()*mplib.Pose(obj.p,obj.q)
    for arm in world.arms.values():arm.motion.update_from_simulation()


def deferred_closing(plans):
    return [s for s,p in plans.items() if p.get('contact_mode')=='bilateral_hold' and p.get('closing')]


class ContactGuard:
    def __init__(self,world,folder,commands,sides):
        self.world=world;self.folder=folder;self.commands=commands;self.sides=sides
        self.log=(folder/'contact_guard_PRIVATE.jsonl').open('x',buffering=1)
        self.first_bilateral={s:None for s in sides};self.first_danger=None;self.samples=0

    def check(self,phase,index,latched):
        w=self.world
        # Refresh actual articulations/object and an existing holder-relative
        # FCL representation. It does not write a PhysX pose or add a holder.
        refresh_actual_scene(w,self.commands)
        pairs=[]
        for arm in w.arms.values():
            pairs.extend((c.object_name1,c.link_name1,c.object_name2,c.link_name2)
                for c in arm.motion.planning_world.check_collision())
        pairs=sorted(set(pairs))
        bilateral={s:w.arms[s].bilateral_pad_contact() for s in self.sides}
        for s,v in bilateral.items():
            if v and self.first_bilateral[s] is None:self.first_bilateral[s]=w.steps
        contacts=[]
        for c in w.scene.get_contacts():
            names=[b.entity.name for b in c.bodies]
            contacts.append({'names':names,'points':[{'position':p.position.tolist(),
                'separation':float(p.separation),'impulse':p.impulse.tolist(),
                'normal':p.normal.tolist() if hasattr(p,'normal') else None} for p in c.points]})
        row={'step':w.steps,'phase':phase,'ramp_index':index,'latched_sides':sorted(latched),
            'bilateral':bilateral,'forbidden_fcl_pairs':pairs,'native_contacts':contacts,
            'grippers':{s:{'actual_master_rad':float(w.arms[s].robot.get_qpos()[w.arms[s].master]),
                'servo_target_rad':float(w.arms[s].joints[w.arms[s].master].get_drive_target()[0]),
                'actual_pad_gap_m':w.arms[s].state()['actual_pad_gap_m']} for s in self.sides}}
        self.log.write(json.dumps(row)+'\n');self.samples+=1
        if pairs:
            self.first_danger=row
            raise RuntimeError('CONTACT_GUARD_COLLISION:'+str(pairs))

    def close(self):
        self.log.close()
        summary={'version':VERSION,'samples':self.samples,'deferred_closing_sides':self.sides,
            'first_bilateral_step':self.first_bilateral,'first_danger':self.first_danger,
            'execution_abort':getattr(self,'execution_abort',None),
            'last_physics_record_at_abort':getattr(self,'abort_physics_row',None),
            'empty_space_closure_is_not_safety_proof':True,'collision_exceptions_changed':False,
            'native_2mm_monitor_unchanged':True,'model_target_changed':False}
        (self.folder/'contact_guard_summary_PRIVATE.json').write_text(json.dumps(summary,indent=2)+'\n')
