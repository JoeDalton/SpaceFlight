"""
Unit tests for the ion crackle (space_flight.fx.spark_fx.IonCrackle).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.fx import spark_fx
from space_flight.fx.spark_fx import ION_CRACKLE_MAX_INTERVAL_S, IonCrackle


def make_game(now: float = 0.0) -> SimpleNamespace:
    """A game with a settable clock and a mock spark pool."""
    return SimpleNamespace(
        game_time=SimpleNamespace(get_current_time=lambda: now),
        spark_fx_pool=MagicMock(),
    )


def test_crackle_bursts_off_the_surface_then_waits():
    """
    A burst starts on the owner's surface (radius away from its position,
    along the sparks' normal) and rides its velocity; the next one waits at
    most ION_CRACKLE_MAX_INTERVAL_S.
    """
    crackle = IonCrackle()
    game = make_game(now=5.0)
    position = np.array([10.0, 20.0, 30.0])

    crackle.update(game, position, radius_m=4.0, velocity=np.array([0.0, 50.0, 0.0]))

    kwargs = game.spark_fx_pool.spawn.call_args.kwargs
    assert kwargs["preset"] is spark_fx.ION
    offset = np.array(kwargs["position"]) - position
    assert np.linalg.norm(offset) == pytest.approx(4.0)
    np.testing.assert_allclose(offset / 4.0, np.array(kwargs["normal"]), atol=1e-6)
    np.testing.assert_allclose(np.array(kwargs["base_velocity"]), [0.0, 50.0, 0.0])
    assert 5.0 <= crackle.next_crackle_s <= 5.0 + ION_CRACKLE_MAX_INTERVAL_S


def test_crackle_waits_until_the_next_burst_is_due():
    """
    No burst before the next one is due.
    """
    crackle = IonCrackle()
    crackle.next_crackle_s = 1.0
    game = make_game(now=0.5)

    crackle.update(game, np.zeros(3), radius_m=1.0, velocity=np.zeros(3))

    game.spark_fx_pool.spawn.assert_not_called()


def test_flare_spark_preset_reaches_at_most_the_configured_radii():
    flare_radius_m = 8.0
    color = (1.0, 0.5, 0.2, 0.5)

    preset = spark_fx.flare_spark_preset(color, flare_radius_m)

    max_reach_m = (
        preset.speed * spark_fx.SPARK_SPEED_SCALE * preset.lifetime
    )  # the fastest, longest-lived spark
    assert max_reach_m == pytest.approx(
        spark_fx.FLARE_SPARK_REACH_FACTOR * flare_radius_m
    )
    assert preset.gravity == 0.0
    # The flare's colour (the smallest sparks dimmer)
    np.testing.assert_allclose(preset.color_inner[:3], color[:3])
    np.testing.assert_allclose(
        preset.color_outer[:3], np.array(color[:3]) * spark_fx.FLARE_SPARK_OUTER_DIM
    )


def test_isotropic_spawn_covers_the_whole_sphere():
    pool = object.__new__(spark_fx.SparkPool)
    directions = []

    def fake_emit(pos, direction, base_velocity, preset, *args):
        directions.append(direction)
        return True

    pool._emit = fake_emit
    np.random.seed(0)

    pool.spawn_isotropic(
        position=(0.0, 0.0, 0.0), base_velocity=None, preset=spark_fx.METAL, count=4000
    )

    d = np.array(directions)
    assert len(d) == 4000
    np.testing.assert_allclose(np.linalg.norm(d, axis=1), 1.0)
    # Isotropic: no mean direction, and both poles reached
    assert np.all(np.abs(d.mean(axis=0)) < 0.05)
    assert d[:, 2].max() > 0.99 and d[:, 2].min() < -0.99


def test_isotropic_spawn_stops_when_the_pool_is_full():
    pool = object.__new__(spark_fx.SparkPool)
    calls = []
    pool._emit = lambda *a, **k: calls.append(1) or len(calls) < 3

    pool.spawn_isotropic(
        position=(0.0, 0.0, 0.0), base_velocity=None, preset=spark_fx.METAL, count=50
    )

    assert len(calls) == 3
