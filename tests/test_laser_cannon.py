"""
Unit tests for LaserCannon (space_flight.weapons.laser_cannon).

LaserCannon.__init__ requires live Panda3D nodes and asset pools, so tests
that exercise post-construction logic use object.__new__() to bypass it and
manually set the minimal attributes needed by each method under test.

LaserShot creation inside fire() is monkeypatched out so that the cannon
cycling and rate-limiting logic can be validated without a live render context.
"""

import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from panda3d.core import Vec3

from space_flight.actors.energy import EnergySystem
from space_flight.weapons.laser_cannon import LASER_SPEED_MPS, LaserCannon

FIRE_DELAY_S = 0.5
N_CANNONS = 2
LASER_SHOT_ENERGY_COST = 0.02


@pytest.fixture
def laser_cannon():
    """
    A LaserCannon instance with __init__ bypassed and all necessary attributes
    set to sensible defaults for testing.
    """
    cannon = object.__new__(LaserCannon)
    cannon.fire_delay = FIRE_DELAY_S
    cannon.last_fire_time = 0.0
    cannon.current_next_cannon_idx = 0
    cannon.n_cannon = N_CANNONS
    cannon.cannon_nodes = [MagicMock(name=f"cannon_node_{i}") for i in range(N_CANNONS)]
    cannon.shot_power = 10.0
    cannon.life_time_s = 1.0
    cannon.light_color = (1.0, 0.0, 0.0, 1.0)
    cannon.laser_color_rgb = Vec3(1.0, 0.05, 0.05)
    cannon.sound_pool = MagicMock()
    # Unlimited power unless a test plugs in an energy system
    cannon.energy = None
    # Exact shots unless a test sets a deviation cone
    cannon.deviation_cone_rad = 0.0
    cannon.damage_multiplier = 1.0

    # Parent ship stub: no auto_aim so fire() falls back to speed + forward
    cannon.parent = MagicMock()
    del cannon.parent.auto_aim  # ensure AttributeError path is taken
    cannon.parent.forward = np.array([0.0, 1.0, 0.0])
    cannon.parent.speed = np.zeros(3)
    cannon.parent.id = uuid.uuid4()

    cannon.game = MagicMock()
    cannon.game.game_time.get_current_time.return_value = 0.0

    return cannon


# ---------------------------
# fire() – rate limiting
# ---------------------------


def test_fire_does_not_proceed_before_cooldown_expires(laser_cannon):
    """
    fire() returns immediately without spawning a shot when the elapsed time
    since the last shot is shorter than fire_delay.
    """
    laser_cannon.game.game_time.get_current_time.return_value = (
        laser_cannon.last_fire_time + FIRE_DELAY_S * 0.5
    )

    laser_cannon.fire()

    # get_pos on any cannon node is only called when a shot is actually fired
    for node in laser_cannon.cannon_nodes:
        node.get_pos.assert_not_called()


def test_fire_proceeds_exactly_at_cooldown_boundary(laser_cannon):
    """
    fire() spawns a shot when elapsed time equals exactly fire_delay.
    """
    laser_cannon.game.game_time.get_current_time.return_value = (
        laser_cannon.last_fire_time + FIRE_DELAY_S
    )

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    mock_laser_shot.assert_called_once()


def test_fire_proceeds_after_cooldown_expires(laser_cannon):
    """
    fire() spawns a shot when sufficient time has passed since the last shot.
    """
    laser_cannon.game.game_time.get_current_time.return_value = (
        laser_cannon.last_fire_time + FIRE_DELAY_S * 2
    )

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    mock_laser_shot.assert_called_once()


# ---------------------------
# fire() – laser energy
# ---------------------------


def test_fire_refuses_without_enough_laser_energy(laser_cannon):
    """
    An energy-powered gun does not fire on a gauge below one bolt's cost, and
    the refused shot does not consume the reload gate.
    """
    laser_cannon.energy = EnergySystem(
        has_shields=True, laser_shot_energy_cost=LASER_SHOT_ENERGY_COST
    )
    laser_cannon.energy.lasers = 0.5 * LASER_SHOT_ENERGY_COST
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    mock_laser_shot.assert_not_called()
    assert laser_cannon.last_fire_time == 0.0


def test_fire_spends_laser_energy_and_applies_damage_bonus(laser_cannon):
    """
    Each bolt costs its energy, and carries the damage bonus of the gauge level
    it was fired at.
    """
    energy = EnergySystem(
        has_shields=True, laser_shot_energy_cost=LASER_SHOT_ENERGY_COST
    )
    laser_cannon.energy = energy
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S
    expected_power = laser_cannon.shot_power * energy.laser_damage_factor()

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    assert mock_laser_shot.call_args.kwargs["power"] == pytest.approx(expected_power)
    assert expected_power > laser_cannon.shot_power
    assert energy.lasers == pytest.approx(1.0 - LASER_SHOT_ENERGY_COST)


