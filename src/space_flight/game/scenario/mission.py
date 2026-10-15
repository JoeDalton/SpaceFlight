"""
Mission scripting.

A level scripts its events as a plain generator function, the mission body,
run by a :class:`Mission` one step per frame::

    def mission3_mission(m: Mission) -> Iterator[None]:
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
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional, Sequence

from space_flight.ai.formation import Formation
from space_flight.game.scenario.conditions import (
    Condition,
    _After,
    _Delay,
    _Sustained,
    ids_of,
    pawns_of,
)
from space_flight.game.scenario.objectives import Objective, reaches
from space_flight.game.scenario.wave import WaveHandle, WaveSpec
from space_flight.ui.player_waypoints import PlayerWaypoints

if TYPE_CHECKING:
    from collections.abc import Generator

    from space_flight.actors.major_ship.hangar import Hangar
    from space_flight.actors.scan import ScanHandle
    from space_flight.game.flight_state import FlightState
    from space_flight.weapons.loadout import Loadout

LOGGER = logging.getLogger()

#: An action: called once when a rule fires.
Action = Callable[[], None]

#: Seconds between a mission ending the level and the level-end screen, so the
#: player sees the objectives' final state.
LEVEL_END_DELAY_S = 2.0


class Trigger:
    """
    A reactive rule: run action when condition becomes true.

    :param condition: Checked once per frame
    :param action: Run when the condition holds
    :param once: Fire only the first time (otherwise every frame it holds)
    """

    def __init__(self, condition: Condition, action: Action, once: bool = True):
        self.condition = condition
        self.action = action
        self.once = once
        #: Whether the action has run at least once.
        self.fired = False
        self.cancelled = False

    def cancel(self):
        """Stop checking this rule."""
        self.cancelled = True

    @property
    def done(self) -> bool:
        return self.cancelled or (self.once and self.fired)

    def maybe_fire(self):
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

    def __init__(self, game: FlightState):
        self.game = game
        self.triggers: list[Trigger] = []
        self.jobs: list[Iterator] = []
        #: The objectives shown on the HUD, in the order they were given
        self.objectives: list[Objective] = []
        #: The outcome the mission is ending on, once it is (see end_level)
        self.ending: Optional[str] = None

    def now(self) -> float:
        """The game clock, in seconds."""
        return self.game.game_time.get_current_time()

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    def run(self, body: Callable[[Mission], Iterator[None]]):
        """Start a mission body: a generator function taking this mission."""
        self.schedule(body(self))

    def schedule(self, job: Iterator):
        """Step a generator once per frame until it finishes."""
        self.jobs.append(job)

    def update(self):
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

    def spawn(self, spec: WaveSpec, **kwargs: Any) -> WaveHandle:
        """Spawn a wave now; kwargs as :meth:`WaveHandle.spawn`."""
        return self.wave(spec).spawn(**kwargs)

    def launch(
        self,
        hangar: Hangar,
        fighter_type: str,
        count: Optional[int] = None,
        target: Any = None,
        name: Optional[str] = None,
        formation: Optional[str] = "arrowhead",
        formation_scale_m: float = Formation.FIGHTER_SCALE_M,
        loadout: Optional[Loadout] = None,
    ) -> WaveHandle:
        """
        Launch fighters from a hangar as a wave, filled as they leave the bay
        (see :meth:`WaveHandle.launch_from`).

        :param hangar: The hangar to launch from (e.g.
            ``isd.pawns()[0].hangars[0]``), stocked by the level
        :param fighter_type: The fighter model, one of the hangar's stock
        :param count: How many fighters (the hangar's group size by default)
        :param target: Who the fighters attack (see :func:`pawns_of`),
            resolved as each one launches
        :param name: The wave's name (by default the hangar's and the type's)
        :param formation: The fighters' formation shape: "arrowhead",
            "diamond", "around_diamond", or None for none (the first fighter
            out leads)
        :param formation_scale_m: Spacing of its slots
        :param loadout: The fighters' weapons; None for their default loadout
        :return: The fighters' wave
        :raises KeyError: if the hangar's stock has no fighter_type
        """
        spec = WaveSpec(
            name=name or f"{hangar.name}_{fighter_type}",
            ship_model=fighter_type,
            size=hangar.group_size if count is None else count,
            team=hangar.team,
            formation=formation,
            formation_scale_m=formation_scale_m,
            loadouts={} if loadout is None else {fighter_type: loadout},
        )
        return self.wave(spec).launch_from(hangar, target=target)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self, who: Any, contraband: bool = False, **kwargs: Any) -> ScanHandle:
        """
        Make every pawn of who scannable by the player, starting now.

        :param who: See :func:`~space_flight.game.scenario.conditions.pawns_of`
        :param contraband: What the scans reveal
        :param kwargs: Tuning, as :class:`ScanHandle`
        :return: The scans' handle, whose state methods are conditions
        """
        # Imported here: actors.scan itself imports this package (conditions)
        from space_flight.actors.scan import ScanHandle

        return ScanHandle(self, who, contraband=contraband, **kwargs)

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
    ) -> Generator[None, None, bool]:
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
    # Objectives
    # ------------------------------------------------------------------

    def objective(
        self,
        text: str,
        done: Optional[Condition] = None,
        failed: Optional[Condition] = None,
        progress: Optional[Callable[[], int]] = None,
        goal: Optional[int] = None,
    ) -> Objective:
        """
        Add an objective to the HUD checklist, from now.

        It only shows the player what to do: ending the level is still the
        mission's call (:meth:`victory`, :meth:`defeat`).

        :param text: What to do, kept short
        :param done: Ticks it once true (by default, progress reaching goal)
        :param failed: Fails it once true, unless already ticked
        :param progress: A live count towards goal, shown as "(n/goal)", e.g.
            ``wave.destroyed_count`` or :meth:`kills`
        :param goal: The count that completes it
        :return: The objective (call its complete(), fail() or remove())
        """
        objective = Objective(self, text, progress=progress, goal=goal)
        if done is None and progress is not None and goal is not None:
            done = reaches(progress, goal)
        if done is not None:
            objective.rules.append(self.on(done, objective.complete))
        if failed is not None:
            objective.rules.append(self.on(failed, objective.fail))
        self.objectives.append(objective)
        return objective

    # ------------------------------------------------------------------
    # Kills
    # ------------------------------------------------------------------

    def kills(self, victims: Any = None, by_player: bool = False) -> Callable[[], int]:
        """
        A live kill counter, e.g. an objective's progress.

        :param victims: Whose deaths count (see
            :func:`~space_flight.game.scenario.conditions.ids_of`), read on each
            call so a wave still spawning is counted in full; everyone by default
        :param by_player: Only count the player's kills
        :return: A zero-argument callable giving the count
        """

        def count() -> int:
            victim_ids = None if victims is None else ids_of(victims)
            return self.game.kill_log.count(victim_ids=victim_ids, by_player=by_player)

        return count

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

    # The HUD shows chatter and hints/events in turn, each for its time (see
    # space_flight.ui.hud.ScenarioText): a message may wait for its turn.

    def hud(self, text: str):
        """Show a message in the HUD event banner."""
        # There is no HUD headless, and no one to read it.
        if not self.game.headless:
            self.game.hud.set_event_text(text=text)

    def hint(self, text: str):
        """Show a tutorial hint (see space_flight.game.levels.hints), smaller
        than the banner's messages and wrapped."""
        if not self.game.headless:
            self.game.hud.set_hint_text(text=text)

    def speech(self, text: str, speaker: Optional[str] = None):
        """Play a line of speech (audio stubbed), shown as a subtitle."""
        LOGGER.info("speech [%s]: %s", speaker or "narrator", text)
        if not self.game.headless:
            subtitle = f"{speaker}: {text}" if speaker else text
            self.game.hud.set_chatter_text(text=subtitle)

    def player_waypoints(
        self,
        points: Sequence[Sequence[float]],
        arrival_radius_m: Optional[float] = None,
        marker_radius_m: Optional[float] = None,
    ):
        """Give the player a route of targetable waypoints, replacing any
        previous one."""
        self.clear_player_waypoints()
        kwargs = {}
        if arrival_radius_m is not None:
            kwargs["arrival_radius_m"] = arrival_radius_m
        if marker_radius_m is not None:
            kwargs["marker_radius_m"] = marker_radius_m
        self.game.player_waypoints = PlayerWaypoints(self.game, points, **kwargs)

    def clear_player_waypoints(self):
        """Remove the player's waypoint route, if any."""
        route = getattr(self.game, "player_waypoints", None)
        if route is not None:
            route.clean()
            self.game.player_waypoints = None

    def jump_out(self, who: Any, spool_s: Optional[float] = None):
        """
        Every live bot of who leaves the level through hyperspace: it flies
        straight on for spool_s, still a target, then jumps out (see
        :meth:`WaveHandle.jump_out`). The player cannot jump out.

        :param who: See :func:`~space_flight.game.scenario.conditions.pawns_of`
        :param spool_s: How long the ships spool up before they jump (the
            default spool time if None)
        """
        for pawn in pawns_of(who):
            bot = pawn.parent
            if bot is self.game.player or not hasattr(bot, "jump_out"):
                continue
            if spool_s is None:
                bot.jump_out()
            else:
                bot.jump_out(spool_s=spool_s)

    def end_level(self, outcome: str, text: str = ""):
        """
        End the level ("victory", "defeat" or "death"): the objectives take
        their final state at once, and the level-end screen follows
        LEVEL_END_DELAY_S later. Only the first ending counts.
        """
        if self.ending is not None:
            return
        self.ending = outcome
        for objective in list(self.objectives):
            objective.finalize()

        def show_the_end() -> Iterator[None]:
            yield from self.wait(LEVEL_END_DELAY_S)
            self.game.end_level(outcome=outcome, text=text)

        self.schedule(show_the_end())

    def victory(self, text: str = ""):
        self.end_level("victory", text)

    def defeat(self, text: str = ""):
        self.end_level("defeat", text)
