from __future__ import annotations

import gc
import logging
import sys
from typing import TYPE_CHECKING, Any

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.energy import (
    ENGINES,
    LASERS,
    SHIELD_REGEN_DELAY_S,
    SHIELDS,
    EnergySystem,
)
from space_flight.actors.ship import Ship, turn_rate_scale
from space_flight.ai.auto_aim import AutoAim
from space_flight.fx.spark_fx import IonCrackle
from space_flight.global_architecture.gameplay_settings import (
    auto_aim_params,
    gameplay_config,
)
from space_flight.utils.state_machine import Cooldown
from space_flight.weapons import ION, ION_DAMAGE_FACTOR, PHYSICAL
from space_flight.weapons.laser_cannon import LaserCannon
from space_flight.weapons.loadout import Loadout
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
        loadout: Loadout | None = None,
    ):
        """
        :param game: The game/flight state
        :param parent: The controlling Player or Bot
        :param ship_type: The fighter model, i.e. its configuration directory
        :param ini_position: Initial world position
        :param ini_orientation: Initial orientation quaternion (w, x, y, z)
        :param ini_speed: Initial world velocity
        :param is_cockpit: Whether it is the player's fighter
        :param team: Its team
        :param loadout: Its weapons; None for its configuration's default
        """
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

        # Disabled (dead engines), it crackles with ion sparks, unless it is
        # the player's (seen from its cockpit)
        self.is_cockpit = is_cockpit
        self.ion_crackle = IonCrackle()

        # Engine and laser gauges, and the power distribution between systems
        self.energy = EnergySystem(
            has_shields=self.max_shield > 0.0, **self.conf["energy"]
        )

        self.loadout = (
            Loadout.from_conf(self.conf.get("loadout", {}))
            if loadout is None
            else loadout
        )

        # Initialize cannons, with the player's or the bots' gameplay settings
        side = "player" if is_cockpit else "bots"
        settings = gameplay_config(self.game)[side]
        self.target_id = None
        self.auto_aim = AutoAim(
            game=self.game, parent=self, **auto_aim_params(self.game, side)
        )
        self.laser_cannon = LaserCannon(
            game=self.game,
            parent=self,
            energy=self.energy,
            deviation_cone_deg=settings["deviation_deg"],
            damage_multiplier=settings["damage_multiplier"],
            damage_type=self.loadout.lasers,
        )

        # Ordnance: one launcher per loadout entry, in the loadout's order, each
        # with its own limited stock
        self.ordnance_launchers = [
            OrdnanceLauncher(
                game=self.game,
                parent=self,
                name=name,
                stock=stock,
                damage_multiplier=settings["damage_multiplier"],
            )
            for name, stock in self.loadout.ordnance.items()
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
        self._attach_hull_collider()

    def move(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Moves the ship (see :meth:`Ship.move`), boost permitting, spends and
        refills the engine and laser gauges, crackles while disabled (dead
        engines), then updates auto-aim acquisition and the missile locks

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
        self._crackle_if_disabled()

        # Compute target acquisition
        self.auto_aim.compute_acquisition()
        self._update_missile_locks()

    def _crackle_if_disabled(self):
        """
        While its engines are dead (it is disabled), the fighter crackles with
        ion sparks, like a disabled subsystem; not the player's, seen from its
        cockpit.
        """
        if self.energy.is_engine_dead and not self.is_cockpit:
            self.ion_crackle.update(
                game=self.game,
                position=self.position,
                radius_m=self.hit_box_radius_m,
                velocity=self.speed,
            )

    def _turn_rate_scale(self, throttle: float) -> float:
        """
        Fraction of the max turn rates available, given the throttle command
        (see turn_rate_scale) and the engine gauge's bonus.

        :param throttle: Throttle command
        :return: The scale applied to the turn rate commands
        """
        return turn_rate_scale(throttle) * self.energy.turn_rate_factor()

    def thrust_factor(self) -> float:
        """
        :return: The engine gauge's bonus on thrust, 0 while the engines are dead
        """
        return self.energy.thrust_factor()

    def engines_online(self) -> bool:
        """
        :return: Whether the engines run, i.e. are not dead for lack of energy
        """
        return not self.energy.is_engine_dead

    @property
    def shield_level(self) -> float:
        """
        A fighter's shield is a plain scalar pool.

        :return: The current shield strength
        """
        return self.shield

    def _armed_missile(self) -> OrdnanceLauncher | None:
        """
        :return: The selected secondary weapon if it is a missile launcher with
            stock left, else None
        """
        launcher = self.selected_secondary
        if launcher is None or launcher.target_lock is None or launcher.stock <= 0:
            return None
        return launcher

    def _update_missile_locks(self):
        """
        Only the armed missile works on its lock: the others drop theirs, so
        switching back to one starts its lock delay over.
        """
        armed_missile = self._armed_missile()
        for launcher in self.ordnance_launchers:
            if launcher.target_lock is None:
                continue
            if launcher is armed_missile:
                launcher.target_lock.update()
            else:
                launcher.target_lock.reset()

    @property
    def is_missile_locked(self) -> bool:
        """Whether a missile launched now would be guided to the target."""
        armed_missile = self._armed_missile()
        return armed_missile is not None and armed_missile.is_locked

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
        too: it just launches nothing. The new selection reloads first.
        """
        candidates = self.secondary_cycle()
        if not candidates:
            self.selected_secondary = None
            return
        if self.selected_secondary in candidates:
            index = candidates.index(self.selected_secondary)
            self.select_secondary(candidates[(index + 1) % len(candidates)])
        else:
            self.select_secondary(candidates[0])

    def select_secondary(self, launcher: OrdnanceLauncher):
        """
        Select a secondary weapon, which reloads if it was not selected already.

        :param launcher: The launcher to select
        """
        if launcher is not self.selected_secondary:
            launcher.restart_reload()
        self.selected_secondary = launcher

    def selected_secondary_with_stock(self, category: str) -> OrdnanceLauncher | None:
        """
        :param category: The ordnance type ("bomb", "missile", "rocket"...)
        :return: The selected secondary weapon if it is of that type with stock
            left, else None
        """
        launcher = self.selected_secondary
        if launcher is None or launcher.category != category or launcher.stock <= 0:
            return None
        return launcher

    def fire_secondary(self) -> bool:
        """
        Launch the selected secondary weapon, then select the next one with stock
        left once its stock runs out. A missile is guided to the target only if
        locked on it (see is_missile_locked); otherwise it flies blind.

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
        any (the selection stays put otherwise). The new selection reloads
        first.
        """
        cycle = self.secondary_cycle()
        index = cycle.index(self.selected_secondary)
        for step in range(1, len(cycle)):
            launcher = cycle[(index + step) % len(cycle)]
            if launcher.stock > 0:
                self.select_secondary(launcher)
                return

    def drop_flare(self) -> bool:
        """
        Drop a flare behind the ship, if any is left. It is offered to the
        missiles homing on the ship, which it may decoy (see
        OrdnanceController.offer_decoy).

        :return: True if dropped, False if out of flares or reloading
        """
        if self.flare_launcher is None:
            return False
        flare_controller = self.flare_launcher.launch()
        if flare_controller is None:
            return False
        # Decoying a missile withdraws its message: iterate over a copy
        for incoming in list(self.incoming_missiles.values()):
            incoming.controller.offer_decoy(flare_controller.pawn)
        return True

    def _launch(self, launcher: OrdnanceLauncher | None) -> bool:
        """
        Launch one unit from one of the ship's launchers, at the current target
        (only a locked missile uses it).

        :param launcher: The launcher (None is a no-op)
        :return: True if launched
        """
        if launcher is None:
            return False
        return launcher.launch(target_id=self.target_id) is not None

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply physical damage to the shield first, the overflow to health. Ion
        damage drains the shield and energy gauges instead (see
        :meth:`_drain_gauges`). Any hit holds off shield regeneration for a
        while.

        :param damage: The amount of damage to apply
        :param damage_type: the type of damage to apply (PHYSICAL, ION)
        """
        # A wreck in its death spin takes no further damage (hits cannot
        # re-trigger death), though collision pushes still shove it around.
        if self.is_dying:
            return
        if damage > 0.0:
            self.shield_regen_cooldown.trigger()
        # Apply damage to health and shield
        if damage_type == PHYSICAL:
            if self.shield - damage >= 0.0:
                self.shield -= damage
            else:
                health_damage = damage - self.shield
                self.health -= health_damage
                self.shield = 0.0
        elif damage_type == ION:
            self._drain_gauges(damage * ION_DAMAGE_FACTOR)
        else:
            raise NotImplementedError

    def _drain_gauges(self, energy_damage: float):
        """
        Split an ion hit equally between the gauges that are not empty yet: the
        shield (in hit points), the engines and the lasers (in energy units).
        Health is untouched, and a gauge cannot take more than it holds.

        :param energy_damage: The energy the hit drains in all
        """
        gauges = [
            system
            for system, level in (
                (SHIELDS, self.shield),
                (ENGINES, self.energy.engines),
                (LASERS, self.energy.lasers),
            )
            if level > 0.0
        ]
        if not gauges:
            return
        share = energy_damage / len(gauges)
        for system in gauges:
            if system == SHIELDS:
                self.shield = max(self.shield - share, 0.0)
            else:
                self.energy.drain(system, share)

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
            app = self.game.app  # Ship.clean drops self.game
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
                LOGGER.info(app.taskMgr.getAllTasks())
