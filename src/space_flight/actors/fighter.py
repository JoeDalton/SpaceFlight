from __future__ import annotations

import gc
import logging
import sys
from typing import TYPE_CHECKING, Any

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.energy import SHIELD_REGEN_DELAY_S, EnergySystem
from space_flight.actors.ship import Ship, turn_rate_scale
from space_flight.ai.auto_aim import AutoAim
from space_flight.game.collisions import attach_collision_sphere
from space_flight.utils.state_machine import Cooldown
from space_flight.weapons.laser_cannon import LaserCannon
from space_flight.weapons.ordnance_launcher import SECONDARY_TYPES, OrdnanceLauncher

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


class Fighter(Ship):
    """
    A class for fighter planes and light bombers
    (quick, manoeuverable, have forward cannons, chase targets...)
    """

    def __init__(
        self,
        game: FlightState,
        parent: Any,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_speed: np.ndarray = np.zeros(3),
        is_cockpit: bool = True,
        team: int = 0,
    ):
        super().__init__(
            game=game,
            parent=parent,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            ini_speed=ini_speed,
            is_cockpit=is_cockpit,
            team=team,
        )

        # Actor category, so target filters can single fighters out.
        self.category = "fighter"

        # Setup integrated shield
        self.max_shield = self.conf["shield"]
        self.shield = self.max_shield
        # Rate with balanced power (see EnergySystem.shield_regen_rate)
        self.shield_regen_rate = self.conf["shield_regen_rate"]
        # The shield does not regenerate for a while after a hit
        self.shield_regen_cooldown = Cooldown(
            duration_s=SHIELD_REGEN_DELAY_S, clock=self.game.game_time.get_current_time
        )

        # Engine and laser gauges, and the power distribution between systems
        self.energy = EnergySystem(
            has_shields=self.max_shield > 0.0,
            laser_shot_energy_cost=self.conf["laser_shot_energy_cost"],
        )

        # Initialize cannons
        # TODO auto-aim parameters from difficulty config file
        self.target_id = None
        self.auto_aim = AutoAim(game=self.game, parent=self)
        self.laser_cannon = LaserCannon(game=self.game, parent=self, energy=self.energy)

        # Ordnance: one launcher per loadout entry, in the configuration's order,
        # each with its own limited stock
        self.ordnance_launchers = [
            OrdnanceLauncher(game=self.game, parent=self, name=name, stock=stock)
            for name, stock in self.conf.get("loadout", {}).items()
        ]
        # The selected secondary weapon (a bomb, rocket or missile launcher),
        # fired by fire_secondary
        self.selected_secondary = None
        self.cycle_secondary()
        # Flares have their own trigger (see drop_flare)
        self.flare_launcher = next(
            (
                launcher
                for launcher in self.ordnance_launchers
                if launcher.category == "flare"
            ),
            None,
        )

        # Initialize collisions
        self.hit_box_radius_m = self.conf["hit_box_radius_m"]
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name="ship",
            radius=self.hit_box_radius_m,
            collider_type="destructible",
            parent_node=self.node,
            parent_object=self,
        )

        # Set explosion size for death animation
        self.explosion_scale = self.conf["explosion_scale"]

    def move(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Moves the ship (see :meth:`Ship.move`), boost permitting, spends and
        refills the engine and laser gauges, then updates auto-aim acquisition

        :param throttle: Throttle command in [0, 1], above 1 for boost
        :param yaw_rate: Yaw rate command in [-1, 1]
        :param pitch_rate: Pitch rate command in [-1, 1]
        :param roll_rate: Roll rate command in [-1, 1]
        """
        # No boost on an exhausted engine gauge
        throttle = self.energy.limit_throttle(throttle)
        super().move(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )
        self.energy.update(
            dt=self.game.game_time.get_time_step(),
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
        )

        # Compute target acquisition
        self.auto_aim.compute_acquisition()

    def _turn_rate_scale(self, throttle: float) -> float:
        """
        Fraction of the max turn rates available, given the throttle command
        (see turn_rate_scale) and the engine gauge's bonus or penalty.

        :param throttle: Throttle command
        :return: The scale applied to the turn rate commands
        """
        return turn_rate_scale(throttle) * self.energy.turn_rate_factor()

    def _thrust_factor(self) -> float:
        """
        :return: The engine gauge's bonus or penalty on thrust
        """
        return self.energy.thrust_factor()

    @property
    def shield_level(self) -> float:
        """
        A fighter's shield is a plain scalar pool.

        :return: The current shield strength
        """
        return self.shield

    def secondary_cycle(self) -> list[OrdnanceLauncher]:
        """
        :return: The secondary weapons cycle_secondary loops over: the bomb,
            rocket and missile launchers, spent ones included, in loadout order
        """
        return [
            launcher
            for launcher in self.ordnance_launchers
            if launcher.category in SECONDARY_TYPES
        ]

    def cycle_secondary(self):
        """
        Select the next secondary weapon (bomb, rocket or missile launcher), in
        loadout order, looping back to the first. A spent one can be selected
        too: it just launches nothing.
        """
        candidates = self.secondary_cycle()
        if not candidates:
            self.selected_secondary = None
            return
        if self.selected_secondary in candidates:
            index = candidates.index(self.selected_secondary)
            self.selected_secondary = candidates[(index + 1) % len(candidates)]
        else:
            self.selected_secondary = candidates[0]

    def fire_secondary(self) -> bool:
        """
        Launch the selected secondary weapon, then select the next one with stock
        left once its stock runs out. A missile is given the current target only
        if auto-aim has locked onto it; otherwise it flies blind, like a rocket.

        The launcher is rate-limited, so a launch can be refused while reloading
        even with stock to spare; stock is only spent on an actual launch.

        :return: True if launched, False if out of stock or reloading
        """
        launched = self._launch(self.selected_secondary)
        if launched and self.selected_secondary.stock <= 0:
            self._select_next_secondary_with_stock()
        return launched

    def _select_next_secondary_with_stock(self):
        """
        Move the selection on to the next secondary weapon with stock left, if
        any (the selection stays put otherwise).
        """
        cycle = self.secondary_cycle()
        index = cycle.index(self.selected_secondary)
        for step in range(1, len(cycle)):
            launcher = cycle[(index + step) % len(cycle)]
            if launcher.stock > 0:
                self.selected_secondary = launcher
                return

    def drop_flare(self) -> bool:
        """
        Drop a flare behind the ship, if any is left.

        :return: True if dropped, False if out of flares or reloading
        """
        return self._launch(self.flare_launcher)

    def _launch(self, launcher: OrdnanceLauncher | None) -> bool:
        """
        Launch one unit from one of the ship's launchers, giving it the current
        target only if auto-aim has locked onto it (only a missile uses it).

        :param launcher: The launcher (None is a no-op)
        :return: True if launched
        """
        if launcher is None:
            return False
        target_id = self.target_id if self.auto_aim.is_target_acquired else None
        return launcher.launch(target_id=target_id)

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply damage to the shield first, the overflow to health. Any hit holds
        off shield regeneration for a while.

        :param damage: The amount of damage to apply
        :param damage_type: the type of damage to apply (physical, energy)
        """
        # A wreck in its death spin takes no further damage (hits cannot
        # re-trigger death), though collision pushes still shove it around.
        if self.is_dying:
            return
        if damage > 0.0:
            self.shield_regen_cooldown.trigger()
        # Apply damage to health and shield
        if damage_type == "physical":
            if self.shield - damage >= 0.0:
                self.shield -= damage
            else:
                health_damage = damage - self.shield
                self.health -= health_damage
                self.shield = 0.0
        else:
            raise NotImplementedError

    def ship_handle_health(self):
        """
        Regenerates the shield at its share of the power (unless just hit) and
        clamps health to its maximum
        """
        if self.shield_regen_cooldown.ready():
            dt = self.game.game_time.get_time_step()
            regen_rate = self.energy.shield_regen_rate(self.shield_regen_rate)
            self.shield = min(max(0.0, self.shield + dt * regen_rate), self.max_shield)
        self.health = min(self.health, self.max_health)

    def clean(self):
        """
        Clean references before deleting the ship so that they can be properly
        garbage collected
        """
        if not self.is_clean:
            super().clean()
            # Remove fighter-specific attributes
            self.auto_aim.clean()
            self.auto_aim = None
            self.laser_cannon.clean()
            self.laser_cannon = None
            for launcher in self.ordnance_launchers:
                launcher.clean()
            self.ordnance_launchers = []
            self.selected_secondary = None

            if DEBUG_DELETION:
                LOGGER.info("Cleaned ship")
                LOGGER.info(f"ship nref = {sys.getrefcount(self)}")
                LOGGER.info(f"ship references {gc.get_referrers(self)}")
                LOGGER.info(self.game.app.taskMgr.getAllTasks)
