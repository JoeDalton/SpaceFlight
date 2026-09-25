from __future__ import annotations

import gc
import logging
import sys
from collections.abc import Iterator
from typing import TYPE_CHECKING

from space_flight import DEBUG_DELETION, RECORD_GAME
from space_flight.actors.destructibles import Destructibles
from space_flight.ai.interactions import Interactions
from space_flight.fx.fire_smoke_fx import FireSmokePool
from space_flight.fx.spark_fx import SparkPool
from space_flight.game.collisions import CollisionSystem
from space_flight.game.integrator import Integrator
from space_flight.game.levels.dev_level import build_dev_level, build_dev_upfront
from space_flight.game.levels.intro_level import build_intro_level, build_intro_upfront
from space_flight.game.levels.race_level import build_race_level, build_race_upfront
from space_flight.game.record import Record
from space_flight.game.scenario import Scenario
from space_flight.game.time_keeping import (
    DelayedMethodManager,
    GameTimeManager,
    IntervalManager,
)
from space_flight.global_architecture.base_state import BaseState
from space_flight.ui.hud import HUD, TargetHUD
from space_flight.ui.input_context import FlightInputContext, HyperspaceInputContext

if TYPE_CHECKING:
    from direct.task import Task

LOGGER = logging.getLogger()

# When True, the hyperspace loading screen holds the tunnel once the level is
# ready and waits for the player to press the jump-out key, instead of dropping
# out automatically. Set False for an unattended (auto-dropping) loading screen.
WAIT_FOR_JUMP_KEY = True


