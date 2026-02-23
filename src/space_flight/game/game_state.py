from space_flight.ai.interactions import Interactions
from space_flight.collisions import CollisionSystem
from space_flight.destructibles import Destructibles
from space_flight.fx import load_explosion_effect_pools
from space_flight.game.levels.demo_level import build_demo_level
from space_flight.game.time_keeping import (
    DelayedMethodManager,
    GameTimeManager,
    IntervalManager,
)
from space_flight.global_architecture.base_state import BaseState
from space_flight.integrator import Integrator
from space_flight.ui.hud import HUD, TargetHUD


class GameState(BaseState):
    def enter(self):
        self.initialize_game_structure()

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
        HUD(game=self)
        TargetHUD(game=self)

        """
        Graphics options
        """
        # self.app.render.setShaderAuto()
        # self.app.render.setAntialias(AntialiasAttrib.MAuto)

        """
        Run game
        """
        self.app.taskMgr.add(self.update_game_world_task, "Update game world")

        # TODO: This is an ugly hack to avoid having stupid dt at the second (?!)
        # time step of the sim. Fix it properly !
        self.app.taskMgr.doMethodLater(1.0, self.start, "start game")
        # self.resume()

    def initialize_game_structure(self):
        """
        Initializes all the necessary game objects
        """
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
        self.app.sfx.get_sounds_from_asset_manager()

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
        Initialize a list of objects to clean at game exit
        """
        self.game_objects = []

    def start(self, task):
        self.is_paused = False
        self.interval_manager.resume()
        self.game_time.resume()
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
        for method_list in self.actor_methods.values():
            for method in method_list:
                method()

        return task.cont

    def pause(self):
        if not self.is_paused:
            self.is_paused = True
            self.interval_manager.pause()
            self.game_time.pause()
            self.app.state_manager.change_state(
                new_state_class=self.app.state_manager.PAUSE_MENU_STATE,
                pause_current_state=True,
            )

    def resume(self):
        if self.is_paused:
            self.is_paused = False
            self.interval_manager.resume()
            self.game_time.resume()

    def exit(self):
        # TODO: methods to clean everything
        for object in self.game_objects:
            object.clean()
        print("Cleaning up game state")
