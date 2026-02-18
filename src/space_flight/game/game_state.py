import numpy as np

from space_flight.ai.interactions import Interactions
from space_flight.bot import spawn_bot
from space_flight.collisions import CollisionSystem
from space_flight.destructibles import Destructibles
from space_flight.fx import load_explosion_effect_pools
from space_flight.fx.sfx import SFX
from space_flight.game.time_keeping import (
    DelayedMethodManager,
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
        self.app.set_background_color(0, 0, 0)
        """
        Initialize time keeping
        """
        self.is_paused = True
        self.game_time = GameTimeManager(game=self)
        self.interval_manager = IntervalManager(game=self)
        self.delayed_methods = DelayedMethodManager(game=self)

        """
        Initialize sound system
        """
        self.sfx = SFX(game=self)
        # music = self.loader.loadMusic(
        # DATAFILES_PATH / "sounds/music_Koyaanisqatsi.mp3"
        # )
        # music = self.loader.loadMusic(DATAFILES_PATH / "sounds/music_westworld.mp3")
        # music.setLoop(True)
        # music.setVolume(0.8)
        """
        Initialize special effects
        """
        load_explosion_effect_pools(game=self)

        """
        Initialize Collision system and Destructibles
        """
        self.destructibles = Destructibles()
        self.collision_system = CollisionSystem(game=self)

        """
        Initialize interaction compute between ships
        """
        self.interactions = Interactions()

        """
        Initialize integrator.
        The update must come before the physics computations :
        (Player, bots, moving scene...)
        """
        self.integrator = Integrator(game=self, max_state_size=5000)

        """
        Initialize a dictionary to hold actors and their update methods
        {
            object_id: [method_to_run_1, method_to_run_2]
        }
        """
        self.actor_methods = {}

        """
        Initialize player and ship
        """
        self.player = Player(
            game=self,
            ship_type="a-wing",
            ini_position=np.array([0, -200, 1]),
            is_neutral=False,
        )

        """
        Build scene
        `asteroids` or `lava_planet` or `debug_collisions`
        """

        self.scene = scene_factory(game=self, scene_name="lava_planet")

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
            game=self,
            name="lead_2",
            ship_type="tie-interceptor",
            ini_position=np.array([0, -50, 2]),
            has_debug_trihedron=True,
            team=2,
            debug_decisions=True,
        )
        self.lead_bot.navigator.set_waypoints(waypoints=bot2_waypoints, is_loop=True)

        # # self.chase_bot = spawn_bot(
        # #     app=self.app,
        # #     name="chase_1",
        # #     ship_type="a-wing",
        # #     ini_position=np.array([0, -2000, -0]),
        # #     has_debug_trihedron=True,
        # #     team=1,
        # #     debug_decisions=True,
        # # )

        # self.scape_goat = spawn_bot(
        #     app=self.app,
        #     name="scape_goat",
        #     ship_type="x-wing",
        #     ini_position=np.array([11.8, -200, 0]),
        #     has_debug_trihedron=True,
        #     team=0,
        #     debug_decisions=True,
        # )

        # for _ in range(7):
        #     spawn_bot(
        #         app=self.app,
        #         name="team_1",
        #         ship_type="x-wing",
        #         ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
        #         has_debug_trihedron=True,
        #         team=1,
        #     )
        # for _ in range(5):
        #     spawn_bot(
        #         app=self.app,
        #         name="team_2",
        #         ship_type="tie-interceptor",
        #         ini_position=np.random.uniform(-300, 300, 3) + np.array([0, 1000, 0]),
        #         has_debug_trihedron=True,
        #         team=2,
        #     )

        """
        DEBUG
        """
        # self.app.oobe()  # DEBUG
        # self.app.toggle_wireframe()  # DEBUG

        """
        HUD
        """
        HUD(game=self)
        TargetHUD(game=self)

        """
        Launch music
        """
        # music.play()

        # self.app.render.setShaderAuto()
        # self.app.render.setAntialias(AntialiasAttrib.MAuto)

        """
        Run game
        """
        self.app.taskMgr.add(self.update_game_world_task, "Update game world")
        self.is_paused = False

    def update_game_world_task(self, task):
        """
        Updates the game world when it is not paused
        """
        # Do nothing if paused
        if self.is_paused:
            # TODO pause menu
            return task.cont

        # Handle delayed methods
        self.delayed_methods.update()
        # Kill destructibles whose health has reached zero
        self.destructibles.handle_deaths()
        # Find all collisions
        self.collision_system.update_collisions()
        # Compute interactions between actors
        self.interactions.update_interactions()
        # Advance time
        self.integrator.step()
        # Run the update tasks of all actors
        for method_list in self.actor_methods.values():
            for method in method_list:
                method()

        return task.cont

    def exit(self):
        print("Cleaning up game state")
