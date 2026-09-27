import uuid

import numpy as np
import pytest

from space_flight.ai import INTERACT_MAX_DISTANCE_M, TARGET_DISTANCE_TOLERANCE_M
from space_flight.ai.interactions import MAX_ACTORS, Interactions
from space_flight.utils import magnitude


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
    Attempting to add a third actor to an instance created with max_actors=2
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
    assert slot in interactions.free_slots


def test_remove_actor_zeroes_interact_row_and_col(interactions):
    """
    After removal, the entire interact row and column for the freed slot
    must be False so that no other actor can appear to interact with it.
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
    After removal, the entire distances row and column for the freed slot
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
    stable slot indices eliminate the stale target_idx bug that existed
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
    n_actors must equal the number of actors that have been added.
    """
    interactions.add_actor(MockActor(team=1, position=[0, 0, 0]))
    interactions.add_actor(MockActor(team=2, position=[100, 0, 0]))
    assert interactions.n_actors == 2


def test_n_actors_after_remove(interactions):
    """
    n_actors must decrement by one after a removal.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)

    interactions.remove_actor(a)

    assert interactions.n_actors == 1


def test_live_actors_contains_no_nones(interactions):
    """
    live_actors must never contain None entries regardless of how
    many slots are occupied.
    """
    interactions.add_actor(MockActor(team=1, position=[0, 0, 0]))
    interactions.add_actor(MockActor(team=2, position=[100, 0, 0]))
    assert None not in interactions.live_actors


def test_live_actors_returns_correct_set(interactions):
    """
    live_actors must return exactly the set of actors that were added
    and not yet removed.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)

    assert set(interactions.live_actors) == {a, b}


def test_live_actors_excludes_removed(interactions):
    """
    live_actors must not include actors that have been removed.
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
    An actor's slot index returned by get_actor_index_from_id must remain
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
    Calling update_interactions on an empty instance must not raise.
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
    Two opposing actors separated by more than INTERACT_MAX_DISTANCE_M
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
    b.speed - a.speed, and the inverse entry must be its negation.
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
    After an actor is removed its slot's entire interact row must be
    False, so it can never appear in np.where(interact_mask) and
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
    existing actors, and actors[recycled_slot] must point to the new actor.
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
    The interact row used for target selection must always be MAX_ACTORS
    wide with all unused slots forced to False, so that score arrays remain
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
    After clean() every attribute must be None so that the garbage
    collector can reclaim the pre-allocated numpy arrays.
    """
    interactions.add_actor(MockActor(team=1, position=[0, 0, 0]))
    interactions.clean()

    assert interactions.actors is None
    assert interactions.actors_id_dict is None
    assert interactions.alive is None
    assert interactions.free_slots is None
    assert interactions.interact is None
    assert interactions.distances is None
    assert interactions.directions is None
    assert interactions.alignments is None
    assert interactions.rel_velocities is None


# ---------------------------------------------------------------------------
# Actors without kinematics (e.g. subsystems)
# ---------------------------------------------------------------------------


class BareActor:
    """
    A targetable actor with no speed and no forward (like a subsystem),
    exercising the interactions' tolerance for missing kinematics.
    """

    def __init__(self, team, position):
        self.id = uuid.uuid4()
        self.name = f"bare_{str(self.id)[:8]}"
        self.team = team
        self.position = np.array(position, dtype=float)


def test_update_interactions_tolerates_missing_speed_and_forward(interactions):
    """
    An actor lacking speed and forward still takes part in interactions:
    its velocity and facing default to zero rather than raising.
    """
    ship = MockActor(team=1, position=[0.0, 0.0, 0.0])
    subsystem = BareActor(team=2, position=[10.0, 0.0, 0.0])
    interactions.add_actor(ship)
    interactions.add_actor(subsystem)

    interactions.update_interactions()  # must not raise

    i_ship = interactions.get_actor_index_from_id(ship.id)
    i_sub = interactions.get_actor_index_from_id(subsystem.id)
    # Opposing teams within range => they interact
    assert interactions.interact[i_ship, i_sub]
    # The unoriented subsystem contributes a zero alignment (no facing)
    assert interactions.alignments[i_sub, i_ship] == pytest.approx(0.0)
    # Relative velocity falls back to zero for the speed-less subsystem
    np.testing.assert_allclose(interactions.rel_velocities[i_ship, i_sub], 0.0)


# ---------------------------------------------------------------------------
# Vectorized update vs the original per-pair loop
# ---------------------------------------------------------------------------


