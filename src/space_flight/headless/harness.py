"""
Headless simulation harness — runs :class:`FlightState` levels with no window,
audio device, menus, or HUD.

Intended for optimization loops (bot personality tuning, navigator strategy
search, ...) that need to evaluate many level runs quickly and
deterministically. One :class:`HeadlessHarness` owns a single, long-lived
:class:`SpaceFlightSimulator` (and its asset cache) for the whole loop; each
call to :meth:`HeadlessHarness.run_level` builds and tears down only the
level-specific :class:`FlightState`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from panda3d.core import ClockObject, loadPrcFileData

from space_flight.global_architecture.simulator import (
    SpaceFlightSimulator,
    StateManager,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState

# A fixed, deterministic simulation step (60 Hz), decoupled from wall-clock
# time via the non-real-time clock set up in HeadlessHarness.__init__.
DEFAULT_TIME_STEP = 1.0 / 60.0


class HeadlessHarness:
    """Owns one windowless :class:`SpaceFlightSimulator` reused across runs."""

    def __init__(self, time_step: float = DEFAULT_TIME_STEP, app=None) -> None:
        """
        :param time_step: fixed ``dt`` (seconds) applied to Panda3D's clock
            for every simulation step, so runs are deterministic and can go
            faster than real time.
        :param app: an existing headless :class:`SpaceFlightSimulator` to
            reuse instead of constructing a new one. ``ShowBase`` is a
            per-process singleton (a second instance raises), so callers that
            already hold one (e.g. a shared test fixture) must pass it in
            rather than letting the harness build its own.
        """
        self._owns_app = app is None
        if app is None:
            # Must be applied before the ShowBase constructor runs.
            loadPrcFileData("", "window-type none")
            loadPrcFileData("", "audio-library-name null")
            app = SpaceFlightSimulator(headless=True)
        self.app = app

        clock = ClockObject.getGlobalClock()
        clock.setMode(ClockObject.MNonRealTime)
        clock.setDt(time_step)

    @contextmanager
    def run_level(
        self, selected_level: str, max_steps: int = 100_000
    ) -> Iterator[FlightState]:
        """
        Load *selected_level* headlessly and step it until it reaches an
        outcome, yielding the live :class:`FlightState` for inspection, then
        clean it up.

        :param selected_level: level name, as read from
            ``app.configuration["selected_level"]`` (e.g. ``"Dev"``)
        :param max_steps: safety cap on simulation steps, in case the level
            never reaches an outcome (e.g. a deadlocked bot strategy)
        :return: a context manager yielding the :class:`FlightState`, stopped
            at the moment ``outcome`` was set (or ``max_steps`` was hit)
        """
        self.app.configuration["selected_level"] = selected_level
        self.app.state_manager.push(StateManager.GAME_STATE, headless=True)
        flight_state = self.app.state_manager.get_current()

        steps = 0
        while flight_state.outcome is None and steps < max_steps:
            self.app.taskMgr.step()
            steps += 1

        try:
            yield flight_state
        finally:
            self.app.state_manager.pop()

    def destroy(self) -> None:
        """
        Tear down the underlying app at the end of the optimization loop.

        No-op when the app was injected (not owned by this harness) — the
        caller that built it is responsible for its lifetime, e.g. a shared
        session-scoped test fixture used by several harnesses in turn.
        """
        if self._owns_app:
            self.app.destroy()
