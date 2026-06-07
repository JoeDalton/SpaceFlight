import uuid

import numpy as np
import pytest

from space_flight.ai import INTERACT_MAX_DISTANCE_M
from space_flight.ai.interactions import MAX_ACTORS, Interactions


class MockActor:
    """
    Minimal actor stub that satisfies the attribute contract expected by
    :class:`~space_flight.ai.interactions.Interactions`.
    """

    def __init__(self, team, position, speed=None, forward=None):
        """
        :param team: Team number (0 = neutral, 1 = player, 2+ = foes)
        :param position: World-space position as a 3-element array-like
        :param speed: World-space velocity as a 3-element array-like,
                    defaults to [0, 0, 0]
        :param forward: Unit forward direction as a 3-element array-like,
                    defaults to [0, 1, 0]
        """
        self.id = uuid.uuid4()
        self.name = f"mock_{str(self.id)[:8]}"
        self.team = team
        self.position = np.array(position, dtype=float)
        self.speed = np.array(speed or [0.0, 0.0, 0.0], dtype=float)
        self.forward = np.array(forward or [0.0, 1.0, 0.0], dtype=float)


@pytest.fixture
def interactions():
    """
    Returns a fresh :class:`~space_flight.ai.interactions.Interactions` instance
    with default capacity for use in each test.
    """
    return Interactions()


# ---------------------------------------------------------------------------
# Actor management
# ---------------------------------------------------------------------------


def test_add_actor_registers_slot(interactions):
    """
    Adding an actor must register it in the id dict, store it in the actors
    list at the assigned slot, and mark that slot as alive.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    interactions.add_actor(a)

    assert a.id in interactions.actors_id_dict
    slot = interactions.actors_id_dict[a.id]
    assert interactions.actors[slot] is a
    assert interactions.alive[slot]


def test_add_duplicate_actor_raises(interactions):
    """
    Adding the same actor instance twice must raise a :exc:`ValueError`.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    interactions.add_actor(a)
    with pytest.raises(ValueError):
        interactions.add_actor(a)


def test_max_actors_exceeded_raises():
    """
    Attempting to add a third actor to an instance created with ``max_actors=2``
    must raise a :exc:`RuntimeError`.
    """
    ix = Interactions(max_actors=2)
    ix.add_actor(MockActor(team=1, position=[0, 0, 0]))
    ix.add_actor(MockActor(team=1, position=[1, 0, 0]))
    with pytest.raises(RuntimeError):
        ix.add_actor(MockActor(team=1, position=[2, 0, 0]))


def test_remove_actor_frees_slot(interactions):
    """
    Removing an actor must clear its id dict entry, null the actors list slot,
    mark it as not alive, and push its index back onto the free-slot stack.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    interactions.add_actor(a)
    slot = interactions.actors_id_dict[a.id]

    interactions.remove_actor(a)

    assert a.id not in interactions.actors_id_dict
    assert interactions.actors[slot] is None
    assert not interactions.alive[slot]
    assert slot in interactions._free_slots


def test_remove_actor_zeroes_interact_row_and_col(interactions):
    """
    After removal, the entire ``interact`` row and column for the freed slot
    must be ``False`` so that no other actor can appear to interact with it.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    b_slot = interactions.actors_id_dict[b.id]
    interactions.remove_actor(b)

    assert not interactions.interact[b_slot, :].any()
    assert not interactions.interact[:, b_slot].any()


def test_remove_actor_zeroes_distances(interactions):
    """
    After removal, the entire ``distances`` row and column for the freed slot
    must be zero to prevent stale distance values from leaking into AI queries.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    b_slot = interactions.actors_id_dict[b.id]
    interactions.remove_actor(b)

    assert interactions.distances[b_slot, :].sum() == 0.0
    assert interactions.distances[:, b_slot].sum() == 0.0


def test_remove_nonexistent_actor_raises(interactions):
    """
    Removing an actor that was never added must raise a :exc:`KeyError`.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    with pytest.raises(KeyError):
        interactions.remove_actor(a)


