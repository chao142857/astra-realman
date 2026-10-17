"""Opt-in left contact servo variant; not a grasp or task-planning skill.

Only after the existing bilateral latch: remove native master velocity damping.
Keep its measured-contact position target, preload, K and URDF effort limit.
Ordinary opening restores the existing K/D. No model target/path replacement.
This is an actuator variant, not a claim of a PhysX bug or measured torque.
"""
VERSION='left_contact_hold_native_damping0_v4'


def install(world):
    arm=world.arms['left'];original=arm.latch_grasp_contact
    def latch():
        result=original();j=arm.joints[arm.master]
        before={'stiffness':j.get_stiffness(),'damping':j.get_damping(),
            'force_limit':j.get_force_limit(),'target':float(j.get_drive_target()[0]),
            'velocity_target':float(j.get_drive_velocity_target()[0])}
        j.set_drive_property(before['stiffness'],0.,force_limit=before['force_limit'])
        record={'version':VERSION,'before':before,'after':dict(before,damping=j.get_damping()),
            'model_target_changed':False,'native_drive_torque_Nm':None}
        arm.log('left_contact_hold_v4',record)
        return dict(result,left_hold_controller=record)
    arm.latch_grasp_contact=latch
    return {'version':VERSION,'scope':'left master damping only after original bilateral contact latch',
        'right_controller_unchanged':True,'target_or_path_correction':False}
