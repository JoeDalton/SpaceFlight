"""
Fighter energy management.

A fighter's power plant feeds three gauges: engines, lasers and shields (the
latter only on shielded ships). Each gauge refills at its share of the plant's
output. By default the power is split equally, but the pilot can redirect most
of it to one system, at a loss of efficiency (see the ENERGY_SHARES_* tables).

Gauges over half full grant bonuses (engines: thrust and turn rate, lasers:
damage), ramping linearly up to a full gauge. They are spent by:

- engines: boosting and hard manoeuvres (pitch or yaw commanded above
  HARD_MANEUVER_COMMAND_THRESHOLD of the current max rate). An empty engine
  gauge kills the engines: no thrust, no braking, no change of rotation (the
  ship drifts, spinning as it was) until the gauge refills to
  ENGINE_RESTART_LEVEL, and boost stays locked out until
  BOOST_REENABLE_ENGINE_LEVEL.
- lasers: each bolt costs the ship's laser_shot_cost. Below that, the cannons
  are silent.
- shields: taking hits. The shield gauge is the fighter's own shield strength
  (see :class:`~space_flight.actors.fighter.Fighter`); this module only sets
  its regeneration rate.

Ion hits drain the gauges too (see :meth:`EnergySystem.drain`).

Each ship sizes its engine and laser gauges (their capacity) and sets their
refill rates and costs in its configuration's ``energy`` block, in energy units
(the same scale as damage, for the ion hits). The gauges themselves are kept as
fractions in [0, 1].
"""

from __future__ import annotations

ENGINES = "engines"
LASERS = "lasers"
SHIELDS = "shields"
BALANCED = "balanced"

# Share of the power plant's output each system receives, per distribution mode,
# in cycling order. Redirected modes add up to less than 1: redirecting power
# loses some of it.
ENERGY_SHARES_SHIELDED = {
    BALANCED: {ENGINES: 1.0 / 3.0, LASERS: 1.0 / 3.0, SHIELDS: 1.0 / 3.0},
    SHIELDS: {ENGINES: 0.07, LASERS: 0.07, SHIELDS: 0.75},
    ENGINES: {ENGINES: 0.75, LASERS: 0.07, SHIELDS: 0.07},
    LASERS: {ENGINES: 0.07, LASERS: 0.75, SHIELDS: 0.07},
}
ENERGY_SHARES_UNSHIELDED = {
    BALANCED: {ENGINES: 0.5, LASERS: 0.5, SHIELDS: 0.0},
    ENGINES: {ENGINES: 0.8, LASERS: 0.1, SHIELDS: 0.0},
    LASERS: {ENGINES: 0.1, LASERS: 0.8, SHIELDS: 0.0},
}

# Pitch or yaw command (fraction of the current max rate) above which a
# manoeuvre is hard. Roll is free.
HARD_MANEUVER_COMMAND_THRESHOLD = 0.9
# Once the engine gauge runs dry, boost stays locked out until it refills to
# this level (hysteresis, so boost does not stutter on an almost empty gauge)
BOOST_REENABLE_ENGINE_LEVEL = 0.5
# Once the engine gauge runs dry, the engines stay dead until it refills to this
# level
ENGINE_RESTART_LEVEL = 0.15

# Bonuses ramp linearly from 0 at BONUS_GAUGE_THRESHOLD to their max at a full
# gauge
BONUS_GAUGE_THRESHOLD = 0.5
ENGINE_BONUS_MAX_THRUST_FACTOR = 0.2
ENGINE_BONUS_MAX_TURN_RATE_FACTOR = 0.2
LASER_BONUS_MAX_DAMAGE_FACTOR = 0.5

# Shields do not regenerate for this long after the fighter is hit
SHIELD_REGEN_DELAY_S = 3.0


def bonus_factor(level: float, max_bonus: float) -> float:
    """
    Multiplier granted by a gauge: 1 up to BONUS_GAUGE_THRESHOLD, then rising
    linearly to 1 + max_bonus at a full gauge.

    :param level: The gauge level, in [0, 1]
    :param max_bonus: The bonus at a full gauge (0.2 for +20%)
    :return: The multiplier
    """
    ramp = (level - BONUS_GAUGE_THRESHOLD) / (1.0 - BONUS_GAUGE_THRESHOLD)
    return 1.0 + max_bonus * min(max(ramp, 0.0), 1.0)


