"""
Unit tests for fighter energy management (space_flight.actors.energy).
"""

import pytest
from energy_fakes import (
    BOOST_DRAIN_RATE_PS,
    ENERGY_CONF,
    ENGINE_REGEN_RATE_PS,
    HARD_MANEUVER_DRAIN_RATE_PS,
    LASER_REGEN_RATE_PS,
    LASER_SHOT_COST,
    make_energy_system,
)

from space_flight.actors.energy import (
    BALANCED,
    BOOST_REENABLE_ENGINE_LEVEL,
    ENERGY_SHARES_SHIELDED,
    ENERGY_SHARES_UNSHIELDED,
    ENGINE_BONUS_MAX_THRUST_FACTOR,
    ENGINE_BONUS_MAX_TURN_RATE_FACTOR,
    ENGINE_RESTART_LEVEL,
    ENGINES,
    HARD_MANEUVER_COMMAND_THRESHOLD,
    LASER_BONUS_MAX_DAMAGE_FACTOR,
    LASERS,
    SHIELDS,
    EnergySystem,
    bonus_factor,
)

# ---------------------------
# Distribution
# ---------------------------


@pytest.mark.parametrize("shares", [ENERGY_SHARES_SHIELDED, ENERGY_SHARES_UNSHIELDED])
def test_redirecting_power_loses_some_of_it(shares):
    """
    Balanced power is fully used; redirecting it loses some.
    """
    assert sum(shares[BALANCED].values()) == pytest.approx(1.0)
    for mode, mode_shares in shares.items():
        if mode != BALANCED:
            assert sum(mode_shares.values()) < 1.0
            assert mode_shares[mode] == max(mode_shares.values())


def test_shielded_shares():
    """
    Shielded ships split power three ways, or 75/7/7 when redirected.
    """
    energy = make_energy_system(has_shields=True)
    assert energy.share(SHIELDS) == pytest.approx(1.0 / 3.0)
    energy.set_mode(LASERS)
    assert energy.share(LASERS) == pytest.approx(0.75)
    assert energy.share(ENGINES) == pytest.approx(0.07)
    assert energy.share(SHIELDS) == pytest.approx(0.07)


def test_unshielded_shares():
    """
    Unshielded ships split power two ways, or 80/10 when redirected, and have
    no shield mode.
    """
    energy = make_energy_system(has_shields=False)
    assert energy.share(ENGINES) == pytest.approx(0.5)
    energy.set_mode(ENGINES)
    assert energy.share(ENGINES) == pytest.approx(0.8)
    assert energy.share(LASERS) == pytest.approx(0.1)
    assert energy.share(SHIELDS) == 0.0

    energy.set_mode(SHIELDS)
    assert energy.mode == ENGINES


@pytest.mark.parametrize(
    "has_shields, expected",
    [
        (True, [SHIELDS, ENGINES, LASERS, BALANCED]),
        (False, [ENGINES, LASERS, BALANCED]),
    ],
)
def test_cycle_mode(has_shields, expected):
    """
    Cycling goes balanced, shields (if any), engines, lasers, then back.
    """
    energy = make_energy_system(has_shields=has_shields)
    visited = []
    for _ in expected:
        energy.cycle_mode()
        visited.append(energy.mode)
    assert visited == expected


def test_is_favoured():
    """
    Only the system power is redirected to is favoured.
    """
    energy = make_energy_system(has_shields=True)
    assert not energy.is_favoured(ENGINES)
    energy.set_mode(ENGINES)
    assert energy.is_favoured(ENGINES)
    assert not energy.is_favoured(LASERS)


# ---------------------------
# Regeneration and drain
# ---------------------------


@pytest.mark.parametrize("mode", [BALANCED, ENGINES, LASERS, SHIELDS])
def test_update_regenerates_by_share(mode):
    """
    Engine and laser gauges refill at their share of the plant's output.
    """
    energy = make_energy_system(has_shields=True)
    energy.set_mode(mode)
    energy.engines = 0.2
    energy.lasers = 0.2

    energy.update(dt=1.0, throttle=0.5, yaw_rate=0.0, pitch_rate=0.0)

    assert energy.engines == pytest.approx(
        0.2 + energy.share(ENGINES) * ENGINE_REGEN_RATE_PS
    )
    assert energy.lasers == pytest.approx(
        0.2 + energy.share(LASERS) * LASER_REGEN_RATE_PS
    )


def test_update_clamps_gauges_to_full():
    """
    Gauges never overfill.
    """
    energy = make_energy_system(has_shields=True)
    energy.update(dt=10.0, throttle=0.5, yaw_rate=0.0, pitch_rate=0.0)
    assert energy.engines == 1.0
    assert energy.lasers == 1.0