def _reference_update_interactions(ix):
    """
    The original per-pair loop implementation of update_interactions, kept as
    the reference the vectorized version is checked against. It only writes
    geometry for interacting pairs.
    """
    live_indices = np.where(ix.alive)[0]
    n_live = len(live_indices)
    for i in range(1, n_live):
        idx_source = live_indices[i]
        source_actor = ix.actors[idx_source]
        for j in range(0, i):
            idx_target = live_indices[j]
            target_actor = ix.actors[idx_target]
            interact = not (
                source_actor.team == 0
                or target_actor.team == 0
                or source_actor.team == target_actor.team
            )
            if interact:
                direction = np.float64(target_actor.position - source_actor.position)
                distance = magnitude(direction)
                if distance > TARGET_DISTANCE_TOLERANCE_M:
                    direction /= distance
                else:
                    direction = np.zeros(3)
                    distance = 0.0
                interact *= distance < INTERACT_MAX_DISTANCE_M
            if interact:
                target_velocity = getattr(target_actor, "speed", np.zeros(3))
                source_velocity = getattr(source_actor, "speed", np.zeros(3))
                rel_velocity = target_velocity - source_velocity
                ix.directions[idx_source, idx_target, :] = direction
                ix.distances[idx_source, idx_target] = distance
                ix.rel_velocities[idx_source, idx_target, :] = rel_velocity
                ix.directions[idx_target, idx_source, :] = -direction
                ix.distances[idx_target, idx_source] = distance
                ix.rel_velocities[idx_target, idx_source, :] = -rel_velocity
            ix.interact[idx_source, idx_target] = interact
            ix.interact[idx_target, idx_source] = interact
    for i in range(n_live):
        idx_source = live_indices[i]
        source_forward = getattr(ix.actors[idx_source], "forward", np.zeros(3))
        for j in range(n_live):
            idx_target = live_indices[j]
            if ix.interact[idx_source, idx_target] and (idx_source != idx_target):
                ix.alignments[idx_source, idx_target] = np.dot(
                    ix.directions[idx_source, idx_target, :], source_forward
                )


def _expected_pair_geometry(source, target):
    """Direct per-pair computation of (distance, direction, rel_velocity, alignment)."""
    offset = np.asarray(target.position, dtype=float) - source.position
    distance = float(np.linalg.norm(offset))
    if distance > TARGET_DISTANCE_TOLERANCE_M:
        direction = offset / distance
    else:
        direction, distance = np.zeros(3), 0.0
    rel_velocity = getattr(target, "speed", np.zeros(3)) - getattr(
        source, "speed", np.zeros(3)
    )
    alignment = float(np.dot(direction, getattr(source, "forward", np.zeros(3))))
    return distance, direction, rel_velocity, alignment


@pytest.mark.parametrize("seed", range(5))
def test_update_interactions_matches_reference(seed):
    """
    Over several frames of random movement, the vectorized update must:
    - produce exactly the same interact flags as the original loop;
    - produce the same geometry for interacting pairs, to rounding (numpy may
      vectorize the arithmetic differently on another CPU);
    - also fill correct geometry for non-interacting live pairs, which the
      original loop left stale;
    - leave dead slots' rows and columns zeroed.
    Covers slot holes and reuse, neutral and same-team actors, actors without
    speed/forward, coincident and out-of-range pairs, and team changes.
    """
    rng = np.random.default_rng(seed)
    vectorized, reference = Interactions(), Interactions()

    def add(actor):
        vectorized.add_actor(actor)
        reference.add_actor(actor)

    def remove(actor):
        vectorized.remove_actor(actor)
        reference.remove_actor(actor)

    actors = []
    for k, team in enumerate([1] * 4 + [2] * 10 + [3] * 5 + [0] * 3):
        position = rng.uniform(-7000, 7000, 3)
        if k % 5 == 3:
            actor = BareActor(team=team, position=position)
        else:
            actor = MockActor(
                team=team,
                position=position,
                speed=list(rng.uniform(-300, 300, 3)),
                forward=list(rng.normal(size=3)),
            )
        actors.append(actor)
        add(actor)
    # A coincident pair of opposing actors (below the distance tolerance)
    actors[5].position = actors[0].position + 0.1
    # Slot hole, then slot reuse by a new actor
    remove(actors.pop(2))
    remove(actors.pop(7))
    newcomer = MockActor(team=2, position=[1.0, 2.0, 3.0], speed=[5.0, 0.0, 0.0])
    actors.append(newcomer)
    add(newcomer)

    for frame in range(5):
        if frame == 2:
            actors[3].team = 3  # switches sides
            actors[4].team = 0  # turns neutral
        vectorized.update_interactions()
        _reference_update_interactions(reference)

        np.testing.assert_array_equal(vectorized.interact, reference.interact)
        mask = reference.interact
        for name in ("distances", "directions", "rel_velocities", "alignments"):
            np.testing.assert_allclose(
                getattr(vectorized, name)[mask],
                getattr(reference, name)[mask],
                rtol=1e-14,
                atol=1e-15,
            )

        live = np.flatnonzero(vectorized.alive)
        for i in live:
            for j in live:
                if mask[i, j]:
                    continue
                distance, direction, rel_velocity, alignment = _expected_pair_geometry(
                    vectorized.actors[i], vectorized.actors[j]
                )
                np.testing.assert_allclose(
                    vectorized.distances[i, j], distance, rtol=1e-12, atol=1e-9
                )
                np.testing.assert_allclose(
                    vectorized.directions[i, j], direction, rtol=1e-12, atol=1e-12
                )
                np.testing.assert_allclose(
                    vectorized.rel_velocities[i, j], rel_velocity, atol=1e-12
                )
                np.testing.assert_allclose(
                    vectorized.alignments[i, j], alignment, atol=1e-12
                )

        dead = np.flatnonzero(~vectorized.alive)
        for name in ("distances", "directions", "rel_velocities", "alignments"):
            matrix = getattr(vectorized, name)
            assert not matrix[dead].any() and not matrix[:, dead].any()
        assert not vectorized.interact[dead].any()
        assert not vectorized.interact[:, dead].any()

        # Move everyone, with steps large enough for pairs to cross the
        # INTERACT_MAX_DISTANCE_M boundary both ways
        for actor in actors:
            actor.position = actor.position + rng.uniform(-4000, 4000, 3)


