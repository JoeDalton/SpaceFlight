from direct.showbase.ShowBase import ShowBase
from panda3d.core import DirectionalLight, AmbientLight, Vec4, load_prc_file_data

from hud import HUD
from cockpit_view import CockpitView
from asteroid_field import AsteroidField
from player import Player
from integrator import Integrator
from skybox import Skybox

# load_prc_file_data("", """
#     gl-version 3 2
#     framebuffer-srgb true
#     basic-shaders-only #f
#     pbr-enable true
#     pbr-hdr true
#     pbr-tonemap true
# """)

# load_prc_file_data("", "notify-level-loader debug")

class MyApp(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)

        self.skybox = Skybox(self)

        self.integrator = Integrator(self)

        self.player = Player(self)

        self.hud = HUD(self)
        self.cockpit_view = CockpitView(self)

        self.asteroid_field = AsteroidField(self, n_asteroids=300, field_size=500)

        # self.environment = loader.loadModel("environment")
        # self.environment.reparentTo(render)

        # Directional light
        # dlight = DirectionalLight("dlight")
        # dlight.set_color(Vec4(1.0, 1.0, 0.9, 1))
        # dlnp = render.attach_new_node(dlight)
        # dlnp.set_hpr(-30, -60, 0)
        # render.set_light(dlnp)

        # # Ambient light
        # alight = AmbientLight("alight")
        # alight.set_color(Vec4(0.2, 0.2, 0.25, 1))
        # alnp = render.attach_new_node(alight)
        # render.set_light(alnp)


        self.oobe()
        # self.toggle_wireframe()

        # Initailaize all tasks in the correct order
        self.integrator.initialize_tasks() # Must come before all physics
        self.asteroid_field.initialize_tasks()


app = MyApp()
app.run()