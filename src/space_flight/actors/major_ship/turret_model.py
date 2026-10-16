from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import NodePath

from space_flight import DATAFILES_PATH
from space_flight.actors.ship_model import AnchoredModel

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState


class TurretModel(AnchoredModel):
    def __init__(
        self, game: FlightState, parent_node: NodePath, turret_type: str = "test"
    ):
        self.game = game
        self.turret_type = turret_type
        # Copy the already-loaded model to a new node: a copy, not an instance,
        # so this mount's swivelling joints are its own (instances would share
        # them with every other mount of the type)
        self.model = self.game.root_node.attachNewNode("turret_model_instance")

        if self.turret_type == "test":
            self.game.app.asset_manager.copy_3d_model_to_node(
                path=DATAFILES_PATH / "models/turrets/test/turret.glb",
                parent_node=self.model,
            )
            self.offset = np.array([0.0, 0.0, 0.0])
            self.orientation = np.quaternion(1.0, 0.0, 0.0, 0.0)
            self.model.setScale(1)
            # Find the proper nodes to manipulate in the model
            self.yaw_node = self.model.find("**/heading_axis")
            self.pitch_node = self.model.find("**/cannon_axis")
            # Assign movement functions
            self.set_yaw = self.yaw_node.setH
            self.set_pitch = self.pitch_node.setP
            self.cannon_node = self.pitch_node
        else:
            raise NotImplementedError(turret_type)

        self.anchor_model(parent_node)