class FlightState(BaseState):
    def __init__(self, app, headless: bool = False) -> None:
        """
        :param app: the ShowBase application
        :param headless: when True, skip every UI-only step (splash-era window
            calls have already been skipped by the caller; here it means no
            hyperspace overlay, no HUD, no level-end screen) so the level can
            be run with no window, for use in optimization loops.
        """
        super().__init__(app)
        self.headless = headless
        # Set by `end_level` once a level reaches a terminal outcome
        # ("victory", "defeat" or "death"); read by headless callers to know
        # when to stop stepping the simulation.
        self.outcome: str | None = None

    def enter(self) -> None:
        """
        Enter the flight state: apply this session's graphics settings, build
        the level, and run its reveal animation (skipped headless).
        """
        if self.headless:
            self._enter_headless()
            return

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

    def _enter_headless(self) -> None:
        """
        Enter the flight state with no window: build the level synchronously
        (no per-frame animation) and start the simulation immediately.

        Skips the hyperspace overlay and HUD entirely, since both require a
        real window (app.win) that does not exist headless.
        """
        self.initialize_game_structure()
        self.flight_context = None
        self.loading_overlay = None
        self._jump_context = None

        self._build_upfront()
        for _ in self._make_build_generator():
            pass
        self._build_generator = None

        self._on_build_complete()
        self.resume()

    def _jump_prompt(self) -> str:
        """
        Build the "press [key] to drop out of hyperspace" prompt from the
        active drop_hyperspace binding.

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

    def _build_upfront(self) -> None:
        """
        Run the level's up-front (on-black) build phase, if it has one. This is
        where the heavy objects are created and GPU-prepared before the animation.
        """
        selected_level = self.app.configuration["selected_level"]
        if selected_level == "Dev":
            return build_dev_upfront(game=self)
        elif selected_level == "Intro":
            return build_intro_upfront(game=self)
        elif selected_level == "Race":
            return build_race_upfront(game=self)
        else:
            raise NotImplementedError(f"Level `{selected_level}` does not exist.")

    def _make_build_generator(self) -> Iterator[str]:
        """
        Return a generator that yields once per build step for the rest of the
        level, advanced one step per frame during the animation.

        :return: A generator yielding a short label once per build step.
        """
        selected_level = self.app.configuration["selected_level"]
        if selected_level == "Dev":
            return build_dev_level(game=self)
        elif selected_level == "Intro":
            return build_intro_level(game=self)
        elif selected_level == "Race":
            return build_race_level(game=self)
        else:
            raise NotImplementedError(f"Level `{selected_level}` does not exist.")

    def _advance_build(self) -> bool:
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

    def _on_build_complete(self) -> None:
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

        # HUD (skipped headless: no window to draw on, and no use for it)
        if self.headless:
            self.hud = None
            self.target_hud = None
        else:
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
        # Not applicable headless: there is no overlay and no player to jump out.
        if WAIT_FOR_JUMP_KEY and not self.headless:
            self._jump_context = HyperspaceInputContext(
                app=self.app, on_trigger=self.loading_overlay.request_jump_out
            )
            self.app.input_context_stack.push(self._jump_context)

    def _on_reveal(self) -> None:
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

    def initialize_game_structure(self) -> None:
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
        self.fire_smoke_pool = FireSmokePool(game=self)
        self.spark_fx_pool = SparkPool(game=self)

        # Initialize Collision system and Destructibles
        self.destructibles = Destructibles()
        self.collision_system = CollisionSystem(game=self)

        # Initialize interaction compute between ships
        self.interactions = Interactions()

        # Initialize integrator.
        # The update must come before the physics computations :
        # (Player, bots, moving scene...)
        self.integrator = Integrator(game=self, max_state_size=5000)

        # Empty scenario by default; levels replace it with a loaded one.
        self.scenario = Scenario([])

        # Initialize records
        if RECORD_GAME:
            self.record = Record()
            self.record.new_time(time=self.game_time.get_current_time())

    def update_game_world_task(self, task: Task) -> int:
        """
        Advance the game world by one frame (a no-op while paused).

        :param task: The Panda3D task driving this per-frame update.
        :return: task.cont so the task keeps running next frame.
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
        # Handle the death of the player: send it into an out-of-control tumble
        # first, and only show the level-end screen once the death spin finishes.
        if self.player.pawn.health <= 0:
            if not self.player.is_dying:
                self.player.begin_death()
            elif self.player.death_spin_finished():
                self.end_level(outcome="death", text="Your ship was destroyed.")
        return task.cont

    def end_level(self, outcome: str, text: str = "") -> None:
        """
        Record the level's terminal outcome and, unless headless, show the
        level-end screen.

        :param outcome: one of "victory", "defeat" or "death"
        :param text: explanatory text shown beneath the outcome title
            (ignored headless)
        """
        self.outcome = outcome
        if not self.headless:
            self.app.state_manager.push(
                state_class=self.app.state_manager.LEVEL_END_STATE,
                outcome=outcome,
                text=text,
            )

    def update_scenario_task(self, task: Task) -> int:
        """
        Advance the scenario by one frame (a no-op while paused).

        :param task: The Panda3D task driving this per-frame update.
        :return: task.cont so the task keeps running next frame.
        """
        # Do nothing if paused
        if self.is_paused:
            return task.cont
        self.scenario.update(self)
        return task.cont

    def set_pause(self) -> None:
        """Open the pause menu, unless the game is already paused."""
        if not self.is_paused:
            self.app.state_manager.push(
                state_class=self.app.state_manager.PAUSE_MENU_STATE,
            )

    def pause(self) -> None:
        """Freeze game time and intervals while a menu is open."""
        if not self.is_paused:
            self.is_paused = True
            self.interval_manager.pause()
            self.game_time.pause()

    def resume(self) -> None:
        """Resume game time and intervals after a pause."""
        if self.is_paused:
            self.is_paused = False
            self.interval_manager.resume()
            self.game_time.resume()

    def exit(self) -> None:
        """
        Clean every object in the game session, in reverse order of creation
        """
        # Save records
        if RECORD_GAME:
            self.record.save()

        # Tear down the render-scale / AA pipeline, restoring direct-to-window
        # rendering before the scene it was compositing is destroyed. There is
        # no pipeline to tear down headless (it was never built).
        if not self.headless:
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
        self.fire_smoke_pool.clean()
        self.fire_smoke_pool = None
        self.spark_fx_pool.clean()
        self.spark_fx_pool = None
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

    def __del__(self) -> None:
        """Log when the flight state is garbage-collected (debug aid)."""
        if DEBUG_DELETION:
            LOGGER.info("Game instance deleted.")
