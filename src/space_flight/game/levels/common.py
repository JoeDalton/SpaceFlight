"""
Helpers shared by the level scripts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Sequence, Union

import numpy as np
from world_builder.asteroids.spec import KeepOut

from space_flight.actors.player import Player
from space_flight.game.scenario.conditions import hit_pawns
from space_flight.scenes.scenes import scene_factory

if TYPE_CHECKING:
    from space_flight.actors.pawn import Pawn
    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission
    from space_flight.weapons.loadout import Loadout

#: A speaker: a name, or a function of the pawn that was shot giving one.
Speaker = Union[str, Callable[["Pawn"], str]]

# Shots still on their way after a warning are forgiven
FRIENDLY_FIRE_GRACE_S = 2


def build_upfront(
    game: FlightState,
    scene_name: str,
    player_ship_type: str,
    player_position: Sequence[float],
    player_is_neutral: bool = False,
    player_record: bool = False,
    player_loadout: Loadout | None = None,
    keep_outs: Sequence[KeepOut] = (),
):
    """
    Build the heavy, up-front part of a level — run synchronously on a black
    screen BEFORE the hyperspace animation starts: the player, then the scene's
    up-front objects. The player comes first: the ocean's reflection camera
    copies the player camera's lens.

    :param game: The game/flight state
    :param scene_name: The scene (see scene_factory)
    :param player_ship_type: The player's fighter model
    :param player_position: The player's initial world position
    :param player_is_neutral: Team 0 instead of 1
    :param player_record: Step-by-step-record the player
    :param player_loadout: The player's weapons; None for its default loadout
    :param keep_outs: Room the scene's asteroid field leaves clear (see
        route_keep_outs)
    """
    game.player = Player(
        game=game,
        ship_type=player_ship_type,
        ini_position=np.array(player_position),
        is_neutral=player_is_neutral,
        has_ai=False,
        record=player_record,
        loadout=player_loadout,
    )
    game.scene = scene_factory(game=game, scene_name=scene_name, keep_outs=keep_outs)
    game.scene.build_upfront()


def route_keep_outs(
    points: Sequence[Sequence[float]], radius: float, loop: bool = False
) -> list[KeepOut]:
    """
    Room along a route that no asteroid enters: a capsule of *radius* around
    each leg (one ball for a single point).

    :param points: The route's world positions, in order
    :param radius: Clearance around the route, metres
    :param loop: Whether the route closes on its first point
    :return: The keep-outs
    """
    points = [tuple(float(v) for v in p) for p in points]
    if len(points) == 1:
        return [KeepOut(points[0], radius)]
    legs = list(zip(points, points[1:]))
    if loop:
        legs.append((points[-1], points[0]))
    return [KeepOut(a, radius, end=b) for a, b in legs]


def clear_position(game: FlightState, position: Sequence[float], radius: float):
    """
    Where to put ships wanted at *position* (placed at run time, relative to
    the player): the nearest place with room for a ball of *radius* in the
    scene (clear of its asteroids).

    :return: The world position to use
    """
    return game.scene.clear_position(position, radius)


def relative_position(
    pawn: Pawn, right_m: float = 0.0, forward_m: float = 0.0, up_m: float = 0.0
) -> np.ndarray:
    """
    :param pawn: The reference pawn
    :param right_m: Distance to its right (negative: to its left)
    :param forward_m: Distance ahead of it, along its nose (negative: behind)
    :param up_m: Distance above it (negative: below)
    :return: The world position at these coordinates in the pawn's frame
    """
    return (
        pawn.position + pawn.forward * forward_m + pawn.right * right_m + pawn.up * up_m
    )


class FirePolice:
    """
    The handle of a :func:`police_fire` chain.
    """

    def __init__(self):
        self.trigger = None
        self.cancelled = False

    def cancel(self):
        """Stop watching the player's fire."""
        self.cancelled = True
        if self.trigger is not None:
            self.trigger.cancel()


def police_fire(
    m: Mission,
    who: Any,
    stages: Sequence[Sequence[tuple[Speaker, str]]],
    on_grounded: Callable[[], None],
    grace_s: float = FRIENDLY_FIRE_GRACE_S,
) -> FirePolice:
    """
    Rules of engagement: each of the player's hits on who plays the next stage
    of chatter, and the hit of the last stage grounds the player.

    A hit within grace_s of the previous one is forgiven (shots already on
    their way). Every call counts its hits from zero.

    :param m: The level's :class:`Mission`
    :param who: What the player must not shoot, see
        :func:`~space_flight.game.scenario.conditions.pawns_of`
    :param stages: One group of (speaker, line) per hit; a speaker is a name
        or a function of the pawn that was shot
    :param on_grounded: Called once the last stage is spoken; ends the level
    :param grace_s: The forgiveness after each hit
    :return: The handle, to cancel the rules
    """
    police = FirePolice()
    hits = hit_pawns(who, by_player=True)
    shot: list = []

    def arm(index: int):
        # Read every frame, so a hit during the grace is not kept for later
        def read() -> bool:
            shot[:] = hits()
            return bool(shot)

        grace = m.after(grace_s if index else 0)
        police.trigger = m.on(lambda: read() and grace(), lambda: play(index))

    def play(index: int):
        if police.cancelled or m.ending is not None:
            return
        victim = shot[0]
        for speaker, text in stages[index]:
            name = speaker(victim) if callable(speaker) else speaker
            m.speech(text, speaker=name)
        if index + 1 < len(stages):
            arm(index + 1)
        else:
            on_grounded()

    arm(0)
    return police
