"""
Unit tests for the pure helpers of the cockpit low-health FX
(space_flight.fx.cockpit_fx): the health-tier mapping and the incoming-shot
to screen-direction projection. Both are game-free, so no Panda3D app is needed.
"""

import random
from types import SimpleNamespace

import numpy as np
import pytest

from space_flight.fx import cockpit_fx as cfx
from space_flight.fx.cockpit_fx import (
    CRITICAL,
    DAMAGED,
    INTACT,
    CockpitFX,
    health_tier,
    load_cockpit_spark_emitters,
    screen_direction_from_incoming,
)

# ---------------------------------------------------------------------------
# health_tier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fraction, expected",
    [
        (1.0, INTACT),
        (0.75, INTACT),  # above 2/3
        (2.0 / 3.0, DAMAGED),  # exactly the smoke threshold -> damaged
        (0.5, DAMAGED),
        (1.0 / 3.0, CRITICAL),  # exactly the fire threshold -> critical
        (0.2, CRITICAL),
        (0.0, CRITICAL),
    ],
)
def test_health_tier_boundaries(fraction, expected):
    assert health_tier(fraction) == expected


# ---------------------------------------------------------------------------
# screen_direction_from_incoming
# ---------------------------------------------------------------------------

# A canonical pilot basis: right = +x, up = +z (forward would be +y).
_RIGHT = np.array([1.0, 0.0, 0.0])
_UP = np.array([0.0, 0.0, 1.0])


def test_shot_from_the_left():
    # A shot travelling toward +x came from the left -> screen dir points left.
    d = screen_direction_from_incoming([1.0, 0.0, 0.0], _RIGHT, _UP)
    np.testing.assert_allclose(d, [-1.0, 0.0], atol=1e-6)


def test_shot_from_above():
    # A shot travelling downward (-z) came from above -> screen dir points up.
    d = screen_direction_from_incoming([0.0, 0.0, -1.0], _RIGHT, _UP)
    np.testing.assert_allclose(d, [0.0, 1.0], atol=1e-6)


def test_diagonal_is_unit_length():
    d = screen_direction_from_incoming([1.0, 0.0, -1.0], _RIGHT, _UP)
    # came from lower-left of travel -> upper-left on screen, unit length.
    np.testing.assert_allclose(d, [-np.sqrt(0.5), np.sqrt(0.5)], atol=1e-6)
    assert np.linalg.norm(d) == pytest.approx(1.0)


def test_head_on_shot_has_no_side_bias():
    # Straight down the view axis (+y): projects to zero on right/up.
    d = screen_direction_from_incoming([0.0, 1.0, 0.0], _RIGHT, _UP)
    np.testing.assert_allclose(d, [0.0, 0.0], atol=1e-6)


def test_zero_direction_is_safe():
    d = screen_direction_from_incoming([0.0, 0.0, 0.0], _RIGHT, _UP)
    np.testing.assert_allclose(d, [0.0, 0.0], atol=1e-6)


# ---------------------------------------------------------------------------
# Damage stutter scheduler
# ---------------------------------------------------------------------------
# CockpitFX.__init__ builds render/GPU resources, so the stutter logic is
# exercised on a bare instance (object.__new__) with the state __init__ would set
# and a fake player pawn -- no Panda3D app needed.


def _make_stutter_fx(health_frac: float) -> CockpitFX:
    fx = object.__new__(CockpitFX)
    fx._stutter_intensity = 0.0
    fx._stutter_elapsed = 0.0
    fx._stutter_duration = 0.0
    fx._stutter_peak = 0.0
    fx._next_stutter_at = 0.0
    fx.game = SimpleNamespace(game_time=SimpleNamespace(get_current_time=lambda: 1.0))
    fx.player = SimpleNamespace(
        pawn=SimpleNamespace(health=health_frac * 100.0, max_health=100.0)
    )
    return fx


def test_stutter_idle_and_armed_while_intact():
    fx = _make_stutter_fx(1.0)  # full health
    fx._advance_stutter(now=5.0, dt=0.016, tier=INTACT)

    assert fx.sputter_intensity() == 0.0
    offset, roll = fx.rattle_offset()
    np.testing.assert_allclose(offset, [0.0, 0.0, 0.0])
    assert roll == 0.0
    # The next-event clock is held ahead so entering the damaged tier does not
    # fire an instant jolt.
    assert fx._next_stutter_at == pytest.approx(5.0 + cfx._STUTTER_GAP_S[DAMAGED][0])


def test_stutter_fires_then_decays_to_zero():
    fx = _make_stutter_fx(0.2)  # critical
    random.seed(0)
    np.random.seed(0)

    fx._advance_stutter(now=1.0, dt=0.016, tier=CRITICAL)

    peak = fx.sputter_intensity()
    assert peak > 0.0
    assert fx._stutter_duration > 0.0
    assert fx._next_stutter_at > 1.0  # a fresh gap was scheduled

    # Advance past the event duration: the jolt eases back to nothing.
    for _ in range(200):
        fx._advance_stutter(now=1.0, dt=0.016, tier=CRITICAL)
        if fx.sputter_intensity() == 0.0:
            break
    assert fx.sputter_intensity() == 0.0


# ---------------------------------------------------------------------------
# Cockpit spark emitter loading
# ---------------------------------------------------------------------------


def test_no_emitters_when_config_absent():
    assert load_cockpit_spark_emitters({}) == []
    assert load_cockpit_spark_emitters({"cockpit_spark_emitters": None}) == []


@pytest.mark.parametrize(
    "rel_path",
    [
        "models/ships/tie_common/cockpit/spark_emitters.yaml",
        "models/ships/x-wing/cockpit/spark_emitters.yaml",
        "models/ships/a-wing/cockpit/spark_emitters.yaml",
        "models/ships/y-wing/cockpit/spark_emitters.yaml",
    ],
)
def test_shipped_emitter_files_parse(rel_path):
    emitters = load_cockpit_spark_emitters({"cockpit_spark_emitters": rel_path})
    assert len(emitters) > 0
    for position, normal in emitters:
        assert position.shape == (3,)
        assert normal.shape == (3,)
        assert np.linalg.norm(normal) > 0.0  # a usable emission direction


def test_camera_rattle_and_engine_gated_by_same_envelope():
    fx = _make_stutter_fx(0.2)  # critical
    random.seed(1)
    np.random.seed(1)

    # During an event: both the engine cut and the camera vibration are active.
    fx._advance_stutter(now=1.0, dt=0.016, tier=CRITICAL)
    assert fx.sputter_intensity() > 0.0
    offset, roll = fx.rattle_offset()
    assert np.linalg.norm(offset) > 0.0

    # Run the event out: the shared envelope hits zero, and BOTH the engine cut
    # and the camera rattle switch off together.
    for _ in range(200):
        fx._advance_stutter(now=1.0, dt=0.016, tier=CRITICAL)
        if fx.sputter_intensity() == 0.0:
            break
    assert fx.sputter_intensity() == 0.0
    offset, roll = fx.rattle_offset()
    np.testing.assert_allclose(offset, [0.0, 0.0, 0.0])
    assert roll == 0.0
