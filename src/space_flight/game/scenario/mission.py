"""
Mission scripting.

A level scripts its events as a plain generator function, the mission body,
run by a :class:`Mission` one step per frame::

    def intro_mission(m: Mission) -> Iterator[None]:
        transports = m.spawn(TRANSPORTS)
        m.on(m.delay(transports.all_destroyed, 3),
             lambda: m.defeat("The convoy was lost."))
        yield from m.wait(10)
        m.spawn(FIRST_WAVE, target=transports)

The body ``yield from``s :meth:`Mission.wait` / :meth:`Mission.wait_until`
for its sequential parts, and registers reactive rules with
:meth:`Mission.on` for what must hold wherever the sequence currently is.
Conditions are zero-argument callables (see
:mod:`space_flight.game.scenario.conditions`); actions are zero-argument
callables too, typically lambdas calling the mission's action methods.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Iterator, Optional, Sequence

from space_flight.game.scenario.conditions import Condition, _After, _Delay, _Sustained
from space_flight.game.scenario.wave import WaveHandle, WaveSpec
from space_flight.ui.player_waypoints import PlayerWaypoints

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()

#: An action: called once when a rule fires.
Action = Callable[[], None]


class Trigger:
    """
    A reactive rule: run action when condition becomes true.

    :param condition: Checked once per frame
    :param action: Run when the condition holds
    :param once: Fire only the first time (otherwise every frame it holds)
    """

    def __init__(self, condition: Condition, action: Action, once: bool = True) -> None:
        self.condition = condition
        self.action = action
        self.once = once
        #: Whether the action has run at least once.
        self.fired = False
        self.cancelled = False

    def cancel(self) -> None:
        """Stop checking this rule."""
        self.cancelled = True

    @property
    def done(self) -> bool:
        return self.cancelled or (self.once and self.fired)

    def maybe_fire(self) -> None:
        if not self.done and self.condition():
            self.action()
            self.fired = True


class Mission:
    """
    Runs a level's mission: its body and jobs (generators stepped once per
    frame) and its reactive rules.

    FlightState owns one per level (``game.mission``) and calls
    :meth:`update` every unpaused frame.

    :param game: The game/flight state
    """

    def __init__(self, game: FlightState) -> None:
        self.game = game
        self.triggers: list[Trigger] = []
        self.jobs: list[Iterator] = []

    def now(self) -> float:
        """The game clock, in seconds."""
        return self.game.game_time.get_current_time()

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    def run(self, body: Callable[[Mission], Iterator[None]]) -> None:
        """Start a mission body: a generator function taking this mission."""
        self.schedule(body(self))

    def schedule(self, job: Iterator) -> None:
        """Step a generator once per frame until it finishes."""
        self.jobs.append(job)

    def update(self) -> None:
        """Advance by one frame: fire due rules, then step every job."""
        for trigger in list(self.triggers):
            trigger.maybe_fire()
        self.triggers = [t for t in self.triggers if not t.done]

        # A job scheduled during this loop (e.g. a spawn started by the body)
        # is appended to the list being iterated, so it takes its first step
        # this same frame.
        still_running = []
        for job in self.jobs:
            try:
                next(job)
                still_running.append(job)
            except StopIteration:
                pass
        self.jobs = still_running

    # ------------------------------------------------------------------
    # Waves
    # ------------------------------------------------------------------

    def wave(self, spec: WaveSpec) -> WaveHandle:
        """A handle to a not-yet-spawned wave (call its spawn() later)."""
        return WaveHandle(self, spec)

    def spawn(self, spec: WaveSpec, **kwargs) -> WaveHandle:
        """Spawn a wave now; kwargs as :meth:`WaveHandle.spawn`."""
        return self.wave(spec).spawn(**kwargs)

    # ------------------------------------------------------------------
    # Sequencing (yield from these in a mission body)
    # ------------------------------------------------------------------

    def wait(self, seconds: float) -> Iterator[None]:
        """Pause the body for seconds of game time."""
        deadline = self.now() + seconds
        while self.now() < deadline:
            yield

    def wait_until(
        self, condition: Condition, timeout: Optional[float] = None
    ) -> Iterator[None]:
        """
        Pause the body until condition holds, or timeout seconds pass.

        :return: (via ``yield from``) True if the condition was met, False on
            timeout
        """
        deadline = None if timeout is None else self.now() + timeout
        while not condition():
            if deadline is not None and self.now() >= deadline:
                return False
            yield
        return True

    # ------------------------------------------------------------------
    # Conditions that need the clock
    # ------------------------------------------------------------------

    def after(self, seconds: float) -> Condition:
        """True once seconds have passed from now."""
        return _After(self.now, seconds)

    def delay(self, condition: Condition, seconds: float) -> Condition:
        """True seconds after condition first became true (latches)."""
        return _Delay(self.now, condition, seconds)

    def sustained(self, condition: Condition, seconds: float) -> Condition:
        """True once condition has held for an unbroken run of seconds."""
        return _Sustained(self.now, condition, seconds)

    # ------------------------------------------------------------------
    # Reactive rules
    # ------------------------------------------------------------------

    def on(self, condition: Condition, action: Action, once: bool = True) -> Trigger:
        """
        Run action when condition becomes true, wherever the body currently is.

        :return: The rule (call its cancel() to retire it)
        """
        trigger = Trigger(condition, action, once)
        self.triggers.append(trigger)
        return trigger

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def hud(self, text: str, display_time_s: float = 5.0) -> None:
        """Show a message in the HUD event banner."""
        # There is no HUD headless, and no one to read it.
        if not self.game.headless:
            self.game.hud.set_event_text(text=text, display_time_s=display_time_s)

    def speech(
        self, text: str, speaker: Optional[str] = None, display_time_s: float = 6.0
    ) -> None:
        """Play a line of speech (audio stubbed), shown as a subtitle."""
        LOGGER.info("speech [%s]: %s", speaker or "narrator", text)
        if not self.game.headless:
            subtitle = f"{speaker}: {text}" if speaker else text
            self.game.hud.set_chatter_text(text=subtitle, display_time_s=display_time_s)

    def player_waypoints(
        self,
        points: Sequence[Sequence[float]],
        arrival_radius_m: Optional[float] = None,
        marker_radius_m: Optional[float] = None,
    ) -> None:
        """Give the player a route of targetable waypoints, replacing any
        previous one."""
        self.clear_player_waypoints()
        kwargs = {}
        if arrival_radius_m is not None:
            kwargs["arrival_radius_m"] = arrival_radius_m
        if marker_radius_m is not None:
            kwargs["marker_radius_m"] = marker_radius_m
        self.game.player_waypoints = PlayerWaypoints(self.game, points, **kwargs)

    def clear_player_waypoints(self) -> None:
        """Remove the player's waypoint route, if any."""
        route = getattr(self.game, "player_waypoints", None)
        if route is not None:
            route.clean()
            self.game.player_waypoints = None

    def end_level(self, outcome: str, text: str = "") -> None:
        """End the level ("victory", "defeat" or "death")."""
        self.game.end_level(outcome=outcome, text=text)

    def victory(self, text: str = "") -> None:
        self.end_level("victory", text)

    def defeat(self, text: str = "") -> None:
        self.end_level("defeat", text)
