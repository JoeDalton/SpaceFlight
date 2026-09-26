"""
Conditions for mission scripting.

A condition is any zero-argument callable returning a bool, checked once per
frame by :meth:`Mission.wait_until` or a :meth:`Mission.on` rule. Plain
lambdas and bound methods (e.g. ``wave.all_destroyed``) are conditions too;
the factories below cover the spatial checks and composition.

Clock-based conditions (``after``/``delay``/``sustained``) need the game
clock, so they are built through :class:`Mission` (``m.after(10)``...), which
constructs the private classes at the bottom of this module.

``who`` arguments accept a :class:`WaveHandle` (its live members), a
Player/Bot (its pawn) or a pawn, see :func:`pawns_of`.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

import numpy as np

#: A condition: called once per frame, the rule/wait proceeds when it is True.
Condition = Callable[[], bool]


def pawns_of(who: Any) -> list:
    """
    The live pawns designated by who.

    :param who: A :class:`WaveHandle` (its live members), a Player or Bot
        (its pawn), or a pawn
    :return: The live pawns; empty if none are alive
    """
    if hasattr(who, "pawns"):
        return who.pawns()
    pawn = getattr(who, "pawn", who)
    if pawn is None or getattr(pawn, "is_dead", False):
        return []
    return [pawn]


# ---------------------------------------------------------------------------
# Spatial conditions
# ---------------------------------------------------------------------------


def near(who: Any, point: Sequence[float], radius: float) -> Condition:
    """
    True when any live pawn of who is within radius of a fixed point.

    :param who: See :func:`pawns_of`
    :param point: World-space position to measure against
    :param radius: Distance in metres considered "near"
    :return: The condition
    """
    point_arr = np.asarray(point, dtype=float)
    radius_sq = radius * radius

    def cond() -> bool:
        for pawn in pawns_of(who):
            delta = pawn.position - point_arr
            if float(delta @ delta) <= radius_sq:
                return True
        return False

    return cond


def near_actor(who_a: Any, who_b: Any, radius: float) -> Condition:
    """
    True when the nearest pair between who_a's and who_b's live pawns is
    within radius -- :func:`near` for two moving targets (e.g. "is the player
    still close to any member of the escort?").

    :param who_a: See :func:`pawns_of`
    :param who_b: See :func:`pawns_of`
    :param radius: Distance in metres considered "near"
    :return: The condition
    """
    radius_sq = radius * radius

    def cond() -> bool:
        for a in pawns_of(who_a):
            for b in pawns_of(who_b):
                delta = a.position - b.position
                if float(delta @ delta) <= radius_sq:
                    return True
        return False

    return cond


def reached_waypoint(who: Any, index: int) -> Condition:
    """
    True once any live bot of who has reached its waypoint index (0-based).

    Reads the navigator's next_waypoint_idx, which becomes index + 1 the
    moment waypoint index is reached. The navigator resets it to 0 at the
    end of each lap of a looping patrol and after the last waypoint of a
    non-looping path, so it is unambiguous only on the first pass.

    :param who: See :func:`pawns_of` (bots only: the player has no navigator)
    :param index: The waypoint that must have been reached
    :return: The condition
    """

    def cond() -> bool:
        return any(
            pawn.parent.navigator.next_waypoint_idx > index for pawn in pawns_of(who)
        )

    return cond


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------
# Plain lambdas compose stateless conditions just as well; these exist so a
# stateful condition (m.delay / m.sustained) is built once, when the rule is
# declared -- `lambda: m.delay(c, 3)()` would build a fresh, never-firing
# timer every frame.


def all_of(*conds: Condition) -> Condition:
    """True when every sub-condition is true."""
    return lambda: all(c() for c in conds)


def any_of(*conds: Condition) -> Condition:
    """True when any sub-condition is true."""
    return lambda: any(c() for c in conds)


def not_(cond: Condition) -> Condition:
    """True when cond is false."""
    return lambda: not cond()


# ---------------------------------------------------------------------------
# Clock-based conditions (built via Mission.after / delay / sustained)
# ---------------------------------------------------------------------------


class _After:
    """True once seconds have passed since construction."""

    def __init__(self, clock: Callable[[], float], seconds: float) -> None:
        self.clock = clock
        self.deadline = clock() + seconds

    def __call__(self) -> bool:
        return self.clock() >= self.deadline


class _Delay:
    """
    True once seconds have passed since inner first became true.

    Latches: once inner has been true, the timer keeps running even if inner
    flickers back to false.
    """

    def __init__(
        self, clock: Callable[[], float], inner: Condition, seconds: float
    ) -> None:
        self.clock = clock
        self.inner = inner
        self.seconds = seconds
        self._armed_at: Optional[float] = None

    def __call__(self) -> bool:
        now = self.clock()
        if self._armed_at is None:
            if not self.inner():
                return False
            self._armed_at = now
        return now - self._armed_at >= self.seconds


class _Sustained:
    """
    True once inner has held for an unbroken run of seconds.

    The mirror image of :class:`_Delay`: resets the moment inner goes false.
    """

    def __init__(
        self, clock: Callable[[], float], inner: Condition, seconds: float
    ) -> None:
        self.clock = clock
        self.inner = inner
        self.seconds = seconds
        self._since: Optional[float] = None

    def __call__(self) -> bool:
        if not self.inner():
            self._since = None
            return False
        now = self.clock()
        if self._since is None:
            self._since = now
        return now - self._since >= self.seconds
