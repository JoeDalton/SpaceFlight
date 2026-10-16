from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import quaternion  # noqa: F401 - registers np.quaternion; needed before any use below
from panda3d.core import NodePath, Quat

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.asset_manager import gltf_model_tilt_quaternion

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState


@dataclass(frozen=True)
class ModelSpec:
    """
    How a ship's 3D model is placed on its ship node.

    :param path: The glTF file, relative to datafiles/models
    :param offset: Model position on the ship node
    :param orientation: Model orientation on the ship node
    :param scale: Model scale, or None to leave the model's own
    :param tilt: Whether to compose the orientation with the glTF tilt (see
        gltf_model_tilt_quaternion)
    """

    path: str
    offset: tuple[float, float, float]
    orientation: np.quaternion
    scale: float | None
    tilt: bool = True


# Turns a glTF model (+Z forward) around to face the ship's +Y
_FLIP = np.quaternion(0.0, 0.0, 1.0, 0.0)
# Half a turn about the vertical axis
_YAW_180 = np.quaternion(0.0, 0.0, 0.0, 1.0)
_TIE_COCKPIT = "ships/tie_common/cockpit/scene.gltf"

#: (ship type, is_cockpit) -> its model
_MODELS = {
    ("a-wing", True): ModelSpec(
        "ships/a-wing/cockpit/scene.gltf", (0.0, 0.8, -0.2), _FLIP, 0.8
    ),
    ("a-wing", False): ModelSpec(
        "ships/a-wing/exterior/scene.gltf", (0.0, 0.0, 0.0), _FLIP, 0.01
    ),
    ("tie-interceptor", True): ModelSpec(_TIE_COCKPIT, (0.0, 0.9, -0.2), _FLIP, None),
    ("tie-interceptor", False): ModelSpec(
        "ships/tie-interceptor/exterior/scene.gltf", (0.0, 0.0, 0.0), _FLIP, 4.1
    ),
    ("tie-bomber", True): ModelSpec(_TIE_COCKPIT, (0.0, 0.9, -0.2), _FLIP, None),
    ("tie-bomber", False): ModelSpec(
        "ships/tie-bomber/exterior/scene.gltf", (1.5, 0.0, 0.0), _FLIP, 1.0
    ),
    ("y-wing", True): ModelSpec(
        "ships/y-wing/cockpit/scene.gltf", (0.0, 0.7, -0.5), _FLIP, None
    ),
    ("y-wing", False): ModelSpec(
        "ships/y-wing/exterior/scene.gltf", (0.0, 0.0, 0.0), _FLIP, 0.115
    ),
    ("x-wing", True): ModelSpec(
        "ships/x-wing/cockpit/scene.gltf", (0.0, 0.9, -0.2), _FLIP, None
    ),
    ("x-wing", False): ModelSpec(
        "ships/x-wing/exterior/scene.gltf", (0.0, 0.0, 0.0), _YAW_180 * _FLIP, 0.5
    ),
    ("tie-fighter", True): ModelSpec(_TIE_COCKPIT, (0.0, 0.9, -0.2), _FLIP, None),
    ("tie-fighter", False): ModelSpec(
        "ships/tie-fighter/exterior/scene.gltf", (3.7, 0.0, 6.5), _FLIP, 0.035
    ),
    ("gr-75", False): ModelSpec(
        "ships/gr-75/scene.gltf", (0.0, 0.0, 0.0), _YAW_180, 1.0, tilt=False
    ),
    ("cr-90", False): ModelSpec(
        "ships/cr-90/scene.gltf", (0.0, 0.0, 0.0), _YAW_180, 1.0, tilt=False
    ),
    ("isd", False): ModelSpec(
        "star_wars_imperial-class_star_destroyer/scene.gltf",
        (0.0, -700.0, 0.0),
        _YAW_180,
        1.0,
        tilt=False,
    ),
}


class AnchoredModel:
    """
    A 3D model placed on a parent node at its offset and orientation.

    :ivar model: The model's node
    :ivar offset: Its position on the parent node
    :ivar orientation: Its orientation on the parent node
    """

    model: NodePath
    offset: np.ndarray
    orientation: np.quaternion

    def anchor_model(self, node: NodePath):
        """
        Anchors the 3D model to its parent node
        """
        self.model.reparent_to(node)
        self.model.setPos(*self.offset)
        self.model.setQuat(
            Quat(
                self.orientation.w,
                self.orientation.x,
                self.orientation.y,
                self.orientation.z,
            )
        )

    def clean(self):
        """
        Cleans the model
        """
        self.model.removeNode()
        self.model = None
        self.game = None


class ShipModel(AnchoredModel):
    def __init__(
        self,
        game: FlightState,
        parent_node: NodePath,
        ship_type: str = "a-wing",
        is_cockpit: bool = True,
    ):
        self.game = game
        self.ship_type = ship_type
        spec = _MODELS.get((ship_type, is_cockpit))
        if spec is None:
            raise NotImplementedError(f"{ship_type=} {is_cockpit=}")
        # Instantiate already-loaded models to a new node
        self.model = self.game.root_node.attachNewNode("ship_model_instance")
        self.game.app.asset_manager.instantiate_3d_model_to_node(
            path=DATAFILES_PATH / "models" / spec.path, parent_node=self.model
        )
        self.offset = np.array(spec.offset)
        self.orientation = spec.orientation
        if spec.tilt:
            self.orientation = self.orientation * gltf_model_tilt_quaternion(self.game)
        if spec.scale is not None:
            self.model.setScale(spec.scale)

        self.anchor_model(parent_node)
