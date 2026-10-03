"""
Unit tests for MissileNavigator (space_flight.ai.missile.missile_navigator).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Intent
from space_flight.ai.missile.missile_navigator import MissileNavigator


def make_navigator(*actors):
    """
    A navigator for a missile at the origin flying +Y at 300 m/s, among the
    given interacting actors.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    game.interactions.actors = list(actors)

    def get_actor_index_from_id(actor_id):
        for index, actor in enumerate(game.interactions.actors):
            if actor is not None and actor.id == actor_id:
                return index
        raise ValueError(actor_id)

    game.interactions.get_actor_index_from_id.side_effect = get_actor_index_from_id
    pawn = SimpleNamespace(
        position=np.zeros(3),
        speed=np.array([0.0, 300.0, 0.0]),
        max_speed_mps=300.0,
    )
    return MissileNavigator(game=game, pawn=pawn)


def make_target(position, speed=None, is_dead=False):
    target = SimpleNamespace(
        id=uuid.uuid4(), position=np.array(position, dtype=float), is_dead=is_dead
    )
    if speed is not None:
        target.speed = np.array(speed, dtype=float)
    return target


def navigate(navigator, target):
    return navigator.navigate(
        intent=Intent.ENGAGE, target_dict={"target_id": target.id}
    )


def test_leads_a_crossing_target():
    """
    A target dead ahead crossing to the right is led: the missile points right
    of it, at its own speed.
    """
    target = make_target([0.0, 1000.0, 0.0], speed=[100.0, 0.0, 0.0])
    navigator = make_navigator(target)

    direction, speed_mps = navigate(navigator, target)

    assert np.linalg.norm(direction) == pytest.approx(1.0)
    assert direction[0] > 0.0
    assert speed_mps == pytest.approx(300.0)


def test_points_at_a_static_target_without_speed():
    """
    A target without a speed (e.g. a subsystem) is treated as static.
    """
    target = make_target([0.0, 1000.0, 0.0])
    navigator = make_navigator(target)

    direction, _ = navigate(navigator, target)

    np.testing.assert_allclose(direction, [0.0, 1.0, 0.0], atol=1e-9)


@pytest.mark.parametrize("case", ["removed", "dead"])
def test_lost_target_gives_no_direction(case):
    """
    A target no longer interacting (removed) or dead gives a zero direction.
    """
    target = make_target([0.0, 1000.0, 0.0], is_dead=case == "dead")
    navigator = make_navigator() if case == "removed" else make_navigator(target)

    direction, speed_mps = navigate(navigator, target)

    np.testing.assert_array_equal(direction, np.zeros(3))
    assert speed_mps == pytest.approx(300.0)
