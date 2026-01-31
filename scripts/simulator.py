import numpy as np
from direct.showbase.ShowBase import ShowBase

from space_flight.ai.interactions import Interactions
from space_flight.bot import spawn_bot
from space_flight.collisions import CollisionSystem
from space_flight.destructibles import Destructibles
from space_flight.fx.sfx import SFX
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
        self.sfx = SFX(app=self)
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
        Initialize interaction compute between ships
        """
        self.interactions = Interactions(app=self)

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
            self,
            ship_type="a-wing",
            ini_position=np.array([0, -200, 0]),
            is_neutral=True,
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

        """
        Initialize dummy bots
        """

        wp_distance = 1000
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
        self.lead_bot = spawn_bot(
            app=self,
            name="lead_2",
            ship_type="tie-fighter",
            ini_position=np.array([0, 0, 0]),
            has_debug_trihedron=True,
            team=2,
        )
        self.lead_bot.navigator.set_waypoints(waypoints=bot2_waypoints, is_loop=True)

        self.chase_bot = spawn_bot(
            app=self,
            name="chase_1",
            ship_type="a-wing",
            ini_position=np.array([0, -50, 0]),
            has_debug_trihedron=True,
            team=1,
        )

        # for _ in range(7):
        #     spawn_bot(
        #         app=self,
        #         name="team_1",
        #         ship_type="a-wing",
        #         ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
        #         has_debug_trihedron=True,
        #         team=1,
        #     )
        # for _ in range(5):
        #     spawn_bot(
        #         app=self,
        #         name="team_2",
        #         ship_type="tie-fighter",
        #         ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
        #         has_debug_trihedron=True,
        #         team=2,
        #     )

        """
        DEBUG
        """
        # self.oobe()  # DEBUG
        # self.toggle_wireframe()  # DEBUG

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
