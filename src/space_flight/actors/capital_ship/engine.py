from __future__ import annotations

from typing import TYPE_CHECKING

from space_flight.actors.capital_ship.sub_system import SubSystem

if TYPE_CHECKING:
    from space_flight.actors.capital_ship import CapitalShip
    from space_flight.game.flight_state import FlightState


class Engine(SubSystem):
    """
    A class for capital ships engines
    """

    def __init__(self, game: FlightState, parent: CapitalShip):
        super().__init__(game=game, parent=parent)
