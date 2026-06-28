"""
Unit tests for Formation (space_flight.ai.formation).

Formation is pure Python with no external dependencies, so all tests
instantiate it directly.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai.formation import Formation


def make_ship(ship_id=None) -> MagicMock:
    """
    Build a minimal ship stub with an id and a settable formation attribute.

    :param ship_id: the UUID to assign; a fresh UUID is generated if None
    :return: a MagicMock ship stub
    """
    ship = MagicMock()
    ship.id = ship_id if ship_id is not None else uuid.uuid4()
    ship.formation = None
    return ship


# ---------------------------------------------------------------------------
# __init__ — shape selection
# ---------------------------------------------------------------------------


def test_formation_default_shape_is_arrowhead():
    """
    Constructing a Formation without specifying a shape uses the arrowhead
    layout, which has 11 slots.
    """
    formation = Formation()

    assert len(formation.relative_positions) == len(Formation.ARROWHEAD_POSITIONS)


def test_formation_diamond_shape_has_eight_positions():
    """
    Requesting the 'diamond' shape yields exactly 8 relative positions.
    """
    formation = Formation(shape="diamond")

    assert len(formation.relative_positions) == 8


def test_formation_around_diamond_shape_has_nine_positions():
    """
    Requesting the 'around_diamond' shape yields exactly 9 relative positions.
    """
    formation = Formation(shape="around_diamond")

    assert len(formation.relative_positions) == 9


def test_formation_unknown_shape_raises():
    """
    Constructing a Formation with an unrecognised shape must raise
    NotImplementedError.
    """
    with pytest.raises(NotImplementedError):
        Formation(shape="v_formation")


# ---------------------------------------------------------------------------
# __init__ — scale
# ---------------------------------------------------------------------------


def test_formation_default_scale_leader_position_is_zero():
    """
    The leader slot (index 0) is always at the origin regardless of scale,
    since the arrowhead template has [0, 0, 0] at position 0.
    """
    formation = Formation()

    np.testing.assert_array_equal(formation.relative_positions[0], np.zeros(3))


def test_formation_positions_preserve_relative_proportions():
    """
    Regardless of accumulated scale, the second and third arrowhead positions
    must be symmetric about the Y axis (equal X magnitude, same Y value).
    The arrowhead template is [1, -2, 0] and [-1, -2, 0] for indices 1 and 2.
    """
    formation = Formation()
    pos_1 = formation.relative_positions[1]
    pos_2 = formation.relative_positions[2]

    # Symmetric about Y axis: x_1 == -x_2, y_1 == y_2
    assert pos_1[0] == pytest.approx(-pos_2[0])
    assert pos_1[1] == pytest.approx(pos_2[1])
    assert pos_1[2] == pytest.approx(pos_2[2])


# ---------------------------------------------------------------------------
# get_ship_index
# ---------------------------------------------------------------------------


def test_get_ship_index_returns_correct_index():
    """
    get_ship_index must return the correct zero-based position of a ship in
    the ship_ids list.
    """
    formation = Formation()
    ship_a = make_ship()
    ship_b = make_ship()
    formation.add_ship(ship_a)
    formation.add_ship(ship_b)

    assert formation.get_ship_index(ship_a.id) == 0
    assert formation.get_ship_index(ship_b.id) == 1


def test_get_ship_index_unknown_id_returns_none():
    """
    get_ship_index must return None for an id not present in the formation.
    """
    formation = Formation()

    result = formation.get_ship_index(uuid.uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# add_ship — wingman
# ---------------------------------------------------------------------------


def test_add_ship_appends_id_to_ship_ids():
    """
    Adding a new ship as a wingman appends its id to ship_ids.
    """
    formation = Formation()
    ship = make_ship()

    formation.add_ship(ship)

    assert ship.id in formation.ship_ids


def test_add_ship_sets_formation_on_ship():
    """
    After adding, ship.formation must point back to this Formation instance.
    """
    formation = Formation()
    ship = make_ship()

    formation.add_ship(ship)

    assert ship.formation is formation


def test_add_ship_duplicate_is_noop():
    """
    Adding a ship that is already in the formation (as wingman) must leave
    ship_ids unchanged.
    """
    formation = Formation()
    ship = make_ship()
    formation.add_ship(ship)
    count_before = len(formation.ship_ids)

    formation.add_ship(ship)

    assert len(formation.ship_ids) == count_before


# ---------------------------------------------------------------------------
# add_ship — leader
# ---------------------------------------------------------------------------


def test_add_ship_as_leader_inserts_at_index_zero():
    """
    Adding a ship as leader must insert its id at position 0 in ship_ids.
    """
    formation = Formation()
    wingman = make_ship()
    leader = make_ship()
    formation.add_ship(wingman)

    formation.add_ship(leader, leader=True)

    assert formation.ship_ids[0] == leader.id


def test_add_ship_as_leader_sets_formation_on_ship():
    """
    Adding a ship as leader must set ship.formation to this Formation instance.
    """
    formation = Formation()
    leader = make_ship()

    formation.add_ship(leader, leader=True)

    assert leader.formation is formation


def test_add_existing_ship_as_leader_removes_old_slot_first():
    """
    Promoting an already-present wingman to leader must not result in the ship
    appearing twice in ship_ids.
    """
    formation = Formation()
    ship_a = make_ship()
    ship_b = make_ship()
    formation.add_ship(ship_a)
    formation.add_ship(ship_b)

    formation.add_ship(ship_b, leader=True)

    assert formation.ship_ids.count(ship_b.id) == 1
    assert formation.ship_ids[0] == ship_b.id


# ---------------------------------------------------------------------------
# remove_ship
# ---------------------------------------------------------------------------


def test_remove_ship_deletes_id_from_ship_ids():
    """
    Removing a ship must delete its id from ship_ids.
    """
    formation = Formation()
    ship = make_ship()
    formation.add_ship(ship)

    formation.remove_ship(ship.id)

    assert ship.id not in formation.ship_ids


def test_remove_ship_shifts_remaining_ids_down():
    """
    After removing the leader (index 0) the former first wingman becomes the
    new index-0 entry.
    """
    formation = Formation()
    ship_a = make_ship()
    ship_b = make_ship()
    ship_c = make_ship()
    formation.add_ship(ship_a)
    formation.add_ship(ship_b)
    formation.add_ship(ship_c)

    formation.remove_ship(ship_a.id)

    assert formation.ship_ids[0] == ship_b.id
    assert formation.ship_ids[1] == ship_c.id
