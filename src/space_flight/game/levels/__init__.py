"""
The single registry of shipped levels.

Each level contributes an ``upfront`` builder (the heavy, synchronous
pre-animation phase) and a ``build`` generator (the rest, built incrementally
during the hyperspace animation) -- see any level module (e.g.
:mod:`space_flight.game.levels.intro_level`) for the pair's contract.

This registry is the single place that lists the shipped levels by name, so
:mod:`space_flight.game.flight_state` (which builds a level) and
:mod:`space_flight.menus.level_selection_menu_state` (which lets the player
pick one) both read the same data instead of keeping their own, easily
out-of-sync copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from space_flight.game.levels.dev_level import build_dev_level, build_dev_upfront
from space_flight.game.levels.intro_level import build_intro_level, build_intro_upfront
from space_flight.game.levels.race_level import build_race_level, build_race_upfront

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState


@dataclass(frozen=True)
class LevelEntry:
    """
    One shipped level's build callbacks plus its menu description.

    :param upfront: The heavy, synchronous, on-black build phase
    :param build: The generator building the rest, one step per frame
    :param description: Shown in the level selection menu
    """

    upfront: Callable[["FlightState"], None]
    build: Callable[["FlightState"], "Iterator[str]"]
    description: str


#: Every shipped level, keyed by its name as stored in
#: ``app.configuration["selected_level"]``.
LEVELS: dict[str, LevelEntry] = {
    "Dev": LevelEntry(
        upfront=build_dev_upfront,
        build=build_dev_level,
        description="A development level that usually demonstrates the "
        "latest implemented features",
    ),
    "Intro": LevelEntry(
        upfront=build_intro_upfront,
        build=build_intro_level,
        description="The first `game ready` level.",
    ),
    "Race": LevelEntry(
        upfront=build_race_upfront,
        build=build_race_level,
        description="A friendly tutorial race: pass the checkpoints and "
        "beat three rival pilots to the finish line.",
    ),
}
