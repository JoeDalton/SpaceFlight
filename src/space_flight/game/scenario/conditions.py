"""
Condition factories for scenario triggers.

A condition is any callable condition(game) -> bool. Stateless conditions
are plain functions; conditions that need memory (e.g. "3 seconds after X") are
small classes that latch internal state. Either kind composes through the
combinators below, so a single trigger can express things like::

    Delay(all_destroyed("first_wave"), seconds=3.0)
    AllOf(reached_waypoint("transports", 5), all_destroyed("second_wave"))
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Actor, Condition


# ---------------------------------------------------------------------------
# Leaf conditions
# ---------------------------------------------------------------------------


def after_seconds(seconds: float) -> Condition:
    """
    True once the game clock passes seconds.

    :param seconds: Game-time threshold, in seconds
    :return: The condition callable
    """

    def cond(game: FlightState) -> bool:
        return game.game_time.get_current_time() > seconds

    return cond


def all_destroyed(group: str) -> Condition:
    """
    True once group has spawned and all its members are dead.

    :param group: A group name (see :class:`Scenario`)
    :return: The condition callable
    """

    def cond(game: FlightState) -> bool:
        return game.scenario.all_destroyed(game, group)

    return cond


def any_destroyed(group: str) -> Condition:
    """
    True once group has spawned and one of its member is dead.

    :param group: A group name (see :class:`Scenario`)
    :return: The condition callable
    """

    # TODO
    def cond(game: FlightState) -> bool:
        return False

    return cond


def any_alive(group: str) -> Condition:
    """
    True while at least one member of group is alive.

    :param group: A group name
    :return: The condition callable
    """

    def cond(game: FlightState) -> bool:
        return game.scenario.is_alive(game, group)

    return cond


def fired(trigger_name: str) -> Condition:
    """
    True once the trigger called trigger_name has fired.

    Lets events chain off one another by name; wrap in :class:`Delay` to fire
    some time after the other trigger.

    :param trigger_name: The name of the trigger to wait on
    :return: The condition callable
    """

    def cond(game: FlightState) -> bool:
        return game.scenario.has_fired(trigger_name)

    return cond


def near(who: str, point: Sequence[float], radius: float) -> Condition:
    """
    True when who is within radius of point.

    who is either the literal "player" or a group name; for a group it is
    true if *any* live member is in range. Handy for race checkpoints and finish
    lines.

    :param who: "player" or a group name
    :param point: World-space position to measure against
    :param radius: Distance in metres considered "near"
    :return: The condition callable
    """
    point_arr = np.asarray(point, dtype=float)
    radius_sq = radius * radius

    def cond(game: FlightState) -> bool:
        for pawn in _resolve_who(game, who):
            delta = pawn.position - point_arr
            if float(delta @ delta) <= radius_sq:
                return True
        return False

    return cond


def _resolve_who(game: FlightState, who: str) -> list[Actor]:
    """
    Resolve a who token to a list of pawns.

    :param game: The game/flight state
    :param who: "player" or a group name
    :return: The pawn(s) the token refers to
    """
    if who == "player":
        return [game.player.pawn]
    return game.scenario.resolve(game, who)


def reached_waypoint(group: str, index: int) -> Condition:
    """
    True once any member of group has reached waypoint index.

    Reads the navigator's next_waypoint_idx directly. Looping patrols reset
    this to 0 each lap, so it is unambiguous only on the first lap; use a
    non-looping path or a monotonic counter if you need later laps.

    :param group: A group name
    :param index: The waypoint index to reach (0-based)
    :return: The condition callable
    """

    def cond(game: FlightState) -> bool:
        for pawn in _resolve_who(game, group):
            if pawn is not None and pawn.parent.navigator.next_waypoint_idx >= index:
                return True
        return False

    return cond


# ---------------------------------------------------------------------------
# Stateful / combinator conditions
# ---------------------------------------------------------------------------


class Delay:
    """
    True once seconds have elapsed since inner first became true.

    Latches the moment inner fires, so it survives inner flickering back
    to false afterwards. Each trigger must own its own Delay instance — the
    loader builds a fresh one per trigger so two rules never share the armed time.

    :param inner: The condition that arms the timer
    :param seconds: Delay after arming before this condition reports true
    """

    def __init__(self, inner: Condition, seconds: float) -> None:
        self.inner = inner
        self.seconds = seconds
        self._armed_at: Optional[float] = None

    def __call__(self, game: FlightState) -> bool:
        now = game.game_time.get_current_time()
        if self._armed_at is None:
            if not self.inner(game):
                return False
            self._armed_at = now
        return now - self._armed_at >= self.seconds


class AllOf:
    """
    True when every sub-condition is true.

    :param conds: The sub-conditions
    """

    def __init__(self, *conds: Condition) -> None:
        self.conds = conds

    def __call__(self, game: FlightState) -> bool:
        return all(c(game) for c in self.conds)


class AnyOf:
    """
    True when any sub-condition is true.

    :param conds: The sub-conditions
    """

    def __init__(self, *conds: Condition) -> None:
        self.conds = conds

    def __call__(self, game: FlightState) -> bool:
        return any(c(game) for c in self.conds)
