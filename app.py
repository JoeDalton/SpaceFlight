from direct.showbase.ShowBase import ShowBase
from panda3d.core import load_prc_file_data

from panda3d.core import CollisionTraverser, CollisionHandlerEvent

from direct.showbase import Audio3DManager

import numpy as np

from hud import HUD, TargetHUD
from asteroid_field import AsteroidField
from player import Player
from integrator import Integrator
from skybox import Skybox
from trihedron import Trihedron
from lighting import Lighting
from bot import Bot
from dust_clouds import SpeedDust

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
        # music = self.loader.loadMusic("sounds/music_Koyaanisqatsi.mp3")
        # music = self.loader.loadMusic("sounds/music_westworld.mp3")
        # music.setLoop(True)
        # music.setVolume(0.8)
        

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
        self.integrator = Integrator(self, max_state_size=5000)

        """
        Build scene
        """
        self.set_background_color(0, 0, 0)
        self.lighting = Lighting(self)

        # self.skybox = Skybox(self, name="test")
        self.skybox = Skybox(self)
        
        # Asteroid field
        self.static_asteroid_field = AsteroidField(self, n_asteroids=2000, field_size=15000, is_moving=False)
        self.big_rotating_asteroid_field = AsteroidField(self, n_asteroids=20, scale_factor=10, field_size=15000, is_moving=True)
        self.rotating_asteroid_field = AsteroidField(self, n_asteroids=500, field_size=15000)

        # Drydock
        self.drydock = self.loader.load_model("models/star_trek_space_drydock/scene.gltf")
        self.drydock.reparent_to(self.render)
        self.drydock.set_pos(0, 8000, 50)
        self.drydock.set_scale(100, 100, 100)


        # # test asset
        # self.test_asset = self.loader.load_model("models/venator-class_star_destroyer/scene.gltf")
        # self.test_asset.reparent_to(self.render)
        # self.test_asset.set_pos(0, 1000, 50)
        # self.test_asset.set_scale(1000, 1000, 1000)

        """
        Initialize player and ship        
        """
        self.available_targets = [{None: ""}]
        # self.player = Player(self, ship_type="a-wing", ini_position=np.array([0, -300, 0]))
        self.player = Player(self, ship_type="tie-fighter")

        """
        Initialize dummy bots
        """
        self.bot1 = Bot(app=self, name="tie_1", ship_type="tie-fighter", ini_position=np.array([0, 0, -20]))
        self.bot1.set_mode("idle")
        
        self.bot2 = Bot(app=self, name="tie_2", ship_type="tie-fighter", ini_position=np.array([0, 0, 0]))
        self.bot2.set_mode("loop")
        wp_distance = 100
        bot_waypoints = [
            np.array([0, wp_distance, 0]),
            np.array([0, wp_distance, wp_distance]),
            np.array([0, 0, wp_distance]),
            np.array([wp_distance, 0, wp_distance]),
            np.array([wp_distance, 0, 0]),
        ]
        self.bot2.initialize_waypoints(waypoints=bot_waypoints)
        """
        Debug options
        """
        # self.oobe()
        # self.toggle_wireframe()
        HUD(self)
        # trihedron = Trihedron(app = self, parent=self.player.ship.node, scale = 1)
        Trihedron(app = self, parent=self.bot1.ship.node, scale = 1)
        Trihedron(app = self, parent=self.bot2.ship.node, scale = 1)

        """
        Speed dust
        """
        SpeedDust(app=self, colors=["orange", "pink", "yellow", "white"])

        """
        Add target HUD
        """
        TargetHUD(app=self)

        """
        Initialize all tasks in the correct order
        """
        self.integrator.initialize_tasks() # Must come before all physics
        self.player.initialize_move()
        self.bot1.initialize_move()
        self.bot2.initialize_move()
        self.rotating_asteroid_field.initialize_move()
        self.big_rotating_asteroid_field.initialize_move()

        """
        Launch music
        """
        # music.play()

    def collision_task(self, task):
        self.traverser.traverse(self.render)
        return task.cont



app = MyApp()
app.run()