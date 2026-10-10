from __future__ import annotations

from typing import TYPE_CHECKING

from space_flight.actors.major_ship.sub_system import SubSystem

if TYPE_CHECKING:
    from space_flight.actors.major_ship.major_ship import MajorShip
    from space_flight.game.flight_state import FlightState


class Engine(SubSystem):
    """
    A class for capital ships engines
    """

    def __init__(self, game: FlightState, parent: MajorShip):
        super().__init__(game=game, parent=parent)
