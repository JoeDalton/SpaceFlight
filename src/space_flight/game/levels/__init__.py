"""
The single registry of shipped levels.

Each level contributes an ``upfront`` builder (the player and the scene's
heavy objects, built synchronously before the hyperspace animation) and a
``mission`` body (its scripted events, run by a
:class:`~space_flight.game.scenario.Mission` once the rest of the scene has
been built during the animation).

This registry is the single place that lists the shipped levels by name, so
:mod:`space_flight.game.flight_state` (which builds a level) and
:mod:`space_flight.menus.level_selection_menu_state` (which lets the player
pick one) both read the same data instead of keeping their own, easily
out-of-sync copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from space_flight.game.levels.dev_level import build_dev_upfront, dev_mission
from space_flight.game.levels.intro_level import build_intro_upfront, intro_mission
from space_flight.game.levels.mission1_level import (
    build_mission1_upfront,
    mission1_mission,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission


@dataclass(frozen=True)
class LevelEntry:
    """
    One shipped level's callbacks plus its menu description.

    :param upfront: Creates the player and the scene, on a black screen
    :param mission: The mission body, a generator function taking the Mission
    :param description: Shown in the level selection menu
    """

    upfront: Callable[["FlightState"], None]
    mission: Callable[["Mission"], "Iterator[None]"]
    description: str


#: Every shipped level, keyed by its name as stored in
#: ``app.configuration["selected_level"]``.
LEVELS: dict[str, LevelEntry] = {
    "Mission 1: Rookies": LevelEntry(
        upfront=build_mission1_upfront,
        mission=mission1_mission,
        description="A tutorial mission: learn the target-filter radial "
        "menu, follow a formation through the asteroid field, then race it "
        "to the marker.",
    ),
    "Mission 2: Escort": LevelEntry(
        upfront=build_intro_upfront,
        mission=intro_mission,
        description="The first `game ready` level.",
    ),
    "Dev": LevelEntry(
        upfront=build_dev_upfront,
        mission=dev_mission,
        description="A development level, not player-intended",
    ),
}
