from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from panda3d.core import NodePath

    from space_flight.game.flight_state import FlightState


class Trihedron:
    def __init__(self, game: FlightState, parent: NodePath, scale: int = 10):
        axis = game.app.loader.loadModel("zup-axis")
        # make sure it will be drawn above all other elements
        axis.setDepthTest(False)
        axis.setBin("fixed", 0)
        axis.setScale(scale)
        axis.reparentTo(parent)
        axis.setPos(0, 0, 0)
