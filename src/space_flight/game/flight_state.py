import gc
import logging
import sys

from space_flight import DEBUG_DELETION, RECORD_GAME
from space_flight.actors.destructibles import Destructibles
from space_flight.ai.interactions import Interactions
from space_flight.fx.explosion_fx import ExplosionPool
from space_flight.game.collisions import CollisionSystem
from space_flight.game.integrator import Integrator
from space_flight.game.levels.dev_level import build_dev_level
from space_flight.game.levels.intro_level import build_intro_level, build_intro_upfront
from space_flight.game.record import Record
from space_flight.game.time_keeping import (
    DelayedMethodManager,
    GameTimeManager,
    IntervalManager,
)
from space_flight.global_architecture.base_state import BaseState
from space_flight.ui.hud import HUD, TargetHUD
from space_flight.ui.input_context import FlightInputContext, HyperspaceInputContext

LOGGER = logging.getLogger()

# When True, the hyperspace loading screen holds the tunnel once the level is
# ready and waits for the player to press the jump-out key, instead of dropping
# out automatically. Set False for an unattended (auto-dropping) loading screen.
WAIT_FOR_JUMP_KEY = True


class FlightState(BaseState):
    def enter(self):
        # Apply the saved render-scale / anti-aliasing settings for this
        # session (no-op when scale is 1.0 and AA is off). Done before any scene
        # rendering so the offscreen buffer and reflection sizing are in place.
        self.app.graphics_manager.begin_scene_render()

        # Initialize mandatory game elements (cheap; done up front).
        self.initialize_game_structure()
        self.flight_context = None

        # Phase 1 — on a black screen, BEFORE the animation: build the heavy
        # objects (player, ocean, cloud field) and force their one-time GPU
        # preparation now. A brief freeze on black is invisible, and it keeps the
        # one-time compile/upload spikes out of the animation.
        self.force_render()
        self._build_upfront()

        # Phase 2 — play the hyperspace animation; the rest of the level is built
        # incrementally during its looping "inside" phase. The overlay declares
        # PAUSES_BELOW = False (so we stay alive) and pulls build steps via the
        # callbacks below, then reveals the live scene.
        self._build_generator = self._make_build_generator()
        self._jump_context = None
        self.app.state_manager.push(
            state_class=self.app.state_manager.HYPERSPACE_LOADING_STATE,
            build_step=self._advance_build,
            on_build_complete=self._on_build_complete,
            on_reveal=self._on_reveal,
            wait_for_key=WAIT_FOR_JUMP_KEY,
            await_prompt=self._jump_prompt() if WAIT_FOR_JUMP_KEY else "",
        )
        self.loading_overlay = self.app.state_manager.get_current()

    def _jump_prompt(self):
        """
        Build the "press [key] to drop out of hyperspace" prompt from the
        active ``drop_hyperspace`` binding.

        :return: the prompt string shown by the loading overlay
        """
        input_type = self.app.bindings.get("input_type", "keyboard")
        key = (
            self.app.bindings.get("contexts", {})
            .get("hyperspace", {})
            .get(input_type, {})
            .get("drop_hyperspace", "")
        )
        label = key.upper() if key else "the jump key"
        return f"Press [{label}] to drop out of hyperspace"

    def _build_upfront(self):
        """
        Run the level's up-front (on-black) build phase, if it has one. This is
        where the heavy objects are created and GPU-prepared before the animation.
        """
        selected_level = self.app.configuration["selected_level"]
        if selected_level == "Intro":
            build_intro_upfront(game=self)
        # The Dev level is not split; it builds entirely in its generator below.

    def _make_build_generator(self):
        """
        Return a generator that yields once per build step for the rest of the
        level, advanced one step per frame during the animation.
        """
        selected_level = self.app.configuration["selected_level"]
        if selected_level == "Dev":
            # The dev level is not decomposed; run it in one (blocking) step.
            def _dev_build():
                build_dev_level(game=self)
                yield 1.0

            return _dev_build()
        elif selected_level == "Intro":
            return build_intro_level(game=self)
        else:
            raise NotImplementedError(f"Level `{selected_level}` does not exist.")

    def _advance_build(self):
        """
        Advance the level build by one step. Called once per frame by the
        loading overlay during its "inside" phase.

        :return: True while build steps remain, False once the build is done
        """
        try:
            next(self._build_generator)
        except StopIteration:
            return False
        return True

    def _on_build_complete(self):
        """
        Wire up the level once every build step has run. Called by the overlay
        (still during "inside"), so this work is hidden behind the animation.
        Does not start the simulation yet — that happens on reveal.
        """
        self._build_generator = None

        # Initialize input system (needs the player, created during the build)
        self.flight_context = FlightInputContext(
            game=self,
            player=self.player,
            radial_menu_factory=self.player.open_radial_target_menu,
        )
        self.app.input_context_stack.push(self.flight_context)

        # HUD
        self.hud = HUD(game=self)
        self.target_hud = TargetHUD(game=self)

        # Game tasks. They stay idle until is_paused is cleared by resume().
        self.game_world_task = self.app.taskMgr.add(
            self.update_game_world_task, "update_game_world_task"
        )
        self.scenario_task = self.app.taskMgr.add(
            self.update_scenario_task, "update_scenario_task"
        )

        # If the loading screen waits for a key, capture it via an input context
        # on top of the flight context (which it blocks until the world reveals).
        if WAIT_FOR_JUMP_KEY:
            self._jump_context = HyperspaceInputContext(
                app=self.app, on_trigger=self.loading_overlay.request_jump_out
            )
            self.app.input_context_stack.push(self._jump_context)

    def _on_reveal(self):
        """
        Start the simulation as the overlay fades out, so the world is alive
        the moment it becomes visible. Called by the overlay when the reveal
        fade begins.
        """
        # Drop the jump-out context so the flight context regains input as the
        # world appears.
        if self._jump_context is not None:
            self.app.input_context_stack.pop()
            self._jump_context = None
        self.loading_overlay = None
        self.resume()

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

        # Initialize scenario data
        self.scenario_data = {}

        # Initialize records
        if RECORD_GAME:
            self.record = Record()
            self.record.new_time(time=self.game_time.get_current_time())

    def update_game_world_task(self, task):
        """
        Updates the game world when it is not paused
        """
        # Do nothing if paused
        if self.is_paused:
            return task.cont

        # Create new time record
        if RECORD_GAME:
            self.record.new_time(time=self.game_time.get_current_time())

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
        # Handle the death of the player
        if self.player.pawn.health <= 0:
            self.app.state_manager.push(
                state_class=self.app.state_manager.DEATH_MENU_STATE,
            )
        return task.cont

    def update_scenario_task(self, task):
        """
        Updates the scenario when the game is not paused
        """
        # Do nothing if paused
        if self.is_paused:
            return task.cont
        self.update_scenario_method(game=self)
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
        # Save records
        if RECORD_GAME:
            self.record.save()

        # Tear down the render-scale / AA pipeline, restoring direct-to-window
        # rendering before the scene it was compositing is destroyed.
        self.app.graphics_manager.end_scene_render()

        # Remove HUD elements (may not exist if exiting before build finished)
        if getattr(self, "hud", None) is not None:
            self.hud.clean()
            self.hud = None
        if getattr(self, "target_hud", None) is not None:
            self.target_hud.clean()
            self.target_hud = None

        # Stop the tasks that update the world (only present once built)
        if getattr(self, "game_world_task", None) is not None:
            self.app.taskMgr.remove(self.game_world_task)
            self.game_world_task = None
        if getattr(self, "scenario_task", None) is not None:
            self.app.taskMgr.remove(self.scenario_task)
            self.scenario_task = None
        # Drop references to the methods to run
        self.method_lists = None

        # Remove actors
        for actor in self.interactions.live_actors:
            actor.clean()
        self.interactions.actors = None

        # Clean all session-specific contexts before removing actors they reference
        self.app.input_context_stack.clean()

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

        # Remove input system
        if self.flight_context is not None:
            self.app.input_context_stack.pop()
            self.flight_context = None

        # Remove the game's root node to make sure every graphics thing is deleted
        self.root_node.removeNode()
        if DEBUG_DELETION:
            LOGGER.info("Cleaned game")
            LOGGER.info(f"game nref = {sys.getrefcount(self)}")
            LOGGER.info(f"game references {gc.get_referrers(self)}")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Game instance deleted.")
