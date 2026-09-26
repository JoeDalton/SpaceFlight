"""
The Python authoring surface for scenario scripting.

Where :mod:`space_flight.game.scenario.loader` turns a YAML ``triggers:``
section into :class:`~space_flight.game.scenario.Trigger` objects, a
:class:`Mission` lets a level script its events directly in Python: a plain
generator function that ``yield from``s the mission's own wait helpers for
the sequential parts ("wait 10s, then spawn the first wave, then wait until
it's wiped, then...") and calls :meth:`Mission.on` for reactive rules that
must hold throughout regardless of where the main sequence currently is
("if all transports die, defeat -- whenever that happens").

Wave *data* (size, ship model, spawn point, ...) still lives in YAML --
:func:`space_flight.game.scenario.loader.load_waves` loads just that section,
with no ``triggers:`` needed. A level's build function then does::

    def mission(m: Mission) -> Iterator[None]:
        yield from m.wait(0.1)
        transports = m.spawn(m.waves["transports"])
        yield from m.wait_until(transports.all_destroyed_cond())
        m.defeat("The convoy was lost.")

    def build_x_level(game):
        ...
        game.scenario = Scenario()
        m = Mission(game)
        m.waves = load_waves(Path(__file__).with_suffix(".yaml"))
        game.scenario.schedule(mission(m))
        yield "scenario"

This module reuses the existing engine wholesale (:class:`Scenario`,
:class:`Trigger`, its job-stepping) rather than replacing it: a
:class:`Mission`'s body is itself just a job, and :meth:`Mission.on` registers
an ordinary trigger.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterator, Optional, Union

from space_flight.game.scenario import Action, Condition, Scenario, Trigger, actions
from space_flight.game.scenario.actions import (
    _assign_targets,
    _spawn_wave_job,
    _validate_wave_cfg,
    set_bot_team,
)

if TYPE_CHECKING:
    from space_flight.ai.formation import Formation
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


class Mission:
    """
    A level's Python mission: wraps a :class:`Scenario` with an ergonomic API
    for a sequential mission body plus reactive rules.

    One instance is normally created per level, in the level's build
    function, and its mission body scheduled as a job on the scenario (see
    module docstring). :attr:`waves` is mostly just a convenient place for a
    level to stash the wave data it loaded so the mission body can refer to
    ``m.waves["first_wave"]`` -- assigning it also pre-declares each wave id
    as an (empty) group on the scenario, so a reactive rule that polls a
    wave's group before it has spawned (see the setter) does not spuriously
    warn about an "unknown group".

    :param game: The game/flight state; must already have ``game.scenario``
        set to a live :class:`Scenario`
    """

    def __init__(self, game: FlightState) -> None:
        self.game = game
        self.scenario: Scenario = game.scenario
        #: Optional convenience slot for a level's loaded wave data.
        self._waves: dict[str, dict] = {}

    @property
    def waves(self) -> dict[str, dict]:
        return self._waves

    @waves.setter
    def waves(self, waves: dict[str, dict]) -> None:
        self._waves = waves
        # Pre-declare every wave id as a (still empty) identity group, exactly
        # as :func:`space_flight.game.scenario.loader.load_scenario` does for
        # the legacy DSL, and for the same reason: a reactive rule registered
        # up front (see module docstring) may poll a wave's group (e.g.
        # reached_waypoint or near) before that wave has actually spawned --
        # without this, Scenario.resolve would warn about an "unknown group"
        # on every such frame, even though the wave's id is perfectly valid
        # and simply hasn't spawned yet.
        for wave_id in waves:
            self.scenario.groups.setdefault(wave_id, [])

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def spawn(
        self,
        wave_cfg: dict,
        *,
        target: Optional[Union["WaveHandle", str]] = None,
        join: Optional["Formation"] = None,
    ) -> "WaveHandle":
        """
        Spawn a wave, one ship per frame, and return a handle to it.

        :param wave_cfg: The wave configuration (see
            :func:`space_flight.game.scenario.actions.spawn_wave`); validated
            up front so a typo'd or missing key raises immediately rather than
            failing confusingly mid-spawn
        :param target: A :class:`WaveHandle` or group name this wave's ships
            should attack, overriding any ``target`` already in wave_cfg
        :param join: An existing, live :class:`Formation` for this wave's
            ships to attach to (continuing from its next free slot) instead of
            creating a new formation, even if wave_cfg declares one
        :return: A handle to the spawned (spawning) wave
        """
        cfg = dict(wave_cfg)
        _validate_wave_cfg(cfg)
        wave_id = cfg["id"]
        if target is not None:
            cfg["target"] = target.name if isinstance(target, WaveHandle) else target

        if wave_id in self.scenario.scheduled and not cfg.get("allow_respawn", False):
            LOGGER.warning(
                "Mission.spawn: '%s' already spawned; skipping "
                "(set allow_respawn: true to override)",
                wave_id,
            )
            return WaveHandle(wave_id, self)

        self.scenario.scheduled.add(wave_id)
        self.scenario.schedule(_spawn_wave_job(self.game, cfg, join=join))
        return WaveHandle(wave_id, self)

    # ------------------------------------------------------------------
    # Sequencing helpers (yield from these in a mission body)
    # ------------------------------------------------------------------

    def wait(self, seconds: float) -> Iterator[None]:
        """
        Yield once per frame until seconds of game time have passed.

        :param seconds: How long to wait, in game-clock seconds
        """
        deadline = self.game.game_time.get_current_time() + seconds
        while self.game.game_time.get_current_time() < deadline:
            yield

    def wait_until(self, condition: Union[Condition, float]) -> Iterator[None]:
        """
        Yield once per frame until condition holds.

        :param condition: A condition callable(game) -> bool, or a bare
            number of seconds (equivalent to :meth:`wait`)
        """
        if isinstance(condition, (int, float)):
            yield from self.wait(condition)
            return
        while not condition(self.game):
            yield

    def wait_any(self, *conditions: Condition) -> Iterator[None]:
        """
        Yield once per frame until any of conditions holds.

        :param conditions: Condition callables(game) -> bool
        """
        while not any(cond(self.game) for cond in conditions):
            yield

    def wait_all(self, *conditions: Condition) -> Iterator[None]:
        """
        Yield once per frame until every one of conditions holds.

        :param conditions: Condition callables(game) -> bool
        """
        while not all(cond(self.game) for cond in conditions):
            yield

    # ------------------------------------------------------------------
    # Reactive rules
    # ------------------------------------------------------------------

    def on(
        self,
        condition: Condition,
        action: Action,
        once: bool = True,
        name: Optional[str] = None,
    ) -> Trigger:
        """
        Register a reactive rule alongside the sequential mission body.

        Use this for a rule that must hold no matter where the mission body's
        sequence currently is (e.g. "defeat if all transports die, whenever
        that happens"), as opposed to something the body itself waits on.

        :param condition: Checked every frame
        :param action: Run once condition holds
        :param once: Whether the action fires only the first time
        :param name: Optional label, for logging and the fired condition
        :return: The created :class:`Trigger` (also appended to the scenario)
        """
        trigger = Trigger(condition=condition, action=action, once=once, name=name)
        self.scenario.triggers.append(trigger)
        if name is not None:
            self.scenario.triggers_by_name[name] = trigger
        return trigger

    # ------------------------------------------------------------------
    # Thin action wrappers
    # ------------------------------------------------------------------

    def hud(self, text: str, display_time_s: float = 5.0) -> None:
        """Show a one-off HUD banner message."""
        actions.hud_text(text, display_time_s=display_time_s)(self.game)

    def speech(
        self,
        text: str,
        speaker: Optional[str] = None,
        display_time_s: float = 6.0,
    ) -> None:
        """Play (stubbed) a line of speech, shown as a subtitle."""
        cfg: dict[str, Any] = {"text": text, "display_time_s": display_time_s}
        if speaker is not None:
            cfg["speaker"] = speaker
        actions.speech(cfg)(self.game)

    def player_waypoints(self, cfg: Union[list, dict]) -> None:
        """Give the player a targetable waypoint route."""
        actions.player_waypoints(cfg)(self.game)

    def end_level(self, outcome: str, text: str = "") -> None:
        """End the level immediately with the given outcome."""
        actions.end_level({"outcome": outcome, "text": text})(self.game)

    def victory(self, text: str = "") -> None:
        """Shorthand for :meth:`end_level` with outcome "victory"."""
        self.end_level("victory", text)

    def defeat(self, text: str = "", delay: float = 0) -> None:
        """
        Shorthand for :meth:`end_level` with outcome "defeat".

        :param delay: If non-zero, end the level that many seconds from now
            (via the game's delayed-method manager) instead of immediately --
            handy when calling this from a reactive :meth:`on` action, where
            there is no generator to ``yield from`` a :meth:`wait` in.
        """
        if delay:
            self.game.delayed_methods.do_method_later(
                delay_s=delay,
                name="mission_defeat",
                method=lambda: self.end_level("defeat", text),
            )
        else:
            self.end_level("defeat", text)


class WaveHandle:
    """
    A handle to a wave spawned through :meth:`Mission.spawn`.

    Thin wrapper around a group name plus the owning :class:`Mission`; every
    property/method reads live state from the scenario, so a handle stays
    valid across the wave's whole lifetime (spawning, alive, wiped out).

    :param name: The wave's group/identity name
    :param mission: The owning :class:`Mission`
    """

    def __init__(self, name: str, mission: Mission) -> None:
        self.name = name
        self.mission = mission

    @property
    def scenario(self) -> Scenario:
        return self.mission.scenario

    @property
    def game(self) -> FlightState:
        return self.mission.game

    # ------------------------------------------------------------------
    # State, read live
    # ------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        """Whether at least one member of this wave is currently alive."""
        return self.scenario.is_alive(self.game, self.name)

    @property
    def all_destroyed(self) -> bool:
        """Whether this wave has spawned and now has no live members."""
        return self.scenario.all_destroyed(self.game, self.name)

    @property
    def any_destroyed(self) -> bool:
        """Whether this wave has spawned and lost at least one member."""
        return self.scenario.any_destroyed(self.game, self.name)

    @property
    def formation(self) -> Optional["Formation"]:
        """The wave's live :class:`Formation`, or None if it has none."""
        return self.scenario.formation_by_group.get(self.name)

    # ------------------------------------------------------------------
    # As conditions, for wait_until / wait_any / wait_all / on
    # ------------------------------------------------------------------

    def all_destroyed_cond(self) -> Condition:
        """A condition callable(game) -> bool mirroring :attr:`all_destroyed`."""
        return lambda game: self.scenario.all_destroyed(game, self.name)

    def any_destroyed_cond(self) -> Condition:
        """A condition callable(game) -> bool mirroring :attr:`any_destroyed`."""
        return lambda game: self.scenario.any_destroyed(game, self.name)

    def alive_cond(self) -> Condition:
        """A condition callable(game) -> bool mirroring :attr:`alive`."""
        return lambda game: self.scenario.is_alive(game, self.name)

    # ------------------------------------------------------------------
    # Mutating every live member
    # ------------------------------------------------------------------

    def set_targets(self, other: Union["WaveHandle", str]) -> None:
        """
        Make every live member of this wave target every live member of other.

        :param other: A :class:`WaveHandle` or a group name
        """
        target_name = other.name if isinstance(other, WaveHandle) else other
        for pawn in self.scenario.resolve(self.game, self.name):
            _assign_targets(self.game, pawn.parent, target_name)

    def set_team(self, team: int) -> None:
        """
        Reassign every live member of this wave to team, cascading correctly
        for capital ships (sub-systems, shield, mounted turrets/tractor beams).

        :param team: The new team id
        """
        for pawn in self.scenario.resolve(self.game, self.name):
            set_bot_team(pawn.parent, team)

    def set_waypoints(self, points: list, loop: bool = True) -> None:
        """
        Give every live member of this wave a new patrol/route path.

        :param points: The waypoints, in world space
        :param loop: Whether to loop back to the first point
        """
        import numpy as np

        waypoints = [np.array(p) for p in points]
        for pawn in self.scenario.resolve(self.game, self.name):
            pawn.parent.navigator.set_waypoints(waypoints=waypoints, is_loop=loop)