def test_slot_reused_after_remove(interactions):
    """
    The slot freed by removing actor A must be assigned to the next actor added.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    interactions.add_actor(a)
    a_slot = interactions.actors_id_dict[a.id]

    interactions.remove_actor(a)

    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(b)

    assert interactions.actors_id_dict[b.id] == a_slot


def test_slot_stable_across_other_removals(interactions):
    """
    Removing actor B must not shift the slot indices of A or C.

    This is the key correctness guarantee of the pre-allocated design:
    stable slot indices eliminate the stale ``target_idx`` bug that existed
    in the previous compact-list implementation.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    c = MockActor(team=2, position=[200, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.add_actor(c)

    a_slot_before = interactions.actors_id_dict[a.id]
    c_slot_before = interactions.actors_id_dict[c.id]

    interactions.remove_actor(b)

    assert interactions.actors_id_dict[a.id] == a_slot_before
    assert interactions.actors_id_dict[c.id] == c_slot_before


# ---------------------------------------------------------------------------
# Properties: n_actors and live_actors
# ---------------------------------------------------------------------------


def test_n_actors_initially_zero(interactions):
    """
    A newly created instance must report zero live actors.
    """
    assert interactions.n_actors == 0


def test_n_actors_after_add(interactions):
    """
    ``n_actors`` must equal the number of actors that have been added.
    """
    interactions.add_actor(MockActor(team=1, position=[0, 0, 0]))
    interactions.add_actor(MockActor(team=2, position=[100, 0, 0]))
    assert interactions.n_actors == 2


def test_n_actors_after_remove(interactions):
    """
    ``n_actors`` must decrement by one after a removal.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)

    interactions.remove_actor(a)

    assert interactions.n_actors == 1


def test_live_actors_contains_no_nones(interactions):
    """
    ``live_actors`` must never contain ``None`` entries regardless of how
    many slots are occupied.
    """
    interactions.add_actor(MockActor(team=1, position=[0, 0, 0]))
    interactions.add_actor(MockActor(team=2, position=[100, 0, 0]))
    assert None not in interactions.live_actors


def test_live_actors_returns_correct_set(interactions):
    """
    ``live_actors`` must return exactly the set of actors that were added
    and not yet removed.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)

    assert set(interactions.live_actors) == {a, b}


def test_live_actors_excludes_removed(interactions):
    """
    ``live_actors`` must not include actors that have been removed.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.remove_actor(a)

    assert interactions.live_actors == [b]


# ---------------------------------------------------------------------------
# get_actor_index_from_id
# ---------------------------------------------------------------------------


def test_get_actor_index_returns_stable_slot(interactions):
    """
    An actor's slot index returned by ``get_actor_index_from_id`` must remain
    unchanged after a different actor is removed.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)

    a_slot = interactions.get_actor_index_from_id(a.id)
    interactions.remove_actor(b)

    assert interactions.get_actor_index_from_id(a.id) == a_slot


def test_get_actor_index_unknown_id_raises(interactions):
    """
    Looking up a UUID that was never registered must raise a :exc:`ValueError`.
    """
    with pytest.raises(ValueError):
        interactions.get_actor_index_from_id(uuid.uuid4())


def test_get_actor_index_after_removal_raises(interactions):
    """
    Looking up an actor that has been removed must raise a :exc:`ValueError`.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    interactions.add_actor(a)
    interactions.remove_actor(a)

    with pytest.raises(ValueError):
        interactions.get_actor_index_from_id(a.id)


# ---------------------------------------------------------------------------
# update_interactions — interaction flags
# ---------------------------------------------------------------------------


def test_update_empty_does_not_crash(interactions):
    """
    Calling ``update_interactions`` on an empty instance must not raise.
    """
    interactions.update_interactions()


def test_update_single_actor_no_self_interaction(interactions):
    """
    A single actor must never be marked as interacting with itself.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    interactions.add_actor(a)
    interactions.update_interactions()

    slot = interactions.actors_id_dict[a.id]
    assert not interactions.interact[slot, slot]


def test_same_team_does_not_interact(interactions):
    """
    Two actors on the same team must not interact regardless of distance.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=1, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    assert not interactions.interact[sa, sb]
    assert not interactions.interact[sb, sa]


def test_neutral_team_does_not_interact(interactions):
    """
    A neutral actor (team 0) must not interact with any other actor.
    """
    a = MockActor(team=0, position=[0, 0, 0])  # neutral
    b = MockActor(team=1, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    assert not interactions.interact[sa, sb]
    assert not interactions.interact[sb, sa]


def test_different_teams_interact(interactions):
    """
    Two actors on different non-neutral teams within range must mutually interact.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    assert interactions.interact[sa, sb]
    assert interactions.interact[sb, sa]


def test_beyond_max_distance_does_not_interact(interactions):
    """
    Two opposing actors separated by more than ``INTERACT_MAX_DISTANCE_M``
    must not interact.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[INTERACT_MAX_DISTANCE_M + 1, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    assert not interactions.interact[sa, sb]


# ---------------------------------------------------------------------------
# update_interactions — matrix values
# ---------------------------------------------------------------------------


def test_distance_computed_correctly(interactions):
    """
    The distance stored in the matrix must equal the Euclidean distance between
    the two actors' positions, and must be symmetric.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[300, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    np.testing.assert_allclose(interactions.distances[sa, sb], 300.0)
    np.testing.assert_allclose(interactions.distances[sb, sa], 300.0)


