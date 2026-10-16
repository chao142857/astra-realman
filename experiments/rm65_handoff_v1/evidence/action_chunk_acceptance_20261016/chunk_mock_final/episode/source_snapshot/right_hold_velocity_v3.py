"""Versioned right contact-hold actuator setting, not a task/planning skill.

Validated for static 7s independent holding only. Large transport commands still
require physical validation; original safety guards remain mandatory.
"""
VERSION='right_contact_hold_master_damping0_v3'


def apply(arm):
    assert arm.side=='right'
    joint=arm.joints[arm.master]
    before={'stiffness':joint.get_stiffness(),'damping':joint.get_damping(),
        'force_limit':joint.get_force_limit(),'position_target':float(joint.get_drive_target()[0]),
        'velocity_target':float(joint.get_drive_velocity_target()[0])}
    joint.set_drive_property(before['stiffness'],0.,force_limit=before['force_limit'])
    record={'version':VERSION,'before':before,'after':dict(before,damping=joint.get_damping()),
        'target_changed':False,'torque_limit_increased':False,'measured_drive_torque':None}
    arm.log('right_hold_velocity_v3',record)
    return record


def install(world):
    arm=world.arms['right'];original=arm.latch_grasp_contact
    def latch():
        result=original();record=apply(arm)
        return dict(result,right_hold_controller=record)
    arm.latch_grasp_contact=latch
    return {'version':VERSION,'scope':'right master damping after ordinary bilateral contact latch only',
        'opening':'existing opening operation restores original drive settings',
        'target_or_planner_correction':False,'left_arm_unchanged':True}