def test_boost_drains_engines():
    """
    Boosting drains the engine gauge on top of its regeneration.
    """
    energy = make_energy_system(has_shields=True)
    energy.engines = 0.5
    energy.update(dt=1.0, throttle=2.0, yaw_rate=0.0, pitch_rate=0.0)
    assert energy.engines == pytest.approx(
        0.5 + energy.share(ENGINES) * ENGINE_REGEN_RATE_PS - BOOST_DRAIN_RATE_PS
    )


@pytest.mark.parametrize(
    "yaw, pitch, drains",
    [
        (1.0, 0.0, True),
        (0.0, -1.0, True),
        (HARD_MANEUVER_COMMAND_THRESHOLD, 0.0, False),
        (0.5, 0.5, False),
    ],
)
def test_hard_maneuvers_drain_engines(yaw, pitch, drains):
    """
    Pitch or yaw commands above the threshold drain the engine gauge (roll is
    free: update does not even take it).
    """
    energy = make_energy_system(has_shields=True)
    energy.engines = 0.5
    energy.update(dt=1.0, throttle=0.5, yaw_rate=yaw, pitch_rate=pitch)
    regen = energy.share(ENGINES) * ENGINE_REGEN_RATE_PS
    expected = 0.5 + regen - (HARD_MANEUVER_DRAIN_RATE_PS if drains else 0.0)
    assert energy.engines == pytest.approx(expected)


def test_engines_do_not_go_below_empty():
    """
    The engine gauge bottoms out at zero.
    """
    energy = make_energy_system(has_shields=True)
    energy.engines = 0.01
    energy.update(dt=1.0, throttle=2.0, yaw_rate=1.0, pitch_rate=0.0)
    assert energy.engines == 0.0


# ---------------------------
# Boost lockout
# ---------------------------


def test_boost_locked_out_once_engines_run_dry_until_refilled():
    """
    An empty engine gauge locks boost out until it refills to
    BOOST_REENABLE_ENGINE_LEVEL.
    """
    energy = make_energy_system(has_shields=True)
    assert energy.limit_throttle(2.0) == 2.0

    energy.engines = 0.01
    energy.update(dt=1.0, throttle=2.0, yaw_rate=0.0, pitch_rate=0.0)
    assert energy.is_boost_locked
    assert energy.limit_throttle(2.0) == 1.0
    assert energy.limit_throttle(0.7) == 0.7

    # Refilling, but not enough yet
    energy.engines = 0.5 * BOOST_REENABLE_ENGINE_LEVEL
    energy.update(dt=0.0, throttle=1.0, yaw_rate=0.0, pitch_rate=0.0)
    assert energy.is_boost_locked

    energy.engines = BOOST_REENABLE_ENGINE_LEVEL
    energy.update(dt=0.0, throttle=1.0, yaw_rate=0.0, pitch_rate=0.0)
    assert not energy.is_boost_locked
    assert energy.limit_throttle(2.0) == 2.0


# ---------------------------
# Bonuses and penalties
# ---------------------------


@pytest.mark.parametrize(
    "level, expected_ramp",
    [(0.0, 0.0), (0.3, 0.0), (0.5, 0.0), (0.75, 0.5), (1.0, 1.0)],
)
def test_bonus_factor_ramps_linearly_over_half_full(level, expected_ramp):
    """
    No bonus up to half full, then a linear ramp to the max bonus.
    """
    assert bonus_factor(level, 0.2) == pytest.approx(1.0 + 0.2 * expected_ramp)


def test_energy_factors_at_full_and_empty():
    """
    Full gauges grant the max bonuses; an empty laser gauge costs no damage
    (the lasers just stop firing).
    """
    energy = make_energy_system(has_shields=True)
    assert energy.thrust_factor() == pytest.approx(1 + ENGINE_BONUS_MAX_THRUST_FACTOR)
    assert energy.turn_rate_factor() == pytest.approx(
        1 + ENGINE_BONUS_MAX_TURN_RATE_FACTOR
    )
    assert energy.laser_damage_factor() == pytest.approx(
        1 + LASER_BONUS_MAX_DAMAGE_FACTOR
    )

    energy.engines = 0.3
    energy.lasers = 0.0
    assert energy.thrust_factor() == pytest.approx(1.0)
    assert energy.turn_rate_factor() == pytest.approx(1.0)
    assert energy.laser_damage_factor() == pytest.approx(1.0)


# ---------------------------
# Dead engines
# ---------------------------


