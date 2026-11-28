"""
Ordnance (bombs, rockets, missiles, flares): configuration loading and the
launcher a ship carries for each entry of its loadout.

Every kind of ordnance shares the same code; they differ only by their
configuration (``datafiles/models/ordnance/<name>/configuration.yaml``): the
launch direction and speed, the guidance and decoy response (missiles only), the
target mobility (missiles, rockets) and the collision role (flares stop other
ordnance, and may lure a guided missile).
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
from space_flight.ai.aim_assist import AssistCone, aim_toward, target_kinematics
from space_flight.ai.target_lock import TargetLock
from space_flight.weapons import DAMAGE_TYPES, Weapon

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
# How a missile falls for a flare (see Fighter.drop_flare): the flare must be
# dropped within decoy_range_m of it and lie within decoy_cone_angle_deg of its
# nose, and then lures it with probability decoy_chance
MISSILE_DECOY_KEYS = ("decoy_range_m", "decoy_cone_angle_deg", "decoy_chance")
# The targets a missile or rocket is fired at, by mobility (see
# FighterTactician._choose_weapon)
TARGET_MOBILITIES = ("agile", "slow")


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
    if conf["type"] in ("missile", "rocket") and (
        conf.get("target_mobility") not in TARGET_MOBILITIES
    ):
        raise ValueError(
            f"Ordnance {name}: unknown target mobility {conf.get('target_mobility')!r}"
        )
    if conf["type"] == "missile":
        missing_keys = [key for key in MISSILE_DECOY_KEYS if key not in conf]
        if missing_keys:
            raise ValueError(f"Ordnance {name}: missing decoy keys {missing_keys}")
        if not 0.0 <= conf["decoy_chance"] <= 1.0:
            raise ValueError(
                f"Ordnance {name}: decoy_chance {conf['decoy_chance']} not in [0, 1]"
            )
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
        damage_multiplier: float = 1.0,
        bomb_assist_angle_deg: float = 0.0,
    ):
        """
        :param game: The game/flight state
        :param parent: The ship carrying the ordnance
        :param name: The ordnance name, i.e. its configuration directory name
        :param stock: How many it carries
        :param damage_multiplier: Scales the damage of every ordnance it launches
        :param bomb_assist_angle_deg: Bombs only (a gameplay setting): the most
            a launched bomb's course is bent from its launch direction toward
            where it meets the target (0 = it goes straight)
        """
        self.conf = load_ordnance_configuration(name)
        super().__init__(
            game,
            parent,
            fire_delay=self.conf["reload_s"],
            damage_multiplier=damage_multiplier,
        )
        # The ordnance takes its damage from this (private) configuration copy
        self.conf["damage"] *= damage_multiplier
        self.name = name
        self.category = self.conf["type"]
        self.damage_type = self.conf["damage_type"]
        self.stock = stock
        self.bomb_assist_cone = AssistCone(bomb_assist_angle_deg)
        # Where it leaves the ship: [right, forward, up], metres, ship frame
        self.position_m = np.asarray(
            parent.conf["ordnance_launcher_position"], dtype=float
        )
        if self.position_m.shape != (3,):
            raise ValueError(
                f"{name}: ordnance_launcher_position must hold 3 numbers, "
                f"got {parent.conf['ordnance_launcher_position']!r}"
            )
        # Launch speed relative to the launching ship, along launch_direction
        self.speed_mps = self.conf["speed_mps"]
        self.launch_direction = self.conf["launch_direction"]
        # Missiles only: guided to the target once locked on it (the ship
        # updates the lock while the launcher is selected, see Fighter.move)
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

    def _aim(self, target_id: uuid.UUID | None) -> tuple[np.ndarray, bool] | None:
        """
        The aim of a bomb launched now at a target (see AssistCone and
        aim_toward, shared with the laser cannons' auto-aim).

        :param target_id: The launching ship's target, if any
        :return: The unit direction the bomb is aimed along, and whether the
            target is within the assist cone; None if there is nothing to aim
            at (not a bomb, no assist, no target or none in the interactions)
        """
        if self.category != "bomb" or self.bomb_assist_cone.max_angle_rad <= 0.0:
            return None
        kinematics = target_kinematics(
            self.game.interactions,
            self.parent.id,
            self.parent.position,
            target_id,
            self.speed_mps,
        )
        if kinematics is None:
            return None
        target_position, lead_offset = kinematics
        nominal = self.launch_direction_vector()
        return aim_toward(
            self.bomb_assist_cone,
            nominal,
            self.launch_position(nominal),
            target_position + lead_offset,
        )

    def aimed_direction(self, target_id: uuid.UUID | None) -> np.ndarray:
        """
        The launch direction of an ordnance launched now at a target. Only a bomb
        is aided: it is aimed at the target's lead position, within the aim
        assist cone around its launch direction. Every other ordnance, or a bomb
        with no target, goes along its launch direction.

        :param target_id: The launching ship's target, if any
        :return: The unit launch direction, in world coordinates
        """
        aim = self._aim(target_id)
        return self.launch_direction_vector() if aim is None else aim[0]

    def is_target_in_assist_cone(self, target_id: uuid.UUID | None) -> bool:
        """
        :param target_id: The launching ship's target, if any
        :return: Whether this is a bomb launcher with its aim assist on and the
            target within the assist cone: a bomb launched now would be aided
        """
        aim = self._aim(target_id)
        return aim is not None and aim[1]

    def launch_position(self, direction: np.ndarray | None = None) -> np.ndarray:
        """
        :param direction: The launch direction (the nominal one by default)
        :return: Where an ordnance launched now starts, in world coordinates:
            the ship's ordnance launcher position, then the ordnance's own
            launch offset along its launch direction
        """
        x, y, z = self.position_m
        return (
            np.asarray(self.parent.position, dtype=float)
            + x * np.asarray(self.parent.right, dtype=float)
            + y * np.asarray(self.parent.forward, dtype=float)
            + z * np.asarray(self.parent.up, dtype=float)
            + self.conf["launch_offset_m"]
            * (self.launch_direction_vector() if direction is None else direction)
        )

    def initial_velocity(self, direction: np.ndarray | None = None) -> np.ndarray:
        """
        The world velocity of an ordnance launched now: the ship's velocity plus
        the launch speed along the launch direction. It keeps that speed for its
        whole life.

        :param direction: The launch direction (the nominal one by default)
        :return: The world velocity, in m/s
        """
        if direction is None:
            direction = self.launch_direction_vector()
        return np.asarray(self.parent.speed, dtype=float) + self.speed_mps * direction

    def launch(self, target_id: uuid.UUID | None = None) -> OrdnanceController | None:
        """
        Launch one unit of ordnance, if any is left and the launcher is ready.

        :param target_id: The target a missile pursues if locked on it (ignored
            by the other types). Otherwise it flies blind, like a rocket.
        :return: The launched ordnance's controller, None if out of stock or
            reloading
        """
        if self.stock <= 0:
            return None
        if not self._ready_to_fire():
            # Still reloading -- do not spend a unit of ordnance.
            return None
        controller = OrdnanceController(
            game=self.game,
            launcher=self,
            target_id=target_id if self.is_locked else None,
            direction=self.aimed_direction(target_id),
        )
        self.stock -= 1
        LOGGER.info(
            "%s launched a %s (%d left)", self.parent.parent.name, self.name, self.stock
        )
        return controller

    @property
    def is_locked(self) -> bool:
        """Whether this is a missile launcher locked on the target."""
        return self.target_lock is not None and self.target_lock.is_locked

    def clean(self):
        """
        Cleans the target lock, then the weapon
        """
        if self.target_lock is not None:
            self.target_lock.clean()
            self.target_lock = None
        super().clean()
