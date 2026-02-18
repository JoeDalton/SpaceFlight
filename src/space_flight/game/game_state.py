import numpy as np

from space_flight.ai.interactions import Interactions
from space_flight.bot import spawn_bot
from space_flight.collisions import CollisionSystem
from space_flight.destructibles import Destructibles
from space_flight.fx import load_explosion_effect_pools
from space_flight.fx.sfx import SFX
from space_flight.game.time_keeping import (
    DelayedMethodManager,
    GameStates,
    GameTimeManager,
    IntervalManager,
)
from space_flight.global_architecture.base_state import BaseState
from space_flight.integrator import Integrator
from space_flight.player import Player
from space_flight.scenes.scenes import scene_factory
from space_flight.ui.hud import HUD, TargetHUD


class GameState(BaseState):
    def enter(self):
        """
        Initialize time keeping
        """
        self.game_time = GameTimeManager(app=self.app)
        self.interval_manager = IntervalManager(app=self.app)
        self.delayed_methods = DelayedMethodManager(app=self.app)

        """
        Initialize sound system
        """
        self.sfx = SFX(app=self.app)
        # music = self.loader.loadMusic(
        # DATAFILES_PATH / "sounds/music_Koyaanisqatsi.mp3"
        # )
        # music = self.loader.loadMusic(DATAFILES_PATH / "sounds/music_westworld.mp3")
        # music.setLoop(True)
        # music.setVolume(0.8)
        """
        Initialize special effects
        """
        load_explosion_effect_pools(app=self.app)

        """
        Initialize Collision system and Destructibles
        """
        self.destructibles = Destructibles(app=self.app)
        self.collision_system = CollisionSystem(app=self.app)

        """
        Initialize interaction compute between ships
        """
        self.interactions = Interactions()  # app=self.app)

        """
        Initialize integrator.
        Must come before the physic objects : (Player, bots, moving scene...)
        TODO: Priorities for task to dumb-proof
        """
        self.integrator = Integrator(self.app, max_state_size=5000)

        """
        Initialize player and ship
        """
        self.player = Player(
            self.app,
            ship_type="a-wing",
            ini_position=np.array([0, -200, 1]),
            is_neutral=False,
        )

        """
        Build scene
        `asteroids` or `lava_planet` or `debug_collisions`
        """
        self.set_background_color(0, 0, 0)
        self.scene = scene_factory(app=self.app, scene_name="lava_planet")

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
            app=self.app,
            name="lead_2",
            ship_type="tie-interceptor",
            ini_position=np.array([0, -50, 2]),
            has_debug_trihedron=True,
            team=2,
            debug_decisions=True,
        )
        self.lead_bot.navigator.set_waypoints(waypoints=bot2_waypoints, is_loop=True)

        self.chase_bot = spawn_bot(
            app=self.app,
            name="chase_1",
            ship_type="a-wing",
            ini_position=np.array([0, -2000, -0]),
            has_debug_trihedron=True,
            team=1,
            debug_decisions=True,
        )

        self.scape_goat = spawn_bot(
            app=self.app,
            name="scape_goat",
            ship_type="x-wing",
            ini_position=np.array([11.8, -200, 0]),
            has_debug_trihedron=True,
            team=0,
            debug_decisions=True,
        )

        for _ in range(7):
            spawn_bot(
                app=self.app,
                name="team_1",
                ship_type="x-wing",
                ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
                has_debug_trihedron=True,
                team=1,
            )
        for _ in range(5):
            spawn_bot(
                app=self.app,
                name="team_2",
                ship_type="tie-interceptor",
                ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
                has_debug_trihedron=True,
                team=2,
            )

        """
        DEBUG
        """
        # self.app.oobe()  # DEBUG
        # self.app.toggle_wireframe()  # DEBUG

        """
        HUD
        """
        HUD(self.app)
        TargetHUD(app=self.app)

        """
        Launch music
        """
        # music.play()

        # self.app.render.setShaderAuto()
        # self.app.render.setAntialias(AntialiasAttrib.MAuto)

        """
        Run game
        """
        self.game_time.state = GameStates.PLAYING

    def exit(self):
        print("Cleaning up game state")
