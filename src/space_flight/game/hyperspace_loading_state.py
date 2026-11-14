"""
Hyperspace loading-screen overlay state.

Plays a hyperspace jump animation while the level builds underneath it:

    into   (entering, fixed duration — nothing heavy runs, so it is smooth)
      -> inside (looping tunnel; the level is built here, one step per frame,
                 and the loop is held until the build finishes)
      -> outof  (dropping out, fixed duration; from REVEAL_START its black
                 background dissolves into the live game scene behind the
                 streaks), then pops.

The build is driven *by this state*: it calls build_step once per frame
during the inside phase only. Keeping all heavy work out of into (and
out of every cross-fade) means those parts stay smooth; the unavoidable
per-step stutter is confined to the looping tunnel, which has no fixed
endpoint and so never "ends too soon".

The drawing itself is done by a :class:`HyperspaceOverlay` with the opaque
:data:`LOADING_LOOK`, so the half-built world never shows through.

This state declares PAUSES_BELOW = False so the :class:`FlightState`
below it stays alive (its game tasks are created during the build and only
start simulating once we trigger the reveal, partway through outof).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from direct.gui.OnscreenText import OnscreenText
from panda3d.core import ClockObject, TextNode

from space_flight.fx.hyperspace_overlay import (
    INTO_DURATION,
    LOADING_LOOK,
    OUTOF_DURATION,
    HyperspaceOverlay,
)
from space_flight.global_architecture.base_state import BaseState

if TYPE_CHECKING:
    from direct.task import Task

    from space_flight.global_architecture.simulator import SpaceFlightSimulator

# Minimum time the looping tunnel is shown, even if the level loads instantly,
# so the "inside" phase never flashes by.
INSIDE_MIN_DURATION = 2.0
# Time into the outof phase at which the shader's black background starts
# dissolving into the live scene (0.35 * its 2.0s T_MAX; keep in sync with the
# `bg` smoothstep in hyperspace_outof.frag). The world is revealed from here.
REVEAL_START = 0.7

_TASK_NAME = "hyperspace_update"


class HyperspaceLoadingState(BaseState):
    """Animated hyperspace overlay shown while a level loads."""

    # Keep the FlightState below us alive while the animation plays.
    PAUSES_BELOW = False

    def __init__(
        self,
        app: SpaceFlightSimulator,
        build_step: Callable[[], bool] | None = None,
        on_build_complete: Callable[[], None] | None = None,
        on_reveal: Callable[[], None] | None = None,
        wait_for_key: bool = False,
        await_prompt: str = "",
    ):
        """
        Create the overlay and store the callbacks the level drives it with.

        :param app: the ShowBase application
        :param build_step: callable advancing the level build by one step;
            returns True while steps remain, False once the build is complete.
            Called once per frame during the inside phase. If None, the
            overlay behaves as if the build is already finished.
        :param on_build_complete: called once, on the frame the build finishes
            (still during inside). Good place to wire up input/HUD/tasks.
        :param on_reveal: called once, REVEAL_START seconds into the outof
            phase, when its black background starts dissolving into the world
            behind it. Good place to start the simulation.
        :param wait_for_key: when True, hold the looping tunnel after the build
            finishes (showing await_prompt) until :meth:`request_jump_out`
            is called, instead of dropping out of hyperspace automatically.
        :param await_prompt: message shown while waiting for the jump-out key;
            empty for no on-screen text.
        """
        super().__init__(app)
        self._build_step = build_step
        self._on_build_complete = on_build_complete
        self._on_reveal = on_reveal
        self._wait_for_key = wait_for_key
        self._await_prompt = await_prompt

    def enter(self):
        self._clock = ClockObject.getGlobalClock()
        self._overlay = HyperspaceOverlay(
            self.app.render2d, self.app.win, look=LOADING_LOOK
        )

        self._build_done = self._build_step is None
        self._popped = False
        # Wait-for-jump state (only used when wait_for_key is True).
        self._awaiting_jump = False
        self._jump_requested = False
        self._prompt: OnscreenText | None = None
        # Set once on_reveal has fired (outof's background is dissolving).
        self._revealing = False

        # Start on the "into" phase, fully opaque.
        self._overlay.show("into")

        self.app.taskMgr.add(self._update, _TASK_NAME)

    def exit(self):
        self.app.taskMgr.remove(_TASK_NAME)
        if self._prompt is not None:
            self._prompt.destroy()
            self._prompt = None
        self._overlay.destroy()

    # -- internals -----------------------------------------------------------

    def _step_build(self):
        """Advance the level build by one step during the inside phase."""
        if self._build_done:
            return
        # Without a build_step, _build_done starts True and we returned above.
        assert self._build_step is not None
        if not self._build_step():
            self._build_done = True
            if self._on_build_complete is not None:
                self._on_build_complete()

    def request_jump_out(self) -> bool:
        """
        Ask the overlay to drop out of hyperspace now.

        Only has an effect while the overlay is waiting for the jump-out key
        (wait_for_key); the outof transition then begins on the next
        frame. Wired to the player's input via the hyperspace input context.

        :return: True if the request was accepted, False if the overlay is not
            waiting yet (the request is ignored, not buffered)
        """
        if self._awaiting_jump:
            self._jump_requested = True
            return True
        return False

    def _enter_await(self):
        """Begin waiting for the jump-out key, showing the prompt message."""
        self._awaiting_jump = True
        if self._await_prompt:
            self._prompt = OnscreenText(
                text=self._await_prompt,
                pos=(0.0, -0.85),
                scale=0.06,
                fg=(1.0, 1.0, 1.0, 1.0),
                shadow=(0.0, 0.0, 0.0, 0.6),
                align=TextNode.ACenter,
                mayChange=False,
            )
            # Draw on top of the (opaque) tunnel quads.
            self._prompt.setBin("fixed", 100)
            self._prompt.setDepthTest(False)
            self._prompt.setDepthWrite(False)

    def _exit_await(self):
        """Stop waiting and remove the prompt message."""
        self._awaiting_jump = False
        if self._prompt is not None:
            self._prompt.destroy()
            self._prompt = None

    def _update(self, task: Task) -> int:
        self._overlay.update(self._clock.getDt())

        # Phase logic only once settled: no build steps run during a
        # cross-fade, so it stays smooth.
        if self._overlay.transitioning:
            return task.cont

        phase = self._overlay.phase
        phase_time = self._overlay.phase_time
        if phase == "into":
            if phase_time >= INTO_DURATION:
                self._overlay.cross_fade_to("inside")
        elif phase == "inside":
            # Build the level here, one step per frame, then leave once it is
            # done AND the tunnel has shown for at least INSIDE_MIN_DURATION.
            self._step_build()
            if self._build_done and phase_time >= INSIDE_MIN_DURATION:
                if not self._wait_for_key:
                    self._overlay.cross_fade_to("outof")
                else:
                    # Hold the (seamlessly looping) tunnel and prompt the player
                    # until request_jump_out() is called.
                    if not self._awaiting_jump:
                        self._enter_await()
                    if self._jump_requested:
                        self._exit_await()
                        self._overlay.cross_fade_to("outof")
        elif phase == "outof":
            if not self._revealing and phase_time >= REVEAL_START:
                # The shader's black background is now dissolving into the
                # scene: bring the world to life as it appears.
                self._revealing = True
                if self._on_reveal is not None:
                    self._on_reveal()
            if phase_time >= OUTOF_DURATION:
                self._pop_self()
                return task.done

        return task.cont

    def _pop_self(self):
        if self._popped:
            return
        self._popped = True
        # Popping triggers exit() (overlay cleanup) and resume() on the
        # FlightState below.
        self.app.state_manager.pop()
