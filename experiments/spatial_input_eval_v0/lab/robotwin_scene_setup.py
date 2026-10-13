"""Unmodified setup_scene excerpt, RoboTwin MIT, pinned 6dde57155eafa3e4ebf6ad1f93a7cf7d5d41a755.
Only this scene initialization is loaded; no robot/task/action imports.
"""
import sapien

def setup_scene(self, **kwargs):
    """
    Set the scene
        - Set up the basic scene: light source, viewer.
    """
    self.engine = sapien.Engine()
    # declare sapien renderer
    from sapien.render import set_global_config

    set_global_config(max_num_materials=50000, max_num_textures=50000)
    self.renderer = sapien.SapienRenderer()
    # give renderer to sapien sim
    self.engine.set_renderer(self.renderer)

    sapien.render.set_camera_shader_dir("rt")
    sapien.render.set_ray_tracing_samples_per_pixel(32)
    sapien.render.set_ray_tracing_path_depth(8)
    sapien.render.set_ray_tracing_denoiser("oidn")

    # declare sapien scene
    scene_config = sapien.SceneConfig()
    self.scene = self.engine.create_scene(scene_config)
    # set simulation timestep
    self.scene.set_timestep(kwargs.get("timestep", 1 / 250))
    # add ground to scene
    self.scene.add_ground(kwargs.get("ground_height", 0))
    # set default physical material
    self.scene.default_physical_material = self.scene.create_physical_material(
        kwargs.get("static_friction", 0.5),
        kwargs.get("dynamic_friction", 0.5),
        kwargs.get("restitution", 0),
    )
    # give some white ambient light of moderate intensity
    self.scene.set_ambient_light(kwargs.get("ambient_light", [0.5, 0.5, 0.5]))
    # default enable shadow unless specified otherwise
    shadow = kwargs.get("shadow", True)
    # default spotlight angle and intensity
    direction_lights = kwargs.get("direction_lights", [[[0, 0.5, -1], [0.5, 0.5, 0.5]]])
    self.direction_light_lst = []
    for direction_light in direction_lights:
        if self.random_light:
            direction_light[1] = [
                np.random.rand(),
                np.random.rand(),
                np.random.rand(),
            ]
        self.direction_light_lst.append(
            self.scene.add_directional_light(direction_light[0], direction_light[1], shadow=shadow))
    # default point lights position and intensity
    point_lights = kwargs.get("point_lights", [[[1, 0, 1.8], [1, 1, 1]], [[-1, 0, 1.8], [1, 1, 1]]])
    self.point_light_lst = []
    for point_light in point_lights:
        if self.random_light:
            point_light[1] = [np.random.rand(), np.random.rand(), np.random.rand()]
        self.point_light_lst.append(self.scene.add_point_light(point_light[0], point_light[1], shadow=shadow))

    # initialize viewer with camera position and orientation
    if self.render_freq:
        self.viewer = Viewer(self.renderer)
        self.viewer.set_scene(self.scene)
        self.viewer.set_camera_xyz(
            x=kwargs.get("camera_xyz_x", 0.4),
            y=kwargs.get("camera_xyz_y", 0.22),
            z=kwargs.get("camera_xyz_z", 1.5),
        )
        self.viewer.set_camera_rpy(
            r=kwargs.get("camera_rpy_r", 0),
            p=kwargs.get("camera_rpy_p", -0.8),
            y=kwargs.get("camera_rpy_y", 2.45),
        )
