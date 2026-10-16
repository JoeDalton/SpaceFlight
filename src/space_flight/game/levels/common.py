"""
Helpers shared by the level scripts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

import numpy as np

from space_flight.actors.player import Player
from space_flight.scenes.scenes import scene_factory

if TYPE_CHECKING:
    from space_flight.actors.pawn import Pawn
    from space_flight.game.flight_state import FlightState
    from space_flight.weapons.loadout import Loadout


def build_upfront(
    game: FlightState,
    scene_name: str,
    player_ship_type: str,
    player_position: Sequence[float],
    player_is_neutral: bool = False,
    player_record: bool = False,
    player_loadout: Loadout | None = None,
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
    game.scene = scene_factory(game=game, scene_name=scene_name)
    game.scene.build_upfront()


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
