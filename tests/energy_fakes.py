"""
A fighter's energy configuration for tests, and EnergySystems built from it.

Shared by the energy, fighter, laser cannon and HUD tests.
"""

from space_flight.actors.energy import EnergySystem

# A ship configuration's energy block. Both gauges hold 100 energy units, so
# every amount is also a percentage of its gauge: a bolt costs LASER_SHOT_COST
# of the laser gauge, the engines refill at ENGINE_REGEN_RATE_PS of theirs per
# second at full power, etc.
ENERGY_CAPACITY = 100.0
ENGINE_REGEN_RATE_PS = 0.15
LASER_REGEN_RATE_PS = 0.15
BOOST_DRAIN_RATE_PS = 0.12
HARD_MANEUVER_DRAIN_RATE_PS = 0.08
LASER_SHOT_COST = 0.02
ENERGY_CONF = {
    "engine_capacity": ENERGY_CAPACITY,
    "laser_capacity": ENERGY_CAPACITY,
    "engine_regen_rate": ENGINE_REGEN_RATE_PS * ENERGY_CAPACITY,
    "laser_regen_rate": LASER_REGEN_RATE_PS * ENERGY_CAPACITY,
    "boost_drain_rate": BOOST_DRAIN_RATE_PS * ENERGY_CAPACITY,
    "hard_maneuver_drain_rate": HARD_MANEUVER_DRAIN_RATE_PS * ENERGY_CAPACITY,
    "laser_shot_cost": LASER_SHOT_COST * ENERGY_CAPACITY,
}


def make_energy_system(has_shields: bool = True, **overrides: float) -> EnergySystem:
    """
    :param has_shields: Whether the ship has shields to power
    :param overrides: Energy block entries replacing ENERGY_CONF's
    :return: An energy system with full gauges and balanced power
    """
    return EnergySystem(has_shields=has_shields, **{**ENERGY_CONF, **overrides})
