from direct.showbase.ShowBase import ShowBase
from panda3d.core import load_prc_file_data

from panda3d.core import CollisionTraverser, CollisionHandlerEvent

from direct.showbase import Audio3DManager


from hud import HUD
from cockpit_view import CockpitView
from asteroid_field import AsteroidField
from player import Player
from integrator import Integrator
from skybox import Skybox
from trihedron import Trihedron
from lighting import Lighting

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

        """
        Initialize sound system
        """
        self.audio3d = Audio3DManager.Audio3DManager(self.sfxManagerList[0], self.camera)

        """
        Initialize Collision system
        """
        self.traverser = CollisionTraverser()
        self.traverser.showCollisions(self.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern('%fn-into-%in')
        self.taskMgr.add(self.collision_task, "collisionTask")

        """
        Initialize integrator
        """
        self.integrator = Integrator(self, max_state_size=20000)

        """
        Build scene
        """
        self.set_background_color(0, 0, 0)
        # self.skybox = Skybox(self, name="test")
        self.skybox = Skybox(self)
        self.asteroid_field = AsteroidField(self, n_asteroids=300, field_size=5000)
        self.lighting = Lighting(self)
        # self.venator_model = self.loader.load_model("models/ships/cis_dreadnaught/scene.gltf")
        # self.venator_model.reparent_to(self.render)
        # self.venator_model.set_pos(300, -300, 50)
        # self.venator_model.set_scale(200, 200, 200)

        """
        Initialize player and ship        
        """
        # self.player = Player(self, ship_name="a-wing")
        self.player = Player(self, ship_name="tie-fighter")
        
        """
        Debug options
        """
        # self.oobe()
        # self.toggle_wireframe()
        self.hud = HUD(self)
        # trihedron = Trihedron(app = self, parent=self.player.ship.node, scale = 1)

        """
        Initialize all tasks in the correct order
        """
        self.integrator.initialize_tasks() # Must come before all physics
        self.player.initialize_move()
        # self.asteroid_field.initialize_move()

    def collision_task(self, task):
        self.traverser.traverse(self.render)
        return task.cont



app = MyApp()
app.run()