"""
Unit tests for Player (space_flight.actors.player).

Player.__init__ requires a live Panda3D ShowBase (camera, collision system,
etc.).  All tests therefore bypass __init__ via object.__new__() and set only
the attributes consumed by each method under test.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.player import (
    HEAD_DAMPING_RATIO,
    HEAD_SPRING_COEFFICIENT_NPM,
    Player,
)

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


def test_update_target_mask_unknown_filter_does_not_change_mask():
    """
    An unrecognised filter leaves the existing target mask unchanged (except
    zeroing the player's own slot, which always happens).
    """
    n_actors = 4
    player_actor_index = 2
    initial_mask = np.array([1.0, 0.0, 1.0, 1.0])
    player = make_player_for_target_mask(
        n_actors=n_actors,
        target_filter="Capital ships",  # not yet fully implemented
        initial_mask=initial_mask,
    )

    player.update_target_mask(player_actor_index=player_actor_index)

    # Slots other than the player's own should be unchanged
    for idx in range(n_actors):
        if idx != player_actor_index:
            assert player.target_mask[idx] == initial_mask[idx]
    assert player.target_mask[player_actor_index] == 0


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
