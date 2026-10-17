"""Offline-only native servo sampling. Never changes an actuator or model input."""
import json


def install(world):
    stream=(world.output/'contact_servo_readback_PRIVATE.jsonl').open('x',buffering=1)
    original_step=world.scene.step
    def read(side):
        a=world.arms[side];j=a.joints[a.master]
        return {'qpos':a.robot.get_qpos().tolist(),'engine_qvel':a.robot.get_qvel().tolist(),
            'master_index':a.master,'position_target':float(j.get_drive_target()[0]),
            'velocity_target':float(j.get_drive_velocity_target()[0]),
            'stiffness':j.get_stiffness(),'damping':j.get_damping(),'force_limit':j.get_force_limit(),
            'actual_drive_torque_Nm':None}
    def step():
        sides=[s for s,c in getattr(world,'pending_collision_commands',{}).items() if 'opening' in c]
        before={s:read(s) for s in sides}
        original_step()
        if sides:stream.write(json.dumps({'step':world.steps+1,'dt':world.dt,
            'before':before,'after':{s:read(s) for s in sides}})+'\n')
    world.scene.step=step
    original_close=world.close
    def close():
        try:return original_close()
        finally:stream.close()
    world.close=close
