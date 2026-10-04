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
  gauge locks boost out and penalises thrust and turn rate.
- lasers: each bolt costs the ship's laser_shot_energy_cost (from its
  configuration). Below that, the cannons are silent.
- shields: taking hits. The shield gauge is the fighter's own shield strength
  (see :class:`~space_flight.actors.fighter.Fighter`); this module only sets
  its regeneration rate.

Engine and laser gauges are fractions in [0, 1].
"""

from __future__ import annotations

ENGINES = "engines"
LASERS = "lasers"
SHIELDS = "shields"
BALANCED = "balanced"

# Share of the power plant's output each system receives, per distribution mode.
# Redirected modes add up to less than 1: redirecting power loses some of it.
ENERGY_SHARES_SHIELDED = {
    BALANCED: {ENGINES: 1.0 / 3.0, LASERS: 1.0 / 3.0, SHIELDS: 1.0 / 3.0},
    ENGINES: {ENGINES: 0.75, LASERS: 0.07, SHIELDS: 0.07},
    LASERS: {ENGINES: 0.07, LASERS: 0.75, SHIELDS: 0.07},
    SHIELDS: {ENGINES: 0.07, LASERS: 0.07, SHIELDS: 0.75},
}
ENERGY_SHARES_UNSHIELDED = {
    BALANCED: {ENGINES: 0.5, LASERS: 0.5, SHIELDS: 0.0},
    ENGINES: {ENGINES: 0.8, LASERS: 0.1, SHIELDS: 0.0},
    LASERS: {ENGINES: 0.1, LASERS: 0.8, SHIELDS: 0.0},
}

# Gauge refill rates (fraction of the gauge per second) if the system received
# all of the plant's output
ENGINE_FULL_POWER_REGEN_RATE_PS = 0.15
LASER_FULL_POWER_REGEN_RATE_PS = 0.15

# Engine gauge consumption, in fraction of the gauge per second
BOOST_ENERGY_DRAIN_RATE_PS = 0.12
HARD_MANEUVER_ENERGY_DRAIN_RATE_PS = 0.08
# Pitch or yaw command (fraction of the current max rate) above which a
# manoeuvre is hard. Roll is free.
HARD_MANEUVER_COMMAND_THRESHOLD = 0.9
# Once the engine gauge runs dry, boost stays locked out until it refills to
# this level (hysteresis, so boost does not stutter on an almost empty gauge)
BOOST_REENABLE_ENGINE_LEVEL = 0.5

# Bonuses ramp linearly from 0 at BONUS_GAUGE_THRESHOLD to their max at a full
# gauge
BONUS_GAUGE_THRESHOLD = 0.5
ENGINE_BONUS_MAX_THRUST_FACTOR = 0.2
ENGINE_BONUS_MAX_TURN_RATE_FACTOR = 0.2
LASER_BONUS_MAX_DAMAGE_FACTOR = 0.5

# Empty engine gauge penalty: thrust and turn rates are scaled by the EMPTY
# factors on an empty gauge, fading out linearly up to
# ENGINE_PENALTY_GAUGE_THRESHOLD (so a gauge hovering around zero does not
# flicker between penalised and not)
ENGINE_PENALTY_GAUGE_THRESHOLD = 0.05
ENGINE_EMPTY_THRUST_FACTOR = 0.8
ENGINE_EMPTY_TURN_RATE_FACTOR = 0.8

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


def engine_factor(level: float, max_bonus: float, empty_factor: float) -> float:
    """
    Multiplier granted by the engine gauge: the bonus ramp when over half full
    (see bonus_factor), a penalty fading from empty_factor on an empty gauge to
    1 at ENGINE_PENALTY_GAUGE_THRESHOLD.

    :param level: The engine gauge level, in [0, 1]
    :param max_bonus: The bonus at a full gauge
    :param empty_factor: The multiplier on an empty gauge
    :return: The multiplier
    """
    if level >= ENGINE_PENALTY_GAUGE_THRESHOLD:
        return bonus_factor(level, max_bonus)
    ramp = max(level, 0.0) / ENGINE_PENALTY_GAUGE_THRESHOLD
    return empty_factor + ramp * (1.0 - empty_factor)


class EnergySystem:
    """
    A fighter's engine and laser gauges, and the power distribution between
    engines, lasers and shields.

    The owner calls :meth:`update` each frame with its flight commands, and
    reads the factors to scale its thrust, turn rates, laser damage and shield
    regeneration.
    """

    def __init__(self, has_shields: bool, laser_shot_energy_cost: float):
        """
        :param has_shields: Whether the ship has shields to power
        :param laser_shot_energy_cost: Laser gauge fraction spent per bolt
        """
        self.has_shields = has_shields
        self.laser_shot_energy_cost = laser_shot_energy_cost
        self.shares = (
            ENERGY_SHARES_SHIELDED if has_shields else ENERGY_SHARES_UNSHIELDED
        )
        self.engines = 1.0
        self.lasers = 1.0
        self.mode = BALANCED
        self.is_boost_locked = False

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
        Select the next power distribution: balanced, engines, lasers, shields
        (if any), then back to balanced.
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
        and drain the engine gauge for boosting and hard manoeuvres.

        :param dt: Time step, in seconds
        :param throttle: Throttle command actually applied, above 1 for boost
        :param yaw_rate: Yaw rate command, fraction of the current max rate
        :param pitch_rate: Pitch rate command, fraction of the current max rate
        """
        engines_rate = self.share(ENGINES) * ENGINE_FULL_POWER_REGEN_RATE_PS
        if throttle > 1.0:
            engines_rate -= BOOST_ENERGY_DRAIN_RATE_PS
        if max(abs(yaw_rate), abs(pitch_rate)) > HARD_MANEUVER_COMMAND_THRESHOLD:
            engines_rate -= HARD_MANEUVER_ENERGY_DRAIN_RATE_PS
        self.engines = min(max(self.engines + dt * engines_rate, 0.0), 1.0)

        laser_rate = self.share(LASERS) * LASER_FULL_POWER_REGEN_RATE_PS
        self.lasers = min(max(self.lasers + dt * laser_rate, 0.0), 1.0)

        if self.engines <= 0.0:
            self.is_boost_locked = True
        elif self.engines >= BOOST_REENABLE_ENGINE_LEVEL:
            self.is_boost_locked = False

    def thrust_factor(self) -> float:
        """
        :return: The multiplier the engine gauge applies to thrust
        """
        return engine_factor(
            self.engines, ENGINE_BONUS_MAX_THRUST_FACTOR, ENGINE_EMPTY_THRUST_FACTOR
        )

    def turn_rate_factor(self) -> float:
        """
        :return: The multiplier the engine gauge applies to the max turn rates
        """
        return engine_factor(
            self.engines,
            ENGINE_BONUS_MAX_TURN_RATE_FACTOR,
            ENGINE_EMPTY_TURN_RATE_FACTOR,
        )

    def laser_damage_factor(self) -> float:
        """
        :return: The multiplier the laser gauge applies to bolt damage
        """
        return bonus_factor(self.lasers, LASER_BONUS_MAX_DAMAGE_FACTOR)

    def can_fire_laser(self) -> bool:
        """
        :return: Whether the laser gauge holds enough energy for a bolt
        """
        return self.lasers >= self.laser_shot_energy_cost

    def consume_laser_shot(self):
        """
        Spend one bolt's worth of laser energy.
        """
        self.lasers = max(self.lasers - self.laser_shot_energy_cost, 0.0)

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