def test_fire_scales_the_bolt_power_by_the_damage_multiplier(laser_cannon):
    """
    The damage multiplier scales the bolt's power, on top of the laser gauge's
    damage bonus.
    """
    energy = EnergySystem(
        has_shields=True, laser_shot_energy_cost=LASER_SHOT_ENERGY_COST
    )
    laser_cannon.energy = energy
    laser_cannon.damage_multiplier = 2.0
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S
    expected_power = 2.0 * laser_cannon.shot_power * energy.laser_damage_factor()

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    assert mock_laser_shot.call_args.kwargs["power"] == pytest.approx(expected_power)


def test_fire_without_energy_system_uses_base_power(laser_cannon):
    """
    A gun with no energy system (a turret's) fires at its base power.
    """
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    assert mock_laser_shot.call_args.kwargs["power"] == laser_cannon.shot_power


# ---------------------------
# fire() – cannon index cycling
# ---------------------------


def test_fire_advances_cannon_index_after_shot(laser_cannon):
    """
    fire() increments current_next_cannon_idx by one after a successful shot.
    """
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    assert laser_cannon.current_next_cannon_idx == 1


def test_fire_wraps_cannon_index_around_after_last_cannon(laser_cannon):
    """
    After the last cannon fires, current_next_cannon_idx wraps back to zero.
    """
    laser_cannon.current_next_cannon_idx = N_CANNONS - 1
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    assert laser_cannon.current_next_cannon_idx == 0


# ---------------------------
# fire() -- player vs NPC cannon sound
# ---------------------------


def test_fire_marks_the_sound_as_the_players_when_the_parent_is_the_player(
    laser_cannon,
):
    """
    fire() tells SFX.cannon_fire this is the player's own gun when
    game.player.pawn is the firing ship.
    """
    laser_cannon.game.player.pawn = laser_cannon.parent
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    _, kwargs = laser_cannon.game.app.sfx.cannon_fire.call_args
    assert kwargs["is_player"] is True


def test_fire_marks_the_sound_as_an_npcs_when_the_parent_is_not_the_player(
    laser_cannon,
):
    """
    fire() tells SFX.cannon_fire this is not the player's gun when the firing
    ship is anyone else's (e.g. a bot's fighter or a capital ship's turret).
    """
    assert laser_cannon.parent is not laser_cannon.game.player.pawn
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    _, kwargs = laser_cannon.game.app.sfx.cannon_fire.call_args
    assert kwargs["is_player"] is False


def test_fire_marks_the_sound_as_an_npcs_when_there_is_no_player(laser_cannon):
    """
    fire() does not crash and reports is_player=False when game.player is
    None (e.g. a headless run with no human-piloted ship).
    """
    laser_cannon.game.player = None
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    _, kwargs = laser_cannon.game.app.sfx.cannon_fire.call_args
    assert kwargs["is_player"] is False


def test_fire_uses_current_cannon_node_for_shot_origin(laser_cannon):
    """
    fire() calls get_pos on the cannon node at current_next_cannon_idx.
    """
    laser_cannon.current_next_cannon_idx = 1
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    laser_cannon.cannon_nodes[1].get_pos.assert_called_once_with(
        laser_cannon.game.root_node
    )
    laser_cannon.cannon_nodes[0].get_pos.assert_not_called()


def test_fire_updates_last_fire_time(laser_cannon):
    """
    fire() records the current time as last_fire_time after a successful shot.
    """
    fire_time = 7.3
    laser_cannon.game.game_time.get_current_time.return_value = fire_time

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    assert laser_cannon.last_fire_time == pytest.approx(fire_time)


def test_fire_does_not_update_last_fire_time_when_on_cooldown(laser_cannon):
    """
    fire() does not change last_fire_time when the cooldown has not expired.
    """
    initial_last_fire_time = laser_cannon.last_fire_time
    laser_cannon.game.game_time.get_current_time.return_value = (
        initial_last_fire_time + FIRE_DELAY_S * 0.1
    )

    laser_cannon.fire()

    assert laser_cannon.last_fire_time == pytest.approx(initial_last_fire_time)


# ---------------------------
# fire() – consecutive calls cycle through all cannons
# ---------------------------


def test_fire_cycles_through_all_cannon_indices(laser_cannon):
    """
    Firing once per cannon cycles through indices 0 → 1 → 0 for a two-cannon
    configuration.
    """
    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        for shot_number in range(N_CANNONS * 2):
            laser_cannon.last_fire_time = 0.0
            laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S
            expected_index_before = shot_number % N_CANNONS
            assert laser_cannon.current_next_cannon_idx == expected_index_before
            laser_cannon.fire()


# ---------------------------
# fire() – shot direction and deviation
# ---------------------------


def _fire_shot_speeds(cannon: LaserCannon, n: int) -> list[np.ndarray]:
    """
    :return: The world velocities of n shots fired by cannon, the reload gate
        being open for each
    """
    speeds = []
    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        for i in range(n):
            cannon.game.game_time.get_current_time.return_value = (i + 1) * 10.0
            cannon.fire()
            speeds.append(mock_laser_shot.call_args.kwargs["speed"])
    return speeds


def _angles_deg(directions: list[np.ndarray], axis: np.ndarray) -> np.ndarray:
    """:return: The angles between each unit direction and the unit axis."""
    return np.degrees(
        np.arccos(np.clip([np.dot(d, axis) for d in directions], -1.0, 1.0))
    )


