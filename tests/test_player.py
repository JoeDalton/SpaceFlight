"""
Unit tests for Player (space_flight.actors.player).

Player.__init__ requires a live Panda3D ShowBase (camera, collision system,
etc.).  All tests therefore bypass __init__ via object.__new__() and set only
the attributes consumed by each method under test.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.capital_ship.turret import Turret
from space_flight.actors.player import (
    HEAD_DAMPING_RATIO,
    HEAD_SPRING_COEFFICIENT_NPM,
    Player,
)
from space_flight.ai.interactions import Interactions

# ---------------------------
# Helpers
# ---------------------------


def make_player_for_target_mask(
    n_actors: int,
    target_filter: str = "All",
    initial_mask: np.ndarray = None,
) -> Player:
    """
    Build a Player stub configured for update_target_mask tests.

    :param n_actors: total number of actors in the interactions grid
    :param target_filter: the filter string stored on the player
    :param initial_mask: optional pre-existing target_mask (all-zeros if None)
    :return: the configured Player stub
    """
    player = object.__new__(Player)
    player.target_filter = target_filter
    player.target_mask = (
        np.zeros(n_actors) if initial_mask is None else initial_mask.copy()
    )
    game = MagicMock()
    game.interactions.n_actors = n_actors
    # Plain actors with no `category`, so "All" treats them all as targetable.
    game.interactions.live_actors = [object() for _ in range(n_actors)]
    player.game = game
    player.pawn = MagicMock()
    return player


def make_player_for_head_physics(
    head_position_m: np.ndarray = None,
    head_velocity_mps: np.ndarray = None,
    pawn_state_dot: np.ndarray = None,
    pawn_state: np.ndarray = None,
    pawn_impact_force_n: np.ndarray = None,
    pawn_mass_kg: float = 1000.0,
) -> Player:
    """
    Build a Player stub configured for head-physics computation tests.

    :param head_position_m: initial head position in body coordinates
    :param head_velocity_mps: initial head velocity in body coordinates
    :param pawn_state_dot: 10-element state derivative (position, quat, speed)
    :param pawn_state: 10-element state (position, quat, speed)
    :param pawn_impact_force_n: current impact force on the pawn
    :param pawn_mass_kg: pawn mass in kilograms
    :return: the configured Player stub
    """
    player = object.__new__(Player)
    player.head_position_m = (
        np.zeros(3) if head_position_m is None else head_position_m.copy()
    )
    player.head_velocity_mps = (
        np.zeros(3) if head_velocity_mps is None else head_velocity_mps.copy()
    )
    player.head_spring_coefficient_npm = HEAD_SPRING_COEFFICIENT_NPM
    player.head_damping_ratio = HEAD_DAMPING_RATIO
    player.head_inv_mass_pkg = 0.2
    player.head_damping_coefficient_nspm = (
        2
        * HEAD_DAMPING_RATIO
        * np.sqrt(HEAD_SPRING_COEFFICIENT_NPM / player.head_inv_mass_pkg)
    )

    player.pawn = MagicMock()
    player.pawn.mass_kg = pawn_mass_kg
    player.pawn.state_dot = (
        np.zeros(10) if pawn_state_dot is None else pawn_state_dot.copy()
    )
    # Identity quaternion: state[3:7] = [w, x, y, z] = [1, 0, 0, 0]
    player.pawn.state = (
        np.array([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        if pawn_state is None
        else pawn_state.copy()
    )
    player.pawn.impact_force_n = (
        np.zeros(3) if pawn_impact_force_n is None else pawn_impact_force_n.copy()
    )
    player.head_acceleration_mps2 = np.zeros(3)
    return player


# ---------------------------
# update_target_mask
# ---------------------------


def test_update_target_mask_all_filter_sets_mask_to_all_ones():
    """
    The "All" filter initialises every slot to 1 before zeroing the player's
    own slot.
    """
    n_actors = 5
    player_actor_index = 2
    player = make_player_for_target_mask(n_actors=n_actors, target_filter="All")

    player.update_target_mask(player_actor_index=player_actor_index)

    expected = np.ones(n_actors)
    expected[player_actor_index] = 0
    np.testing.assert_array_equal(player.target_mask, expected)


def test_update_target_mask_empty_string_filter_behaves_like_all():
    """
    An empty string filter produces the same result as "All".
    """
    n_actors = 4
    player_actor_index = 0
    player = make_player_for_target_mask(n_actors=n_actors, target_filter="")

    player.update_target_mask(player_actor_index=player_actor_index)

    expected = np.ones(n_actors)
    expected[player_actor_index] = 0
    np.testing.assert_array_equal(player.target_mask, expected)


def test_update_target_mask_always_zeros_out_player_slot():
    """
    Regardless of filter, the slot corresponding to the player is always 0.
    """
    n_actors = 6
    player_actor_index = 3
    player = make_player_for_target_mask(n_actors=n_actors, target_filter="All")

    player.update_target_mask(player_actor_index=player_actor_index)

    assert player.target_mask[player_actor_index] == 0


def test_update_target_mask_enemies_filter_uses_interact_matrix():
    """
    The "Enemies" filter copies the interact row for the player from the
    interactions matrix into the target mask.
    """
    n_actors = 4
    player_actor_index = 1
    interact_row = np.array([1, 0, 1, 1])

    player = make_player_for_target_mask(n_actors=n_actors, target_filter="Enemies")
    player.game.interactions.interact.__getitem__ = MagicMock(return_value=interact_row)
    player.game.interactions.alive = np.array([True, True, True, True])

    player.update_target_mask(player_actor_index=player_actor_index)

    # Player's own slot must still be zero
    assert player.target_mask[player_actor_index] == 0


def test_update_target_mask_unknown_filter_clears_mask():
    """
    An unrecognised filter fails safe to an all-zero mask sized to the
    current actor count, rather than reusing a stale mask that might have
    been computed for a different (now outdated) actor count -- reusing a
    wrong-sized mask could cause an out-of-bounds index in loop_target /
    point_target.
    """
    n_actors = 4
    player_actor_index = 2
    initial_mask = np.array([1.0, 0.0, 1.0, 1.0])
    player = make_player_for_target_mask(
        n_actors=n_actors,
        target_filter="Bogus filter",  # not a real filter
        initial_mask=initial_mask,
    )

    player.update_target_mask(player_actor_index=player_actor_index)

    np.testing.assert_array_equal(player.target_mask, np.zeros(n_actors))


@pytest.mark.parametrize(
    "n_actors, player_actor_index", [(1, 0), (3, 0), (3, 2), (8, 5)]
)
def test_update_target_mask_all_filter_parametrized(n_actors, player_actor_index):
    """
    Parametrised check: "All" filter with various fleet sizes and player positions.
    """
    player = make_player_for_target_mask(n_actors=n_actors, target_filter="All")

    player.update_target_mask(player_actor_index=player_actor_index)

    for idx in range(n_actors):
        if idx == player_actor_index:
            assert player.target_mask[idx] == 0
        else:
            assert player.target_mask[idx] == 1


def test_update_target_mask_capital_ships_filter_selects_by_category():
    """
    The "Capital ships" filter masks in only category == "capital_ship" actors.
    """
    player = make_player_for_target_mask(n_actors=3, target_filter="Capital ships")
    player.game.interactions.live_actors = [
        SimpleNamespace(category=None),  # the player: no category
        SimpleNamespace(category="fighter"),
        SimpleNamespace(category="capital_ship"),
    ]

    player.update_target_mask(player_actor_index=0)

    np.testing.assert_array_equal(player.target_mask, [0.0, 0.0, 1.0])


def test_update_target_mask_subsystems_filter_includes_turrets():
    """
    The "Subsystems" filter masks in category == "sub_system" actors, which
    includes turrets (turrets are subsystems, and also match "Turrets").
    """
    turret = MagicMock(spec=Turret)
    turret.category = "sub_system"
    player = make_player_for_target_mask(n_actors=3, target_filter="Subsystems")
    player.game.interactions.live_actors = [
        SimpleNamespace(category=None),  # the player: no category
        SimpleNamespace(category="sub_system"),  # e.g. a shield generator
        turret,
    ]

    player.update_target_mask(player_actor_index=0)

    np.testing.assert_array_equal(player.target_mask, [0.0, 1.0, 1.0])


def test_update_target_mask_turrets_filter_selects_turret_instances():
    """
    The "Turrets" filter masks in only Turret instances, even though a
    turret's category is "sub_system" rather than "turret".
    """
    turret = MagicMock(spec=Turret)
    turret.category = "sub_system"
    player = make_player_for_target_mask(n_actors=3, target_filter="Turrets")
    player.game.interactions.live_actors = [
        SimpleNamespace(category=None),  # the player: no category
        SimpleNamespace(category="sub_system"),  # e.g. a shield generator
        turret,
    ]

    player.update_target_mask(player_actor_index=0)

    np.testing.assert_array_equal(player.target_mask, [0.0, 0.0, 1.0])


def test_update_target_mask_fighters_filter_selects_by_category():
    """
    The "Fighters" filter masks in only category == "fighter" actors.
    """
    player = make_player_for_target_mask(n_actors=3, target_filter="Fighters")
    player.game.interactions.live_actors = [
        SimpleNamespace(category="fighter"),  # the player itself: also a fighter
        SimpleNamespace(category="fighter"),
        SimpleNamespace(category="capital_ship"),
    ]

    player.update_target_mask(player_actor_index=0)

    np.testing.assert_array_equal(player.target_mask, [0.0, 1.0, 0.0])


# ---------------------------
# loop_target
# ---------------------------


class MockTargetableActor:
    """
    Minimal actor stub satisfying both Interactions' attribute contract and
    update_target_mask's optional `category` lookup.
    """

    def __init__(self, name, category=None):
        self.id = uuid.uuid4()
        self.name = name
        self.team = 0
        self.category = category
        self.position = np.zeros(3)
        self.speed = np.zeros(3)
        self.forward = np.array([0.0, 1.0, 0.0])
        self.is_dead = False
        self.target = None
        self.target_id = None
        self.target_idx = None


def make_player_for_loop_target(pawn, interactions, target_filter: str = "All"):
    """
    Build a Player stub wired to a real Interactions instance, so loop_target
    exercises the actual (raw slot vs compressed position) index translation.

    :param pawn: The player's own actor, already added to `interactions`
    :param interactions: A real Interactions instance
    :param target_filter: the filter string stored on the player
    :return: the configured Player stub
    """
    player = object.__new__(Player)
    player.target_filter = target_filter
    player.pawn = pawn
    player.game = SimpleNamespace(interactions=interactions)
    return player


def test_loop_target_advances_through_all_targets_despite_a_gap():
    """
    Regression test: a dead actor's slot leaves a gap between currently-alive
    slots. Repeatedly looping "next target" must still visit every other
    live actor exactly once before wrapping back to the first one -- it must
    not get stuck jumping between the same one or two entries.
    """
    interactions = Interactions()
    pawn = MockTargetableActor("player")
    actor_a = MockTargetableActor("a")
    actor_b = MockTargetableActor("b")  # will be removed, leaving a gap
    actor_c = MockTargetableActor("c")
    interactions.add_actor(pawn)  # slot 0
    interactions.add_actor(actor_a)  # slot 1
    interactions.add_actor(actor_b)  # slot 2
    interactions.add_actor(actor_c)  # slot 3
    interactions.remove_actor(actor_b)  # frees slot 2, leaving a gap

    player = make_player_for_loop_target(pawn=pawn, interactions=interactions)

    visited = []
    for _ in range(3):
        player.loop_target(increment=1)
        visited.append(player.pawn.target.name)

    # Both remaining targets are visited before the cycle repeats
    assert visited == ["a", "c", "a"]


def test_loop_target_reverse_also_advances_correctly_with_a_gap():
    """
    Same kind of gap scenario as above (with an extra live target so forward
    and reverse traversal orders are distinguishable), but looping backwards
    (Shift-Tab style).
    """
    interactions = Interactions()
    pawn = MockTargetableActor("player")
    actor_a = MockTargetableActor("a")
    actor_b = MockTargetableActor("b")  # will be removed, leaving a gap
    actor_c = MockTargetableActor("c")
    actor_d = MockTargetableActor("d")
    interactions.add_actor(pawn)  # slot 0
    interactions.add_actor(actor_a)  # slot 1
    interactions.add_actor(actor_b)  # slot 2
    interactions.add_actor(actor_c)  # slot 3
    interactions.add_actor(actor_d)  # slot 4
    interactions.remove_actor(actor_b)  # frees slot 2, leaving a gap

    player = make_player_for_loop_target(pawn=pawn, interactions=interactions)

    visited = []
    for _ in range(4):
        player.loop_target(increment=-1)
        visited.append(player.pawn.target.name)

    # All three remaining targets are visited before the cycle repeats.
    assert visited == ["c", "a", "d", "c"]
    assert set(visited) == {"a", "c", "d"}


def test_loop_target_keeps_current_target_selected_on_repeated_calls_with_one_target():
    """
    With only one available target beyond a gap, looping must keep landing on
    it rather than losing track of the current target and failing to find it.
    """
    interactions = Interactions()
    pawn = MockTargetableActor("player")
    actor_dead = MockTargetableActor("dead")  # will be removed, leaving a gap
    actor_only = MockTargetableActor("only")
    interactions.add_actor(pawn)  # slot 0
    interactions.add_actor(actor_dead)  # slot 1
    interactions.add_actor(actor_only)  # slot 2
    interactions.remove_actor(actor_dead)  # frees slot 1, leaving a gap

    player = make_player_for_loop_target(pawn=pawn, interactions=interactions)

    player.loop_target(increment=1)
    assert player.pawn.target.name == "only"
    # Calling again must still find "only" as the (unchanged) current target,
    # not lose track of it because of a stale/mismatched index comparison.
    player.loop_target(increment=1)
    assert player.pawn.target.name == "only"


# ---------------------------
# compute_head_acceleration
# ---------------------------


def test_compute_head_acceleration_at_rest_with_identity_orientation_is_zero():
    """
    When the ship is at rest (no acceleration, no impact) and the head is at
    the origin with zero velocity, the net head acceleration is zero.
    """
    player = make_player_for_head_physics()

    player.compute_head_acceleration()

    np.testing.assert_array_almost_equal(player.head_acceleration_mps2, np.zeros(3))


def test_compute_head_acceleration_spring_pulls_displaced_head_back():
    """
    A head displaced along the X axis in body coordinates experiences a
    negative (restoring) spring acceleration along that axis.
    """
    displacement = np.array([0.5, 0.0, 0.0])
    player = make_player_for_head_physics(head_position_m=displacement)

    player.compute_head_acceleration()

    # Spring force = -k * x; acceleration = force * inv_mass
    spring_contribution = (
        -HEAD_SPRING_COEFFICIENT_NPM * displacement * player.head_inv_mass_pkg
    )
    # Sign: inertial pseudo-force is negated in the formula, spring is added
    # With no ship acceleration the head_acceleration is purely spring + damping
    np.testing.assert_array_almost_equal(
        player.head_acceleration_mps2, spring_contribution
    )


def test_compute_head_acceleration_damping_opposes_velocity():
    """
    A head moving along Y at constant velocity experiences a negative
    (damping) acceleration along that axis when displaced.
    """
    velocity = np.array([0.0, 1.0, 0.0])
    player = make_player_for_head_physics(head_velocity_mps=velocity)

    player.compute_head_acceleration()

    damping_contribution = (
        -player.head_damping_coefficient_nspm * velocity * player.head_inv_mass_pkg
    )
    np.testing.assert_array_almost_equal(
        player.head_acceleration_mps2, damping_contribution
    )


def test_compute_head_acceleration_stores_result_on_player():
    """
    compute_head_acceleration() updates the head_acceleration_mps2 attribute.
    """
    player = make_player_for_head_physics(head_position_m=np.array([0.1, 0.0, 0.0]))
    # The initial value is zero; after the call it must be non-zero
    player.compute_head_acceleration()

    assert not np.allclose(player.head_acceleration_mps2, np.zeros(3))


# ---------------------------
# compute_head_position
# ---------------------------


def test_compute_head_position_delegates_to_integrator(mock_integrator_step=None):
    """
    compute_head_position() calls game.integrator.first_order_euler_step once
    and uses the returned values to update head_position_m and head_velocity_mps.
    """
    player = make_player_for_head_physics(
        head_position_m=np.array([1.0, 0.0, 0.0]),
        head_velocity_mps=np.array([0.0, 2.0, 0.0]),
    )
    player.head_acceleration_mps2 = np.array([0.0, 0.0, -3.0])

    expected_new_state = np.array([1.5, 0.5, 0.0, 0.1, 2.1, -0.3])
    player.game = MagicMock()
    player.game.integrator.first_order_euler_step.return_value = expected_new_state

    player.compute_head_position()

    player.game.integrator.first_order_euler_step.assert_called_once()
    np.testing.assert_array_equal(player.head_position_m, expected_new_state[0:3])
    np.testing.assert_array_equal(player.head_velocity_mps, expected_new_state[3:6])


def test_compute_head_position_passes_correct_state_to_integrator():
    """
    compute_head_position() assembles a 6-element state vector containing
    [position(3), velocity(3)] before passing it to the integrator.
    """
    position = np.array([2.0, 0.0, -1.0])
    velocity = np.array([0.5, -0.5, 0.0])
    acceleration = np.array([0.0, 1.0, 0.0])

    player = make_player_for_head_physics(
        head_position_m=position,
        head_velocity_mps=velocity,
    )
    player.head_acceleration_mps2 = acceleration
    player.game = MagicMock()
    player.game.integrator.first_order_euler_step.return_value = np.zeros(6)

    player.compute_head_position()

    call_kwargs = player.game.integrator.first_order_euler_step.call_args.kwargs
    expected_state = np.concatenate([position, velocity])
    expected_derivative = np.concatenate([velocity, acceleration])
    np.testing.assert_array_equal(call_kwargs["state"], expected_state)
    np.testing.assert_array_equal(call_kwargs["state_derivative"], expected_derivative)
