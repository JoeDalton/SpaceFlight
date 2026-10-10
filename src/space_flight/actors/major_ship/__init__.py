"""
Major ships (the big ships carrying subsystems) and their subsystems.

:class:`MajorShip` is the shared base; each ship config picks its subclass with
its ``ship_class`` key (see :func:`make_major_ship`):

- ``escort``: :class:`EscortShip`, manoeuverable (transports, frigates,
  corvettes), with the full AI stack
- ``capital``: :class:`CapitalShip`, a scripted star destroyer that only
  patrols
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from space_flight.actors.major_ship.capital_ship import CapitalShip
from space_flight.actors.major_ship.escort_ship import EscortShip
from space_flight.actors.major_ship.major_ship import MajorShip
from space_flight.actors.ship import load_ship_configuration

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# The ship config's ship_class values, and the class each one builds
MAJOR_SHIP_CLASSES = {"escort": EscortShip, "capital": CapitalShip}
DEFAULT_SHIP_CLASS = "escort"

__all__ = [
    "CapitalShip",
    "EscortShip",
    "MajorShip",
    "MAJOR_SHIP_CLASSES",
    "make_major_ship",
    "major_ship_class",
]


def major_ship_class(ship_type: str) -> type[MajorShip]:
    """
    The MajorShip subclass a ship type's config asks for (its ``ship_class``
    key, escort by default).

    :param ship_type: The ship type, i.e. its configuration directory name
    :return: The class to build
    """
    ship_class = load_ship_configuration(ship_type).get(
        "ship_class", DEFAULT_SHIP_CLASS
    )
    try:
        return MAJOR_SHIP_CLASSES[ship_class]
    except KeyError:
        raise ValueError(
            f"{ship_type}: unknown ship_class {ship_class!r}, "
            f"expected one of {sorted(MAJOR_SHIP_CLASSES)}"
        ) from None


def make_major_ship(
    game: FlightState, parent: Any, ship_type: str, **kwargs: Any
) -> MajorShip:
    """
    Build a major ship of the class its config asks for.

    :param game: The game/flight state
    :param parent: The ship's parent (its bot)
    :param ship_type: The ship type, i.e. its configuration directory name
    :param kwargs: Passed on to the class constructor
    :return: The ship
    """
    return major_ship_class(ship_type)(
        game=game, parent=parent, ship_type=ship_type, **kwargs
    )
