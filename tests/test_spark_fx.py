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
