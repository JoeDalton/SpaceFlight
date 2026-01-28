import numpy as np
from direct.showbase import Audio3DManager
from direct.showbase.ShowBase import ShowBase

from space_flight.bot import spawn_bot
from space_flight.collisions import CollisionSystem
from space_flight.destructibles import Destructibles
from space_flight.integrator import Integrator
from space_flight.player import Player
from space_flight.scenes.scenes import scene_factory
from space_flight.ui.hud import HUD, TargetHUD

# from panda3d.core import (AntialiasAttrib,; load_prc_file_data)


# load_prc_file_data("", """
#     gl-version 3 2
#     framebuffer-srgb true
#     basic-shaders-only #f
#     pbr-enable true
#     pbr-hdr true
#     pbr-tonemap true
# """)

# load_prc_file_data("", "notify-level-loader debug")


# TODO: Fix jittering by keeping player at (0,0,0) and moving everything around instead.


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
        Initialize Collision system and Destructibles
        """
        self.destructibles = Destructibles(app=self)
        self.collision_system = CollisionSystem(app=self)

        """
        Initialize integrator.
        Must come before the physic objects : (Player, bots, moving scene...)
        TODO: Priorities for task to dumb-proof
        """
        self.integrator = Integrator(self, max_state_size=5000)

        """
        Initialize player and ship
        """
        self.player = Player(
            self, ship_type="a-wing", ini_position=np.array([0, -200, 0])
        )
        # self.player = Player(
        #     self, ship_type="tie-fighter", ini_position=np.array([0, -20, 0])
        # )

        """
        Build scene
        `asteroids` or `lava_planet` or `debug_collisions`
        """
        self.set_background_color(0, 0, 0)
        self.scene = scene_factory(app=self, scene_name="asteroids")
        # self.oobe()  # DEBUG
        # self.toggle_wireframe()  # DEBUG

        """
        Initialize dummy bots
        """

        wp_distance = 150
        bot2_waypoints = [
            np.array([0, 0, 0]),
            np.array([0, wp_distance, 0]),
            np.array([0, wp_distance, wp_distance]),
            np.array([0, 0, wp_distance]),
            np.array([wp_distance, 0, wp_distance]),
            np.array([wp_distance, 0, 0]),
            np.array([0, 0, 0]),
            np.array([0, -wp_distance, 0]),
            np.array([0, -wp_distance, -wp_distance]),
            np.array([0, 0, -wp_distance]),
            np.array([-wp_distance, 0, -wp_distance]),
            np.array([-wp_distance, 0, 0]),
        ]
        self.bot2 = spawn_bot(
            app=self,
            name="tie_2",
            ship_type="tie-fighter",
            ini_position=np.array([0, 0, 20]),
            has_debug_trihedron=True,
        )
        self.bot2.navigator.set_waypoints(waypoints=bot2_waypoints, is_loop=True)

        spawn_bot(
            app=self,
            name="tie_1",
            ship_type="tie-fighter",
            ini_position=np.array([0, -50, 0]),
            has_debug_trihedron=True,
        )

        """
        HUD
        """
        HUD(self)
        TargetHUD(app=self)

        """
        Launch music
        """
        # music.play()

        # self.render.setShaderAuto()
        # self.render.setAntialias(AntialiasAttrib.MAuto)


app = MyApp()
app.run()