def test_fire_without_auto_aim_shoots_forward_plus_parent_speed(laser_cannon):
    """
    Without auto-aim or deviation, the bolt flies along the nose, plus the
    parent's velocity.
    """
    laser_cannon.parent.speed = np.array([10.0, 0.0, 0.0])

    (speed,) = _fire_shot_speeds(laser_cannon, n=1)

    np.testing.assert_allclose(speed, [10.0, LASER_SPEED_MPS, 0.0], atol=1e-9)


def test_fire_shoots_along_the_auto_aim_direction(laser_cannon):
    """With auto-aim, the bolt flies along the direction it computes."""
    aimed = np.array([0.6, 0.8, 0.0])
    laser_cannon.parent.auto_aim = MagicMock()
    laser_cannon.parent.auto_aim.compute_shot_direction.return_value = aimed.copy()

    (speed,) = _fire_shot_speeds(laser_cannon, n=1)

    np.testing.assert_allclose(speed, LASER_SPEED_MPS * aimed, atol=1e-9)


def test_fire_deviates_shots_within_the_cone(laser_cannon):
    """
    Shots deviate randomly from the nose (no auto-aim, e.g. a turret without a
    targeting system), never beyond the cone, and spread over it rather than
    bunching on the axis.
    """
    np.random.seed(0)
    laser_cannon.deviation_cone_rad = np.deg2rad(2.0)

    speeds = _fire_shot_speeds(laser_cannon, n=500)

    angles = _angles_deg([v / LASER_SPEED_MPS for v in speeds], np.array([0, 1, 0]))
    assert angles.max() <= 2.0 + 1e-9
    # Uniform over the cone's solid angle: half the shots beyond ~1.41 degrees
    assert np.median(angles) == pytest.approx(2.0 / np.sqrt(2.0), abs=0.15)


def test_fire_deviates_shots_around_the_auto_aim_direction(laser_cannon):
    """Deviation is applied around the auto-aimed direction, not the nose."""
    np.random.seed(0)
    aimed = np.array([0.6, 0.8, 0.0])
    laser_cannon.parent.auto_aim = MagicMock()
    laser_cannon.parent.auto_aim.compute_shot_direction.side_effect = (
        lambda start_position: aimed.copy()
    )
    laser_cannon.deviation_cone_rad = np.deg2rad(0.5)

    speeds = _fire_shot_speeds(laser_cannon, n=200)

    angles = _angles_deg([v / LASER_SPEED_MPS for v in speeds], aimed)
    assert angles.max() <= 0.5 + 1e-9


def test_fire_adds_the_parent_speed_after_deviating(laser_cannon):
    """
    The deviation turns the bolt's own velocity only: the parent's velocity is
    added afterwards, unchanged.
    """
    np.random.seed(0)
    parent_speed = np.array([0.0, 0.0, 300.0])
    laser_cannon.parent.speed = parent_speed
    laser_cannon.deviation_cone_rad = np.deg2rad(2.0)

    speeds = _fire_shot_speeds(laser_cannon, n=20)

    for speed in speeds:
        assert np.linalg.norm(speed - parent_speed) == pytest.approx(LASER_SPEED_MPS)


def test_fire_deviation_does_not_modify_the_parents_forward(laser_cannon):
    """The parent's forward vector is neither normalised nor otherwise touched."""
    forward = laser_cannon.parent.forward
    laser_cannon.deviation_cone_rad = np.deg2rad(2.0)

    _fire_shot_speeds(laser_cannon, n=5)

    assert laser_cannon.parent.forward is forward
    np.testing.assert_array_equal(forward, [0.0, 1.0, 0.0])


def test_fire_without_deviation_draws_nothing_random(laser_cannon):
    """A zero cone leaves the aimed direction exact."""
    with patch("space_flight.weapons.laser_cannon.sample_direction_in_cone") as sample:
        _fire_shot_speeds(laser_cannon, n=3)

    sample.assert_not_called()


# ---------------------------
# clean()
# ---------------------------


def test_clean_calls_remove_node_on_all_cannon_nodes(laser_cannon):
    """
    clean() calls remove_node() on every cannon node.
    """
    laser_cannon.clean()

    for node in laser_cannon.cannon_nodes:
        node.remove_node.assert_called_once()


def test_clean_empties_cannon_nodes_list(laser_cannon):
    """
    clean() replaces cannon_nodes with an empty list.
    """
    laser_cannon.clean()

    assert laser_cannon.cannon_nodes == []


def test_clean_clears_parent_reference(laser_cannon):
    """
    clean() sets parent to None so the cannon holds no upward reference.
    """
    laser_cannon.clean()

    assert laser_cannon.parent is None


def test_clean_clears_game_reference(laser_cannon):
    """
    clean() sets game to None.
    """
    laser_cannon.clean()

    assert laser_cannon.game is None


def test_clean_clears_laser_color_reference(laser_cannon):
    """
    clean() sets laser_color_rgb to None.
    """
    laser_cannon.clean()

    assert laser_cannon.laser_color_rgb is None
