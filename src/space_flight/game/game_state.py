import gc
import logging
import sys

from space_flight import DEBUG_DELETION
from space_flight.actors.destructibles import Destructibles
from space_flight.ai.interactions import Interactions
from space_flight.fx.explosion_fx import ExplosionPool
from space_flight.game.collisions import CollisionSystem
from space_flight.game.integrator import Integrator
from space_flight.game.levels.demo_level import build_demo_level
from space_flight.game.time_keeping import (
    DelayedMethodManager,
    GameTimeManager,
    IntervalManager,
)
from space_flight.global_architecture.base_state import BaseState
from space_flight.ui.hud import HUD, TargetHUD

LOGGER = logging.getLogger()


class GameState(BaseState):
    def enter(self):
        # TODO: Initialize game in a loading state stacked above self
        # TODO: Handle input management in enter/pause/resume methods
        self.initialize_game_structure()

        # TODO level choice
        build_demo_level(game=self)
        """
        DEBUG
        """
        # self.app.oobe()
        # self.app.toggle_wireframe()
        # self.app.setFrameRateMeter(True)
        # self.app.setSceneGraphAnalyzerMeter(True)

        """
        HUD
        """
        self.hud = HUD(game=self)
        self.target_hud = TargetHUD(game=self)

        """
        Graphics options
        """
        # self.app.render.setShaderAuto()
        # self.app.render.setAntialias(AntialiasAttrib.MAuto)

        """
        Run game
        """
        self.update_task = self.app.taskMgr.add(
            self.update_game_world_task, "update_game_world_task"
        )

        # TODO: This is an ugly hack to avoid having stupid dt at the second (?!)
        # time step of the sim. Fix it properly !
        self.app.taskMgr.doMethodLater(0.1, self.start, "start game")

    def initialize_game_structure(self):
        """
        Initializes all the necessary game objects
        """
        self.app.set_background_color(0, 0, 0)

        # Create a root node for the game
        self.root_node = self.app.render.attachNewNode("game_root_node")

        # Initialize a dictionary to hold actors and their update methods
        # {
        #     object_id: [method_to_run_1, method_to_run_2]
        # }
        self.method_lists = {}

        # Initialize a dictionary of temporary objects to clean at game exit
        # {
        #     object_id: object
        # }
        self.game_objects = {}

        # Initialize time keeping
        self.is_paused = True
        self.game_time = GameTimeManager(game=self)
        self.interval_manager = IntervalManager(game=self)
        self.delayed_methods = DelayedMethodManager(game=self)

        # Initialize sound system
        self.app.sfx.get_sounds_from_asset_manager()

        # Initialize special effects
        self.explosion_fx_pool = ExplosionPool(game=self)

        # Initialize Collision system and Destructibles
        self.destructibles = Destructibles()
        self.collision_system = CollisionSystem(game=self)

        # Initialize interaction compute between ships
        self.interactions = Interactions()

        # Initialize integrator.
        # The update must come before the physics computations :
        # (Player, bots, moving scene...)
        self.integrator = Integrator(game=self, max_state_size=5000)

    def start(self, task):
        self.resume()
        return task.done

    def update_game_world_task(self, task):
        """
        Updates the game world when it is not paused
        """
        # Do nothing if paused
        if self.is_paused:
            return task.cont

        # Handle delayed methods
        self.delayed_methods.update()
        # Kill destructibles whose health has reached zero
        self.destructibles.handle_deaths()
        # Find all collisions
        self.collision_system.update_collisions()
        # Compute interactions between actors
        # TODO Could be parallelized from python 3.14 ?
        self.interactions.update_interactions()
        # Advance time
        self.integrator.step()
        # Run the update tasks of all actors
        # TODO Could be parallelized from python 3.14 ?
        for method_list in self.method_lists.values():
            for method in method_list:
                method()

        return task.cont

    def set_pause(self):
        if not self.is_paused:
            self.app.state_manager.push(
                state_class=self.app.state_manager.PAUSE_MENU_STATE,
            )

    def pause(self):
        if not self.is_paused:
            self.is_paused = True
            self.interval_manager.pause()
            self.game_time.pause()

    def resume(self):
        if self.is_paused:
            self.is_paused = False
            self.interval_manager.resume()
            self.game_time.resume()

    def exit(self):
        """
        Clean every object in the game session, in reverse order of creation
        """
        # Remove HUD elements
        self.hud.clean()
        self.hud = None
        self.target_hud.clean()
        self.target_hud = None

        # Stop the task that updates the world
        self.app.taskMgr.remove(self.update_task)
        self.update_task = None
        # Drop references to the methods to run
        self.method_lists = None

        # Remove actors
        for actor in self.interactions.actors:
            actor.clean()
        self.interactions.actors = None

        # Remove player
        self.player.clean()
        self.player = None

        # Remove scene
        self.scene.clean()
        self.scene = None

        # Remove other game objects (mostly temporary objects)
        for key, object in self.game_objects.items():
            object.clean(remove_from_game_objects=False)
            self.game_objects[key] = None
        self.game_objects = None

        # Remove game structure
        self.integrator.clean()
        self.integrator = None
        self.interactions.clean()
        self.interactions = None
        self.collision_system.clean()
        self.collision_system = None
        self.destructibles.clean()
        self.destructibles = None
        self.explosion_fx_pool.clean()
        self.explosion_fx_pool = None
        self.delayed_methods.clean()
        self.delayed_methods = None
        self.interval_manager.clean()
        self.interval_manager = None
        self.game_time.clean()
        self.game_time = None

        # Remove the game's root node to make sure every graphics thing is deleted
        self.root_node.removeNode()
        if DEBUG_DELETION:
            LOGGER.info("Cleaned game")
            LOGGER.info(f"game nref = {sys.getrefcount(self)}")
            LOGGER.info(f"game references {gc.get_referrers(self)}")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Game instance deleted.")