class EnergySystem:
    """
    A fighter's engine and laser gauges, and the power distribution between
    engines, lasers and shields.

    The owner calls :meth:`update` each frame with its flight commands, and
    reads the factors to scale its thrust, turn rates, laser damage and shield
    regeneration.
    """

    def __init__(
        self,
        has_shields: bool,
        engine_capacity: float,
        laser_capacity: float,
        engine_regen_rate: float,
        laser_regen_rate: float,
        boost_drain_rate: float,
        hard_maneuver_drain_rate: float,
        laser_shot_cost: float,
    ):
        """
        The energy amounts are in energy units, the rates in energy units per
        second (a ship's configuration ``energy`` block).

        :param has_shields: Whether the ship has shields to power
        :param engine_capacity: Energy held by a full engine gauge
        :param laser_capacity: Energy held by a full laser gauge
        :param engine_regen_rate: Engine gauge refill rate if the engines
            received all of the plant's output
        :param laser_regen_rate: Laser gauge refill rate if the lasers received
            all of the plant's output
        :param boost_drain_rate: Engine energy spent boosting
        :param hard_maneuver_drain_rate: Engine energy spent in hard manoeuvres
        :param laser_shot_cost: Laser energy spent per bolt
        """
        if engine_capacity <= 0.0 or laser_capacity <= 0.0:
            raise ValueError("Energy capacities must be positive")
        self.has_shields = has_shields
        self.capacities = {ENGINES: engine_capacity, LASERS: laser_capacity}
        # Rates and costs, converted to gauge fractions
        self.engine_regen_rate = engine_regen_rate / engine_capacity
        self.laser_regen_rate = laser_regen_rate / laser_capacity
        self.boost_drain_rate = boost_drain_rate / engine_capacity
        self.hard_maneuver_drain_rate = hard_maneuver_drain_rate / engine_capacity
        self.laser_shot_cost = laser_shot_cost / laser_capacity
        self.shares = (
            ENERGY_SHARES_SHIELDED if has_shields else ENERGY_SHARES_UNSHIELDED
        )
        self.engines = 1.0
        self.lasers = 1.0
        self.mode = BALANCED
        self.is_boost_locked = False
        self.is_engine_dead = False

    @property
    def modes(self) -> list[str]:
        """
        :return: The distribution modes available, in cycling order
        """
        return list(self.shares)

    def set_mode(self, mode: str):
        """
        Select the power distribution. A mode the ship cannot use (shields on an
        unshielded ship) is ignored.

        :param mode: BALANCED, or the system to favour (ENGINES, LASERS, SHIELDS)
        """
        if mode in self.shares:
            self.mode = mode

    def cycle_mode(self):
        """
        Select the next power distribution: balanced, shields (if any),
        engines, lasers, then back to balanced.
        """
        modes = self.modes
        self.mode = modes[(modes.index(self.mode) + 1) % len(modes)]

    def share(self, system: str) -> float:
        """
        :param system: ENGINES, LASERS or SHIELDS
        :return: The share of the plant's output the system currently receives
        """
        return self.shares[self.mode][system]

    def is_favoured(self, system: str) -> bool:
        """
        :param system: ENGINES, LASERS or SHIELDS
        :return: Whether power is currently redirected to that system
        """
        return self.mode == system

    def limit_throttle(self, throttle: float) -> float:
        """
        :param throttle: Throttle command, above 1 for boost
        :return: The command, capped to full thrust while boost is locked out
        """
        if self.is_boost_locked:
            return min(throttle, 1.0)
        return throttle

    def update(self, dt: float, throttle: float, yaw_rate: float, pitch_rate: float):
        """
        Refill the engine and laser gauges at their share of the plant's output,
        and drain the engine gauge for boosting and hard manoeuvres (dead
        engines spend nothing).

        :param dt: Time step, in seconds
        :param throttle: Throttle command actually applied, above 1 for boost
        :param yaw_rate: Yaw rate command, fraction of the current max rate
        :param pitch_rate: Pitch rate command, fraction of the current max rate
        """
        engines_rate = self.share(ENGINES) * self.engine_regen_rate
        if not self.is_engine_dead:
            if throttle > 1.0:
                engines_rate -= self.boost_drain_rate
            if max(abs(yaw_rate), abs(pitch_rate)) > HARD_MANEUVER_COMMAND_THRESHOLD:
                engines_rate -= self.hard_maneuver_drain_rate
        self.engines = min(max(self.engines + dt * engines_rate, 0.0), 1.0)

        laser_rate = self.share(LASERS) * self.laser_regen_rate
        self.lasers = min(max(self.lasers + dt * laser_rate, 0.0), 1.0)

        self._update_engine_state()

    def _update_engine_state(self):
        """
        Kill the engines and lock boost out on an empty engine gauge; restart
        them, then re-enable boost, as it refills.
        """
        if self.engines <= 0.0:
            self.is_engine_dead = True
            self.is_boost_locked = True
        else:
            if self.engines >= ENGINE_RESTART_LEVEL:
                self.is_engine_dead = False
            if self.engines >= BOOST_REENABLE_ENGINE_LEVEL:
                self.is_boost_locked = False

    def drain(self, system: str, amount: float):
        """
        Take energy out of a gauge (an ion hit). Emptying the engine gauge kills
        the engines at once.

        :param system: ENGINES or LASERS
        :param amount: The energy taken, in energy units
        """
        level = getattr(self, system) - amount / self.capacities[system]
        setattr(self, system, max(level, 0.0))
        self._update_engine_state()

    def thrust_factor(self) -> float:
        """
        :return: The multiplier the engine gauge applies to thrust: its bonus, or
            0 while the engines are dead
        """
        if self.is_engine_dead:
            return 0.0
        return bonus_factor(self.engines, ENGINE_BONUS_MAX_THRUST_FACTOR)

    def turn_rate_factor(self) -> float:
        """
        :return: The multiplier the engine gauge applies to the max turn rates
            (dead engines do not turn at all: the ship keeps its rotation, see
            Ship.engines_online)
        """
        return bonus_factor(self.engines, ENGINE_BONUS_MAX_TURN_RATE_FACTOR)

    def laser_damage_factor(self) -> float:
        """
        :return: The multiplier the laser gauge applies to bolt damage
        """
        return bonus_factor(self.lasers, LASER_BONUS_MAX_DAMAGE_FACTOR)

    def can_fire_laser(self) -> bool:
        """
        :return: Whether the laser gauge holds enough energy for a bolt
        """
        return self.lasers >= self.laser_shot_cost

    def consume_laser_shot(self):
        """
        Spend one bolt's worth of laser energy.
        """
        self.lasers = max(self.lasers - self.laser_shot_cost, 0.0)

    def shield_regen_rate(self, balanced_rate: float) -> float:
        """
        Shield regeneration rate under the current distribution, scaled from the
        ship's rate with balanced power.

        :param balanced_rate: The ship's shield regeneration rate with balanced
            power (its configured shield_regen_rate)
        :return: The current regeneration rate
        """
        if not self.has_shields:
            return 0.0
        return balanced_rate * self.share(SHIELDS) / self.shares[BALANCED][SHIELDS]