def test_engines_die_once_dry_until_refilled_to_restart_level():
    """
    An empty engine gauge kills the engines (no thrust, no turning) until it
    refills to ENGINE_RESTART_LEVEL.
    """
    energy = make_energy_system(has_shields=True)
    energy.engines = 0.01
    energy.update(dt=1.0, throttle=2.0, yaw_rate=0.0, pitch_rate=0.0)
    assert energy.is_engine_dead
    assert energy.thrust_factor() == 0.0
    assert energy.turn_rate_factor() == 0.0

    # Refilling, but not enough yet
    energy.engines = 0.5 * ENGINE_RESTART_LEVEL
    energy.update(dt=0.0, throttle=1.0, yaw_rate=0.0, pitch_rate=0.0)
    assert energy.is_engine_dead

    energy.engines = ENGINE_RESTART_LEVEL
    energy.update(dt=0.0, throttle=1.0, yaw_rate=0.0, pitch_rate=0.0)
    assert not energy.is_engine_dead
    assert energy.thrust_factor() == pytest.approx(1.0)
    # Boost comes back later
    assert energy.is_boost_locked


def test_dead_engines_spend_nothing():
    """
    Boosting or turning hard on dead engines does not keep the gauge empty:
    it refills at its share of the power.
    """
    energy = make_energy_system(has_shields=True)
    energy.engines = 0.0
    energy.is_engine_dead = True
    energy.update(dt=1.0, throttle=2.0, yaw_rate=1.0, pitch_rate=1.0)
    assert energy.engines == pytest.approx(energy.share(ENGINES) * ENGINE_REGEN_RATE_PS)


# ---------------------------
# Drain (ion hits)
# ---------------------------


@pytest.mark.parametrize("system", [ENGINES, LASERS])
def test_drain_takes_energy_out_of_a_gauge(system):
    """
    Draining takes an amount of energy, so a fraction amount / capacity of
    the gauge.
    """
    energy = make_energy_system(
        has_shields=True, engine_capacity=200.0, laser_capacity=400.0
    )
    energy.drain(system, 40.0)
    expected = 1.0 - 40.0 / (200.0 if system == ENGINES else 400.0)
    assert getattr(energy, system) == pytest.approx(expected)


def test_drain_stops_at_empty_and_kills_the_engines():
    """
    A gauge cannot be drained below empty; emptying the engines kills them at
    once.
    """
    energy = make_energy_system(has_shields=True)
    energy.drain(ENGINES, 1000.0)
    energy.drain(LASERS, 1000.0)
    assert energy.engines == 0.0
    assert energy.lasers == 0.0
    assert energy.is_engine_dead
    assert energy.is_boost_locked
    assert not energy.can_fire_laser()


def test_rates_and_costs_scale_with_capacity():
    """
    The configured rates and costs are energy amounts: a bigger gauge refills
    and empties more slowly, in fraction of the gauge.
    """
    small = make_energy_system(has_shields=True)
    big = make_energy_system(
        has_shields=True,
        engine_capacity=2.0 * ENERGY_CONF["engine_capacity"],
        laser_capacity=2.0 * ENERGY_CONF["laser_capacity"],
    )
    for energy in (small, big):
        energy.engines = 0.5
        energy.lasers = 0.5
        energy.update(dt=1.0, throttle=0.5, yaw_rate=0.0, pitch_rate=0.0)
        energy.consume_laser_shot()
    assert big.engines - 0.5 == pytest.approx(0.5 * (small.engines - 0.5))
    assert big.laser_shot_cost == pytest.approx(0.5 * small.laser_shot_cost)


@pytest.mark.parametrize("key", ["engine_capacity", "laser_capacity"])
def test_capacities_must_be_positive(key):
    """
    A gauge must hold some energy.
    """
    with pytest.raises(ValueError):
        EnergySystem(has_shields=True, **{**ENERGY_CONF, key: 0.0})


# ---------------------------
# Lasers
# ---------------------------


def test_laser_shot_costs_energy_and_needs_enough():
    """
    Each bolt costs the ship's laser_shot_cost; below that, no firing.
    """
    energy = make_energy_system(has_shields=True)
    energy.consume_laser_shot()
    assert energy.lasers == pytest.approx(1.0 - LASER_SHOT_COST)

    energy.lasers = LASER_SHOT_COST
    assert energy.can_fire_laser()
    energy.lasers = 0.99 * LASER_SHOT_COST
    assert not energy.can_fire_laser()


# ---------------------------
# Shields
# ---------------------------


@pytest.mark.parametrize(
    "mode, expected_multiplier",
    [(BALANCED, 1.0), (SHIELDS, 0.75 * 3.0), (ENGINES, 0.07 * 3.0)],
)
def test_shield_regen_rate_scales_from_balanced(mode, expected_multiplier):
    """
    Balanced power keeps the ship's configured shield regeneration rate;
    redirecting scales it by the share.
    """
    energy = make_energy_system(has_shields=True)
    energy.set_mode(mode)
    assert energy.shield_regen_rate(5.0) == pytest.approx(5.0 * expected_multiplier)


def test_unshielded_ship_has_no_shield_regen():
    """
    An unshielded ship regenerates no shield.
    """
    energy = make_energy_system(has_shields=False)
    assert energy.shield_regen_rate(5.0) == 0.0
