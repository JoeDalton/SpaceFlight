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
    True once group has spawned and at least one of its members is dead.

    Stays true once every member has died too (all_destroyed is a subset of
    any_destroyed, not its opposite): this reports "the group has taken at
    least one loss", which remains the case after a total wipe.

    :param group: A group name (see :class:`Scenario`)
    :return: The condition callable
    """

    def cond(game: FlightState) -> bool:
        return game.scenario.any_destroyed(game, group)

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


def near_actor(who_a: str, who_b: str, radius: float) -> Condition:
    """
    True when the nearest pair between who_a's and who_b's live members is
    within radius.

    The live-actor equivalent of near(): where near() measures distance to a
    fixed world position, this measures distance between two moving groups
    (e.g. "is the player still close to the escort leader?"), re-resolving
    both sides every frame.

    :param who_a: "player" or a group name
    :param who_b: "player" or a group name
    :param radius: Distance in metres considered "near"
    :return: The condition callable
    """
    radius_sq = radius * radius

    def cond(game: FlightState) -> bool:
        for a in _resolve_who(game, who_a):
            for b in _resolve_who(game, who_b):
                delta = a.position - b.position
                if float(delta @ delta) <= radius_sq:
                    return True
        return False

    return cond


def reached_waypoint(group: str, index: int) -> Condition:
    """
    True once any live member of group has reached waypoint index (0-based).

    Reads the navigator's next_waypoint_idx directly: it starts at 0 and is
    incremented each time a waypoint is reached, so next_waypoint_idx becomes
    index + 1 the moment waypoint index is reached, hence "> index" rather
    than ">= index". The navigator resets it to 0 at the end of each lap of a
    looping patrol and after the last waypoint of a non-looping path, so it is
    unambiguous only on the first pass; use a monotonic counter if you need
    more.

    :param group: A group name
    :param index: The (0-based) waypoint that must have been reached
    :return: The condition callable
    """

    def cond(game: FlightState) -> bool:
        for pawn in _resolve_who(game, group):
            if pawn is not None and pawn.parent.navigator.next_waypoint_idx > index:
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


class Sustained:
    """
    True once inner has held continuously true for seconds straight.

    The mirror image of Delay: Delay latches permanently the moment inner
    first becomes true and never un-arms, whereas Sustained resets to
    unarmed the instant inner goes false, so it only reports true after an
    unbroken run of seconds (e.g. "further than 200m for 10 *consecutive*
    seconds", as opposed to Delay's "3 seconds after X first became true").
    Each trigger must own its own Sustained instance, exactly as for Delay.

    :param inner: The condition that must hold continuously
    :param seconds: How long inner must hold, unbroken, before this reports true
    """

    def __init__(self, inner: Condition, seconds: float) -> None:
        self.inner = inner
        self.seconds = seconds
        self._since: Optional[float] = None

    def __call__(self, game: FlightState) -> bool:
        if not self.inner(game):
            self._since = None
            return False
        now = game.game_time.get_current_time()
        if self._since is None:
            self._since = now
        return now - self._since >= self.seconds


class Not:
    """
    True when inner is false.

    :param inner: The condition to negate
    """

    def __init__(self, inner: Condition) -> None:
        self.inner = inner

    def __call__(self, game: FlightState) -> bool:
        return not self.inner(game)


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
