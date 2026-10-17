"""Private offline fallback when Vulkan is unavailable; real PhysX, no images.

Only visual construction/observation are omitted in this process. URDF inertial
and collision parsing, joint drives, solver, IK, FCL and native guards run as
installed. Exact archived physical-state comparisons remain mandatory.
Never imported by the online episode or public executor.
"""
import copy
import json
from types import SimpleNamespace


def install():
    import sapien
    from sapien.wrapper.actor_builder import ActorBuilder
    from sapien.wrapper.urdf_loader import URDFLoader
    sapien.SapienRenderer=lambda:None
    def scene(engine,config=sapien.physx.PhysxSceneConfig()):
        sapien.physx.set_scene_config(config)
        return sapien.Scene([sapien.physx.PhysxCpuSystem()])
    sapien.Engine.create_scene=scene
    sapien.render.set_camera_shader_dir=lambda *a,**k:None
    sapien.Scene.set_ambient_light=lambda *a,**k:None
    sapien.Scene.add_directional_light=lambda *a,**k:None
    sapien.Scene.add_camera=lambda *a,**k:SimpleNamespace(set_pose=lambda *a:None)
    for name in ('add_plane_visual','add_box_visual','add_capsule_visual',
                 'add_cylinder_visual','add_sphere_visual','add_visual_from_file'):
        setattr(ActorBuilder,name,lambda *a,**k:None)
    original=URDFLoader._build_link
    def build(loader,link,builder):
        link=copy.copy(link);link.visuals=[]
        return original(loader,link,builder)
    URDFLoader._build_link=build


def omit_observations(cls):
    def observe(world,folder):
        folder.mkdir(parents=True,exist_ok=False)
        state={'rendering':'OMITTED_GPU_UNAVAILABLE','images':[],
               'sim_step':world.steps,'arms':{s:a.state() for s,a in world.arms.items()}}
        (folder/'NO_RGB_PHYSICS_ONLY.json').write_text(json.dumps(state,indent=2)+'\n')
        return state
    cls.observe=observe
    cls.start_video=lambda world:None
