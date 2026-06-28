"""
Unit tests for ShipModel (space_flight.actors.ship_model).

All tests use a fully-mocked game object so that no 3-D assets or ShowBase
instance are required.  The asset_manager's
``instantiate_3d_model_to_node`` is replaced by a MagicMock no-op, which
means the scene-graph node exists but carries no geometry — enough to
exercise the positioning and cleanup logic.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.ship_model import ShipModel


@pytest.fixture
def mock_game():
    """
    Minimal game mock: root_node returns a fresh MagicMock each call so
    that NodePath-like attribute access does not collide between tests.
    """
    game = MagicMock()
    return game


def make_ship_model(mock_game, ship_type: str, is_cockpit: bool) -> ShipModel:
    """
    Construct a ShipModel with a mocked game and a mocked parent node.

    :param mock_game: the mocked game object
    :param ship_type: the ship-type string to pass to ShipModel
    :param is_cockpit: whether to request the cockpit variant
    :return: the constructed ShipModel instance
    """
    parent_node = MagicMock()
    return ShipModel(
        game=mock_game,
        parent_node=parent_node,
        ship_type=ship_type,
        is_cockpit=is_cockpit,
    )


# ---------------------------
# Offset values per ship type
# ---------------------------


@pytest.mark.parametrize(
    "ship_type, is_cockpit, expected_offset",
    [
        ("a-wing", True, np.array([0.0, 0.8, -0.2])),
        ("a-wing", False, np.array([0.0, 0.0, 0.0])),
        ("tie-interceptor", True, np.array([0.0, 0.9, -0.2])),
        ("tie-interceptor", False, np.array([0.0, 0.0, 0.0])),
        ("tie-bomber", True, np.array([0.0, 0.9, -0.2])),
        ("tie-bomber", False, np.array([1.5, 0.0, 0.0])),
        ("y-wing", True, np.array([0.0, 0.7, -0.5])),
        ("y-wing", False, np.array([0.0, 0.0, 0.0])),
        ("x-wing", True, np.array([0.0, 0.9, -0.2])),
        ("x-wing", False, np.array([0.0, 0.0, 0.0])),
        ("tie-fighter", True, np.array([0.0, 0.9, -0.2])),
        ("tie-fighter", False, np.array([0.0, 0.0, 0.0])),
        ("gr-75", False, np.array([0.0, 0.0, 0.0])),
        ("cr-90", False, np.array([0.0, 0.0, 0.0])),
    ],
)
def test_ship_model_offset_per_type(mock_game, ship_type, is_cockpit, expected_offset):
    """
    ShipModel stores the correct positional offset for each ship_type /
    is_cockpit combination.
    """
    model = make_ship_model(mock_game, ship_type, is_cockpit)

    np.testing.assert_array_almost_equal(model.offset, expected_offset)


# ---------------------------
# Error cases
# ---------------------------


def test_ship_model_unknown_type_raises(mock_game):
    """
    ShipModel raises NotImplementedError when given an unrecognised ship type.
    """
    with pytest.raises(NotImplementedError):
        make_ship_model(mock_game, ship_type="unknown-ship", is_cockpit=False)


@pytest.mark.parametrize("capital_ship_type", ["gr-75", "cr-90"])
def test_ship_model_capital_ship_cockpit_raises(mock_game, capital_ship_type):
    """
    Capital-ship types do not support a cockpit view and raise
    NotImplementedError when is_cockpit=True.
    """
    with pytest.raises(NotImplementedError):
        make_ship_model(mock_game, ship_type=capital_ship_type, is_cockpit=True)


# ---------------------------
# anchor_model
# ---------------------------


def test_anchor_model_reparents_model_to_given_node(mock_game):
    """
    anchor_model calls reparent_to on the internal model node with the
    supplied parent node.
    """
    ship_model = make_ship_model(mock_game, "a-wing", is_cockpit=False)
    new_parent = MagicMock()

    ship_model.anchor_model(new_parent)

    ship_model.model.reparent_to.assert_called_with(new_parent)


def test_anchor_model_sets_position_from_offset(mock_game):
    """
    anchor_model calls setPos with the unpacked offset components.
    """
    ship_model = make_ship_model(mock_game, "a-wing", is_cockpit=True)
    new_parent = MagicMock()
    # Override offset for a predictable assertion
    ship_model.offset = np.array([1.0, 2.0, 3.0])

    ship_model.anchor_model(new_parent)

    ship_model.model.setPos.assert_called_with(1.0, 2.0, 3.0)


def test_anchor_model_sets_orientation(mock_game):
    """
    anchor_model calls setQuat on the model node; because __init__ already
    calls it once, two calls are expected after a second explicit call.
    """
    ship_model = make_ship_model(mock_game, "a-wing", is_cockpit=False)
    calls_after_init = ship_model.model.setQuat.call_count
    new_parent = MagicMock()

    ship_model.anchor_model(new_parent)

    assert ship_model.model.setQuat.call_count == calls_after_init + 1


# ---------------------------
# clean
# ---------------------------


def test_ship_model_clean_sets_model_to_none(mock_game):
    """
    clean() removes the scene-graph node and sets the model reference to None.
    """
    ship_model = make_ship_model(mock_game, "a-wing", is_cockpit=False)

    ship_model.clean()

    assert ship_model.model is None


def test_ship_model_clean_sets_game_to_none(mock_game):
    """
    clean() clears the back-reference to the game object.
    """
    ship_model = make_ship_model(mock_game, "a-wing", is_cockpit=False)

    ship_model.clean()

    assert ship_model.game is None


def test_ship_model_clean_calls_remove_node_on_model(mock_game):
    """
    clean() calls removeNode on the internal model NodePath.
    """
    ship_model = make_ship_model(mock_game, "a-wing", is_cockpit=False)
    internal_model = ship_model.model

    ship_model.clean()

    internal_model.removeNode.assert_called_once()
