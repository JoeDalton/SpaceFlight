import logging

import numpy as np
import yaml

from space_flight import DATAFILES_PATH
from space_flight.actors.capital_ship.targeting_system import TargetingSystem
from space_flight.actors.laser_cannon import LaserCannon
from space_flight.actors.tracking_mount import TrackingMount
from space_flight.ai import Personality
from space_flight.ai.auto_aim import AutoAim

LOGGER = logging.getLogger()


class Turret(TrackingMount):
    """
    A laser turret: a :class:`TrackingMount` that fires laser cannons.

    It inherits all of its aiming from :class:`TrackingMount` and adds the weapon:
    laser cannons, an auto-aim held ready, and the per-frame fire decision in
    :meth:`_operate`. The fire gate keys off the navigator's published lead
    solution (:attr:`aim_direction` / :attr:`target_distance_m`), so the turret
    fires when its barrel is aligned with where the prey is *going* and the prey
    is in range.

    A ship-mounted targeting system, while alive, grants the turret auto-aim and a
    faster rate of fire (see :meth:`_apply_targeting_support`).

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
        game,
        parent,
        turret_type: str,
        mounted_on,
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

        # Cannons. A turret fires straight down its barrel by default; a living
        # targeting system on the ship grants auto-aim and a faster fire rate,
        # pulled each frame in _operate() (see _apply_targeting_support).
        self.laser_cannon = LaserCannon(
            game=self.game, parent=self, parent_node=self.turret_model.cannon_node
        )
        self.base_fire_delay = self.laser_cannon.fire_delay
        # Auto-aim is held ready but only exposed to the cannon (through
        # self.auto_aim) while a targeting system is alive. self.auto_aim is None
        # otherwise, which the cannon reads as "fire straight ahead". It is
        # retuned from the parameters of whichever targeting system is boosting
        # us; _targeting_source tracks that system so we only reconfigure on a
        # change.
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

    def _active_targeting_system(self):
        """
        Finds a living targeting system on the ship this turret is mounted on.

        :return: The active :class:`TargetingSystem` boosting this turret, or
            ``None`` if its ship has none alive
        """
        for sub_system in getattr(self.mounted_on, "sub_systems", []):
            if isinstance(sub_system, TargetingSystem) and not sub_system.is_dead:
                return sub_system
        return None

    def _apply_targeting_support(self):
        """
        Applies (or removes) the boosts granted by the ship's targeting system.

        While a targeting system is alive the turret gains auto-aim (its shots
        lead the target) and a faster fire rate; with none alive it fires
        straight down the barrel at its base rate.
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
                self._auto_aim.configure(**targeting_system.auto_aim_params)
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
