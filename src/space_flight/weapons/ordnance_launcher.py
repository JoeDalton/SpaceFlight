"""
Ordnance (bombs, rockets, missiles, flares): configuration loading and the
launcher a ship carries for each entry of its loadout.

Every kind of ordnance shares the same code; they differ only by their
configuration (``datafiles/models/ordnance/<name>/configuration.yaml``): the
launch direction and speed, the guidance (missiles only) and the collision role
(flares only stop other ordnance).
"""

from __future__ import annotations

import copy
import functools
import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np
import yaml

from space_flight import DATAFILES_PATH
from space_flight.actors.ordnance import OrdnanceController
from space_flight.ai.target_lock import TargetLock
from space_flight.weapons import Weapon

if TYPE_CHECKING:
    from space_flight.actors.fighter import Fighter
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()

ORDNANCE_PATH = DATAFILES_PATH / "models/ordnance"
ORDNANCE_TYPES = ("bomb", "rocket", "missile", "flare")
# The ordnance types the player picks as a "secondary" weapon (flares have their
# own trigger)
SECONDARY_TYPES = ("bomb", "rocket", "missile")
LAUNCH_DIRECTIONS = ("forward", "down", "backward")
DAMAGE_TYPES = ("physical",)
# What a missile's configuration must hold to tune its target lock
MISSILE_LOCK_KEYS = ("lock_delay_s", "lock_cone_angle_deg")


@functools.cache
def _read_ordnance_configuration(name: str) -> dict:
    """
    Read and validate an ordnance configuration file (cached).

    :param name: The ordnance name, i.e. its configuration directory name
    :return: The configuration dictionary
    """
    with open(ORDNANCE_PATH / name / "configuration.yaml", "r") as f:
        conf = yaml.safe_load(f)
    if conf.get("type") not in ORDNANCE_TYPES:
        raise ValueError(f"Ordnance {name}: unknown type {conf.get('type')!r}")
    if conf.get("launch_direction") not in LAUNCH_DIRECTIONS:
        raise ValueError(
            f"Ordnance {name}: unknown launch direction "
            f"{conf.get('launch_direction')!r}"
        )
    if conf.get("damage_type") not in DAMAGE_TYPES:
        raise NotImplementedError(
            f"Ordnance {name}: unsupported damage type {conf.get('damage_type')!r}"
        )
    if conf["type"] == "missile":
        missing = [key for key in MISSILE_LOCK_KEYS if key not in conf]
        if missing:
            raise ValueError(f"Ordnance {name}: missile without {', '.join(missing)}")
    return conf


def load_ordnance_configuration(name: str) -> dict:
    """
    Load an ordnance configuration.

    :param name: The ordnance name, i.e. its configuration directory name
    :return: A copy of the configuration dictionary, free to be modified
    """
    return copy.deepcopy(_read_ordnance_configuration(name))


class OrdnanceLauncher(Weapon):
    """
    Launches one kind of ordnance from a ship, from a limited stock and at a
    limited rate. One launcher per entry of the ship's loadout.

    It is the single source of an ordnance's launch properties, read by the
    player's controls and by the AI alike.
    """

    def __init__(
        self,
        game: FlightState,
        parent: Fighter,
        name: str,
        stock: int,
    ):
        """
        :param game: The game/flight state
        :param parent: The ship carrying the ordnance
        :param name: The ordnance name, i.e. its configuration directory name
        :param stock: How many it carries
        """
        self.conf = load_ordnance_configuration(name)
        super().__init__(game, parent, fire_delay=self.conf["reload_s"])
        self.name = name
        self.category = self.conf["type"]
        self.stock = stock
        # Launch speed relative to the launching ship, along launch_direction
        self.speed_mps = self.conf["speed_mps"]
        self.launch_direction = self.conf["launch_direction"]
        # A missile is guided to the target only once locked on it, which the
        # ship updates while the missile is selected (see Fighter.move)
        self.target_lock = None
        if self.category == "missile":
            self.target_lock = TargetLock(
                game=self.game,
                parent=self.parent,
                lock_delay_s=self.conf["lock_delay_s"],
                cone_angle_deg=self.conf["lock_cone_angle_deg"],
            )

    @property
    def display_name(self) -> str:
        """The ordnance's name as shown on the HUD."""
        return self.name.replace("_", " ").upper()

    def launch_direction_vector(self) -> np.ndarray:
        """
        :return: The unit launch direction, in world coordinates
        """
        if self.launch_direction == "forward":
            return np.asarray(self.parent.forward, dtype=float)
        if self.launch_direction == "down":
            return -np.asarray(self.parent.up, dtype=float)
        return -np.asarray(self.parent.forward, dtype=float)

    def initial_velocity(self) -> np.ndarray:
        """
        The world velocity of an ordnance launched now: the ship's velocity plus
        the launch speed along the launch direction. It keeps that speed for its
        whole life.

        :return: The world velocity, in m/s
        """
        return (
            np.asarray(self.parent.speed, dtype=float)
            + self.speed_mps * self.launch_direction_vector()
        )

    def launch(self, target_id: uuid.UUID | None = None) -> bool:
        """
        Launch one unit of ordnance, if any is left and the launcher is ready.

        :param target_id: The target a missile pursues (ignored by the other
            types). None fires it blind, like a rocket.
        :return: True if launched, False if out of stock or reloading
        """
        if self.stock <= 0:
            return False
        if not self._ready_to_fire():
            # Still reloading -- do not spend a unit of ordnance.
            return False
        OrdnanceController(
            game=self.game,
            launcher=self,
            target_id=target_id if self.category == "missile" else None,
        )
        self.stock -= 1
        LOGGER.info(
            "%s launched a %s (%d left)", self.parent.parent.name, self.name, self.stock
        )
        return True

    def clean(self):
        """
        Cleans the target lock, then drops the upward references (see
        :meth:`Weapon.clean`).
        """
        if self.target_lock is not None:
            self.target_lock.clean()
            self.target_lock = None
        super().clean()
