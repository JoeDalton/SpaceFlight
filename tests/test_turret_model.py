"""
Unit tests for TurretModel (space_flight.actors.turret_model).

Tests use a fully-mocked game so no 3-D assets or ShowBase instance are
required.  The MagicMock returned by game.root_node.attachNewNode stands
in for the real NodePath, allowing scene-graph calls to succeed as no-ops.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.turret_model import TurretModel


@pytest.fixture
def mock_game():
    """
    Minimal game mock whose root_node.attachNewNode returns a MagicMock
    that supports arbitrary attribute access (setScale, find, reparent_to…).
    """
    return MagicMock()


def make_turret_model(mock_game, turret_type: str) -> TurretModel:
    """
    Construct a TurretModel with a mocked game and parent node.

    :param mock_game: the mocked game object
    :param turret_type: the turret-type string to pass to TurretModel
    :return: the constructed TurretModel instance
    """
    parent_node = MagicMock()
    return TurretModel(game=mock_game, parent_node=parent_node, turret_type=turret_type)


# ---------------------------
# Initialisation
# ---------------------------


def test_turret_model_test_type_stores_type(mock_game):
    """
    TurretModel stores the turret_type string on construction.
    """
    turret_model = make_turret_model(mock_game, "test")

    assert turret_model.turret_type == "test"


def test_turret_model_test_type_offset_is_zero(mock_game):
    """
    The 'test' turret type has a zero positional offset.
    """
    turret_model = make_turret_model(mock_game, "test")

    np.testing.assert_array_equal(turret_model.offset, np.array([0.0, 0.0, 0.0]))


def test_turret_model_test_type_orientation_is_identity(mock_game):
    """
    The 'test' turret type has an identity quaternion orientation.
    """
    turret_model = make_turret_model(mock_game, "test")

    expected = np.quaternion(1.0, 0.0, 0.0, 0.0)
    assert turret_model.orientation == expected


def test_turret_model_test_type_exposes_yaw_and_pitch_callables(mock_game):
    """
    After construction the model exposes callable set_yaw and set_pitch
    attributes that delegate to the correct sub-nodes.
    """
    turret_model = make_turret_model(mock_game, "test")

    assert callable(turret_model.set_yaw)
    assert callable(turret_model.set_pitch)


def test_turret_model_test_type_cannon_node_is_pitch_node(mock_game):
    """
    cannon_node is the same object as pitch_node for the 'test' turret.
    """
    turret_model = make_turret_model(mock_game, "test")

    assert turret_model.cannon_node is turret_model.pitch_node


# ---------------------------
# Error cases
# ---------------------------


def test_turret_model_unknown_type_raises(mock_game):
    """
    TurretModel raises NotImplementedError for an unrecognised turret type.
    """
    with pytest.raises(NotImplementedError):
        make_turret_model(mock_game, turret_type="unknown-turret")


# ---------------------------
# anchor_model
# ---------------------------


def test_turret_model_anchor_model_reparents_to_given_node(mock_game):
    """
    anchor_model calls reparent_to on the internal model with the given parent.
    """
    turret_model = make_turret_model(mock_game, "test")
    new_parent = MagicMock()

    turret_model.anchor_model(new_parent)

    turret_model.model.reparent_to.assert_called_with(new_parent)


def test_turret_model_anchor_model_sets_position_from_offset(mock_game):
    """
    anchor_model calls setPos with the unpacked offset components.
    """
    turret_model = make_turret_model(mock_game, "test")
    new_parent = MagicMock()
    turret_model.offset = np.array([4.0, 5.0, 6.0])

    turret_model.anchor_model(new_parent)

    turret_model.model.setPos.assert_called_with(4.0, 5.0, 6.0)


def test_turret_model_anchor_model_sets_orientation(mock_game):
    """
    anchor_model calls setQuat on the model node; because __init__ already
    calls it once, two calls are expected after a second explicit call.
    """
    turret_model = make_turret_model(mock_game, "test")
    calls_after_init = turret_model.model.setQuat.call_count
    new_parent = MagicMock()

    turret_model.anchor_model(new_parent)

    assert turret_model.model.setQuat.call_count == calls_after_init + 1


# ---------------------------
# clean
# ---------------------------


def test_turret_model_clean_sets_model_to_none(mock_game):
    """
    clean() sets the model attribute to None.
    """
    turret_model = make_turret_model(mock_game, "test")

    turret_model.clean()

    assert turret_model.model is None


def test_turret_model_clean_sets_game_to_none(mock_game):
    """
    clean() clears the back-reference to the game object.
    """
    turret_model = make_turret_model(mock_game, "test")

    turret_model.clean()

    assert turret_model.game is None


def test_turret_model_clean_calls_remove_node_on_model(mock_game):
    """
    clean() calls removeNode on the internal model NodePath.
    """
    turret_model = make_turret_model(mock_game, "test")
    internal_model = turret_model.model

    turret_model.clean()

    internal_model.removeNode.assert_called_once()