def test_geometry_filled_for_non_interacting_pairs(interactions):
    """
    Same-team and neutral pairs never interact, but their geometry must still
    be computed (e.g. the player scores friendly capital ships or waypoint
    markers by distance and alignment).
    """
    a = MockActor(team=1, position=[0, 0, 0], forward=[1, 0, 0])
    friend = MockActor(team=1, position=[300, 0, 0])
    marker = MockActor(team=0, position=[0, 400, 0])
    for actor in (a, friend, marker):
        interactions.add_actor(actor)
    interactions.update_interactions()

    sa, sf, sm = (interactions.actors_id_dict[x.id] for x in (a, friend, marker))
    assert not interactions.interact[sa].any()
    np.testing.assert_allclose(interactions.distances[sa, sf], 300.0)
    np.testing.assert_allclose(interactions.directions[sa, sf], [1, 0, 0])
    np.testing.assert_allclose(interactions.alignments[sa, sf], 1.0)
    np.testing.assert_allclose(interactions.distances[sa, sm], 400.0)
    np.testing.assert_allclose(interactions.alignments[sa, sm], 0.0, atol=1e-12)


def test_update_writes_matrices_in_place(interactions):
    """
    Navigators keep views such as directions[i, j, :] across frames, so the
    update must write into the existing arrays rather than replace them.
    """
    a = MockActor(team=1, position=[0, 0, 0])
    b = MockActor(team=2, position=[100, 0, 0])
    interactions.add_actor(a)
    interactions.add_actor(b)
    sa, sb = interactions.actors_id_dict[a.id], interactions.actors_id_dict[b.id]
    interactions.update_interactions()
    held_view = interactions.directions[sa, sb, :]

    b.position = np.array([0.0, 100.0, 0.0])
    interactions.update_interactions()

    np.testing.assert_allclose(held_view, [0, 1, 0])


def test_diagonal_is_zero_even_with_non_finite_kinematics(interactions):
    """
    An actor never interacts with itself: every matrix keeps a zero diagonal,
    even for an actor whose speed or facing is NaN (NaN - NaN is NaN).
    """
    healthy = MockActor(team=1, position=[0, 0, 0], speed=[10, 0, 0])
    broken = MockActor(team=2, position=[100, 0, 0])
    broken.speed = np.array([np.nan, 0.0, 0.0])
    broken.forward = np.array([np.nan, np.nan, np.nan])
    interactions.add_actor(healthy)
    interactions.add_actor(broken)
    interactions.update_interactions()

    for slot in (interactions.actors_id_dict[x.id] for x in (healthy, broken)):
        assert not interactions.interact[slot, slot]
        assert interactions.distances[slot, slot] == 0.0
        assert interactions.alignments[slot, slot] == 0.0
        assert not interactions.directions[slot, slot].any()
        assert not interactions.rel_velocities[slot, slot].any()
