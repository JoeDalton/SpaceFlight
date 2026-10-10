from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import yaml

from space_flight import DATAFILES_PATH
from space_flight.actors.major_ship.targeting_system import TargetingSystem
from space_flight.actors.major_ship.tracking_mount import TrackingMount
from space_flight.ai import Personality
from space_flight.ai.auto_aim import AutoAim
from space_flight.global_architecture.gameplay_settings import (
    auto_aim_params,
    gameplay_config,
)
from space_flight.weapons.laser_cannon import LaserCannon

if TYPE_CHECKING:
    from space_flight.actors.bot import Bot
    from space_flight.actors.ship import Ship
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


class Turret(TrackingMount):
    """
    A laser turret: a :class:`TrackingMount` that fires laser cannons.

    It adds laser cannons, an auto-aim held ready, and the per-frame fire
    decision in :meth:`_operate`: the turret fires when its barrel is aligned
    with the navigator's published lead solution (:attr:`aim_direction`) and the
    prey is in range (:attr:`target_distance_m`).

    A living targeting system on the ship grants auto-aim and a faster rate of
    fire (see :meth:`_apply_targeting_support`).

    :param game: The game/flight state
    :param parent: The controlling Bot
    :param turret_type: The turret model/config name
    :param mounted_on: The ship this turret is bolted onto
    :param base_position: Mounting position relative to the ship node
    :param base_orientation: Mounting orientation (quaternion) on the ship
    :param ini_yaw_deg: Initial yaw angle
    :param ini_pitch_deg: Initial pitch angle
    :param personality: Behaviour parameters (fire thresholds, shared with the AI)
    """

    def __init__(
        self,
        game: FlightState,
        parent: Bot,
        turret_type: str,
        mounted_on: Ship,
        base_position: np.ndarray = np.zeros(3),
        base_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_yaw_deg: float = 0.0,
        ini_pitch_deg: float = 30.0,
        personality: dict = Personality.TURRET_DEFAULT,
    ):
        # Load configuration first: it feeds the TrackingMount parameters below
        filepath = DATAFILES_PATH / f"models/turrets/{turret_type}/configuration.yaml"
        with open(filepath, "r") as f:
            conf = yaml.safe_load(f)

        super().__init__(
            game=game,
            parent=parent,
            mounted_on=mounted_on,
            conf=conf,
            model_type=turret_type,
            base_position=base_position,
            base_orientation=base_orientation,
            ini_yaw_deg=ini_yaw_deg,
            ini_pitch_deg=ini_pitch_deg,
            personality=personality,
            name="turret",
        )

        bots_settings = gameplay_config(self.game)["bots"]
        self.laser_cannon = LaserCannon(
            game=self.game,
            parent=self,
            parent_node=self.turret_model.cannon_node,
            deviation_cone_deg=bots_settings["deviation_deg"],
            damage_multiplier=bots_settings["damage_multiplier"],
        )
        self.base_fire_delay = self.laser_cannon.fire_delay
        # Auto-aim is held ready but only exposed as self.auto_aim while a
        # targeting system is alive (None makes the cannon fire straight ahead).
        # _targeting_source is the system it was last tuned from, so it is only
        # reconfigured on a change.
        self._auto_aim = AutoAim(game=self.game, parent=self)
        self.auto_aim = None
        self._targeting_source = None

    def _operate(self):
        """
        Per-frame turret action: refresh the targeting-system support, then fire
        if the published lead solution says we are aligned and in range.
        """
        self._apply_targeting_support()
        self._fire_if_engaged()

    def _fire_if_engaged(self):
        """
        Fire the cannons when the barrel is aligned with the navigator's lead
        solution and the prey is within firing range.
        """
        fire = self.personality["navigator"]["fire"]
        firing_alignment = np.dot(self.aim_direction, self.forward)
        if (self.target_distance_m < fire["maximum_distance_m"]) and (
            firing_alignment > fire["minimum_cos_angle"]
        ):
            self.laser_cannon.fire()

    def _active_targeting_system(self) -> TargetingSystem | None:
        """
        Finds a living targeting system on the ship this turret is mounted on.

        :return: The active :class:`TargetingSystem` boosting this turret, or
            None if its ship has none alive
        """
        for sub_system in getattr(self.mounted_on, "sub_systems", []):
            if isinstance(sub_system, TargetingSystem) and not sub_system.is_dead:
                return sub_system
        return None

    def _auto_aim_params(self, targeting_system: TargetingSystem) -> dict:
        """
        :param targeting_system: The targeting system boosting this turret
        :return: The auto-aim tuning: the bots' gameplay settings, overridden by
            the targeting system's own tuning, except for whether auto-aim is
            enabled at all, which only the gameplay settings set
        """
        bots_params = auto_aim_params(self.game, "bots")
        # TODO The targeting system's tuning ignores the difficulty: e.g. a CR-90
        #  keeps its 0.5 s lock and 8 degree assist on easy. Scale it with the
        #  bots' settings instead of overriding them?
        return {
            **bots_params,
            **targeting_system.auto_aim_params,
            "enabled": bots_params["enabled"],
        }

    def _apply_targeting_support(self):
        """
        Applies (or removes) the boosts granted by the ship's targeting system:
        auto-aim and a faster fire rate, or straight shots at the base rate when
        none is alive.
        """
        targeting_system = self._active_targeting_system()
        if targeting_system is None:
            # No fire control: fire straight ahead at the base rate.
            self.auto_aim = None
            self.laser_cannon.fire_delay = self.base_fire_delay
            self._targeting_source = None
        else:
            # Fire control online: retune the auto-aim from this system (only
            # when it just came online or changed), then lead the target and
            # fire faster.
            if targeting_system is not self._targeting_source:
                self._auto_aim.configure(**self._auto_aim_params(targeting_system))
                self._targeting_source = targeting_system
            self.auto_aim = self._auto_aim
            self.auto_aim.compute_acquisition()
            self.laser_cannon.fire_delay = (
                self.base_fire_delay / targeting_system.fire_rate_multiplier
            )

    def clean(self):
        """
        Cleans the turret's cannons and auto-aim, then the tracking mount itself.
        """
        if not self.is_clean:
            self.laser_cannon.clean()
            self.laser_cannon = None
            self._auto_aim.clean()
            self._auto_aim = None
            self.auto_aim = None
            super().clean()