def test_directions_are_unit_vectors_and_antisymmetric(interactions):
    """
    The direction from A to B must be a unit vector pointing along the correct
    axis, and the direction from B to A must be its exact negation.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[300, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    dir_ab = interactions.directions[sa, sb]
    dir_ba = interactions.directions[sb, sa]

    np.testing.assert_allclose(np.linalg.norm(dir_ab), 1.0, atol=1e-6)
    np.testing.assert_allclose(dir_ab, [1, 0, 0], atol=1e-6)
    np.testing.assert_allclose(dir_ab, -dir_ba, atol=1e-6)


def test_relative_velocity_computed(interactions):
    """
    The relative velocity stored for the pair (A, B) must equal
    ``b.speed - a.speed``, and the inverse entry must be its negation.
    """
    a = MockActor(team=1, position=[0, 0, 0], speed=[10, 0, 0])
    b = MockActor(team=2, position=[300, 0, 0], speed=[0, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    np.testing.assert_allclose(interactions.rel_velocities[sa, sb], [-10, 0, 0])
    np.testing.assert_allclose(interactions.rel_velocities[sb, sa], [10, 0, 0])


def test_alignment_computed(interactions):
    """
    When both actors face directly toward each other the alignment must be 1.0
    for both directions.
    """
    a = MockActor(team=1, position=[0, 0, 0], forward=[0, 1, 0])
    b = MockActor(team=2, position=[0, 300, 0], forward=[0, -1, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    np.testing.assert_allclose(interactions.alignments[sa, sb], 1.0, atol=1e-6)
    np.testing.assert_allclose(interactions.alignments[sb, sa], 1.0, atol=1e-6)


def test_alignment_zero_for_perpendicular(interactions):
    """
    When an actor faces perpendicular to the direction of its opponent the
    alignment must be 0.0.
    """
    a = MockActor(team=1, position=[0, 0, 0], forward=[1, 0, 0])
    b = MockActor(team=2, position=[0, 300, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    interactions.update_interactions()

    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    np.testing.assert_allclose(interactions.alignments[sa, sb], 0.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Target selection regression
# ---------------------------------------------------------------------------


def test_dead_slot_not_selectable_as_target(interactions):
    """
    After an actor is removed its slot's entire ``interact`` row must be
    ``False``, so it can never appear in ``np.where(interact_mask)`` and
    therefore can never be selected as a target by the player or a bot.

    This is the primary regression guard for the pre-allocated refactor.
    """
    player = MockActor(team=1, position=[0, 0, 0])
    enemy = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(player)
    interactions.add_actor(enemy)
    interactions.update_interactions()

    player_slot = interactions.actors_id_dict[player.id]
    assert interactions.interact[player_slot, :].any()  # sanity: enemy was visible

    interactions.remove_actor(enemy)

    target_mask = interactions.interact[player_slot, :]
    assert not target_mask.any()


def test_new_actor_in_reused_slot_is_selectable(interactions):
    """
    After slot reuse the replacement actor must interact correctly with
    existing actors, and ``actors[recycled_slot]`` must point to the new actor.
    """
    player = MockActor(team=1, position=[0, 0, 0])
    first_enemy = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(player)
    interactions.add_actor(first_enemy)
    interactions.update_interactions()

    recycled_slot = interactions.actors_id_dict[first_enemy.id]
    interactions.remove_actor(first_enemy)

    second_enemy = MockActor(team=2, position=[200, 0, 0])
    interactions.add_actor(second_enemy)
    assert interactions.actors_id_dict[second_enemy.id] == recycled_slot

    interactions.update_interactions()

    player_slot = interactions.actors_id_dict[player.id]
    assert interactions.interact[player_slot, recycled_slot]
    assert interactions.actors[recycled_slot] is second_enemy


def test_interact_mask_width_is_max_actors(interactions):
    """
    The ``interact`` row used for target selection must always be ``MAX_ACTORS``
    wide with all unused slots forced to ``False``, so that score arrays remain
    consistently sized across the lifetime of the simulation.
    """
    player = MockActor(team=1, position=[0, 0, 0])
    enemy = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(player)
    interactions.add_actor(enemy)
    interactions.update_interactions()

    player_slot = interactions.actors_id_dict[player.id]
    mask = interactions.interact[player_slot, :]

    assert len(mask) == MAX_ACTORS
    # Only the enemy's slot should be True; all unused slots are False
    assert mask.sum() == 1


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


def test_clean_nulls_all_references(interactions):
    """
    After ``clean()`` every attribute must be ``None`` so that the garbage
    collector can reclaim the pre-allocated numpy arrays.
    """
    interactions.add_actor(MockActor(team=1, position=[0, 0, 0]))
    interactions.clean()

    assert interactions.actors is None
    assert interactions.actors_id_dict is None
    assert interactions.alive is None
    assert interactions._free_slots is None
    assert interactions.interact is None
    assert interactions.distances is None
    assert interactions.directions is None
    assert interactions.alignments is None
    assert interactions.rel_velocities is None
