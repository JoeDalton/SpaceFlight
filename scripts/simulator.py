import numpy as np
from direct.showbase import Audio3DManager
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (  # AntialiasAttrib,; load_prc_file_data,
    CollisionHandlerEvent,
    CollisionTraverser,
)

from space_flight.bot import Bot
from space_flight.dust_clouds import SpeedDust
from space_flight.ui.hud import HUD, TargetHUD
from space_flight.integrator import Integrator
from space_flight.lighting import Lighting
from space_flight.player import Player
from space_flight.trihedron import Trihedron
from space_flight.scenes.scenes import SceneAsteroids

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
        self.audio3d = Audio3DManager.Audio3DManager(
            self.sfxManagerList[0], self.camera
        )
        # music = self.loader.loadMusic(
        # DATAFILES_PATH / "sounds/music_Koyaanisqatsi.mp3"
        # )
        # music = self.loader.loadMusic(DATAFILES_PATH / "sounds/music_westworld.mp3")
        # music.setLoop(True)
        # music.setVolume(0.8)

        """
        Initialize Collision system
        """
        self.traverser = CollisionTraverser()
        self.traverser.showCollisions(self.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern("%fn-into-%in")
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
        self.scene = SceneAsteroids(app=self)
        # self.oobe()  # DEBUG
        # self.toggle_wireframe()  # DEBUG


        """
        Initialize player and ship
        """
        self.available_targets = [{None: ""}]
        self.player = Player(
        self, ship_type="a-wing", ini_position=np.array([0, -300, 0])
        )
        # self.player = Player(self, ship_type="tie-fighter")

        """
        Initialize dummy bots
        """
        self.bot1 = Bot(
            app=self,
            name="tie_1",
            ship_type="tie-fighter",
            ini_position=np.array([0, 0, -20]),
        )
        self.bot1.set_mode("idle")

        self.bot2 = Bot(
            app=self,
            name="tie_2",
            ship_type="tie-fighter",
            ini_position=np.array([0, 0, 0]),
        )
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
        Trihedron(app=self, parent=self.bot1.ship.node, scale=1)
        Trihedron(app=self, parent=self.bot2.ship.node, scale=1)

        """
        Speed dust effect
        """
        SpeedDust(app=self, colors=["orange", "pink", "yellow", "white"])

        """
        HUD
        """
        HUD(self)
        TargetHUD(app=self)

        """
        Initialize all tasks in the correct order
        """
        self.integrator.initialize_tasks()  # Must come before all physics
        self.player.initialize_move()
        self.bot1.initialize_move()
        self.bot2.initialize_move()
        self.scene.inititalize_move()

        """
        Launch music
        """
        # music.play()

        # self.render.setShaderAuto()
        # self.render.setAntialias(AntialiasAttrib.MAuto)

    def collision_task(self, task):
        self.traverser.traverse(self.render)
        return task.cont


app = MyApp()
app.run()
