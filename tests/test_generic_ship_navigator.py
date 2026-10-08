"""
Unit tests for GenericShipNavigator (space_flight.ai.generic.generic_ship_navigator).

GenericShipNavigator.__init__ instantiates a CollisionSensor which requires
Panda3D collision nodes.  All tests bypass __init__ via object.__new__() and
populate the instance with the minimal attributes consumed by each method.
"""

import copy
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Intent, Personality
from space_flight.ai.generic.generic_ship_navigator import (
    NO_DIRECTION,
    GenericShipNavigator,
)
from space_flight.utils.state_machine import StateMachine


def make_ship_navigator(
    pawn_position: np.ndarray = None,
    max_speed_mps: float = 500.0,
    personality: dict = None,
) -> GenericShipNavigator:
    """
    Build a GenericShipNavigator that bypasses __init__.

    :param pawn_position: world-space position of the owning ship
    :param max_speed_mps: maximum speed of the owning ship in m/s
    :param personality: personality dict; defaults to FIGHTER_DEFAULT
    :return: a GenericShipNavigator whose methods can be tested in isolation
    """
    if personality is None:
        personality = Personality.FIGHTER_DEFAULT
    nav = object.__new__(GenericShipNavigator)
    nav.game = MagicMock()
    nav.game.game_time.get_current_time.return_value = 0.0
    nav.pawn = MagicMock()
    nav.pawn.position = np.zeros(3) if pawn_position is None else pawn_position.copy()
    nav.pawn.max_speed_mps = max_speed_mps
    nav.pawn.parent = MagicMock()
    nav.personality = personality
    nav.debug = False
    nav.behaviour_sm = StateMachine("idle", clock=nav.game.game_time.get_current_time)
    nav.waypoints = []
    nav.next_waypoint_idx = 0
    nav.distance_to_waypoint_m = 0.0
    nav.has_waypoint_loop = False
    nav._best_distance_to_waypoint_m = float("inf")
    nav._time_without_progress_s = 0.0
    nav.patrol_speed_factor = 1.0
    nav.time_in_spiral_s = 0.0
    nav._last_navigate_s = None
    nav.think_dt_s = 0.0
    nav.collision_sensor = MagicMock()
    nav.collision_sensor.compute_repulsion.return_value = (np.zeros(3), 0.0)
    return nav


# ---------------------------------------------------------------------------
# regroup
# ---------------------------------------------------------------------------


def test_regroup_returns_direction_toward_target():
    """
    regroup() must return a unit direction pointing from self toward the
    target's position.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    target_position = np.array([0.0, 300.0, 0.0])

    direction, _ = nav.regroup(target_dict={"position": target_position})

    np.testing.assert_allclose(direction, np.array([0.0, 1.0, 0.0]), atol=1e-6)


def test_regroup_speed_matches_personality():
    """
    regroup() must return the regroup speed from the personality dict.
    """
    nav = make_ship_navigator()
    target_position = np.array([0.0, 300.0, 0.0])

    _, speed = nav.regroup(target_dict={"position": target_position})

    expected_speed = Personality.FIGHTER_DEFAULT["navigator"]["regroup"]["speed_mps"]
    assert speed == pytest.approx(expected_speed)


def test_regroup_at_zero_distance_returns_no_direction():
    """
    When the target coincides with self, regroup() must return NO_DIRECTION
    (zero vector, constant speed) to avoid dividing by zero.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))

    result = nav.regroup(target_dict={"position": np.zeros(3)})

    no_dir_vector, no_dir_speed = NO_DIRECTION
    result_vector, result_speed = result
    np.testing.assert_array_equal(result_vector, no_dir_vector)
    assert result_speed == pytest.approx(no_dir_speed)


# ---------------------------------------------------------------------------
# disengage
# ---------------------------------------------------------------------------


def test_disengage_returns_direction_away_from_target():
    """
    disengage() must return a unit direction pointing away from the target.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    target_position = np.array([0.0, 200.0, 0.0])

    direction, _ = nav.disengage(target_dict={"position": target_position})

    np.testing.assert_allclose(direction, np.array([0.0, -1.0, 0.0]), atol=1e-6)


def test_disengage_at_zero_distance_returns_no_direction():
    """
    When the danger center coincides with self, disengage() must return
    NO_DIRECTION.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))

    result = nav.disengage(target_dict={"position": np.zeros(3)})

    no_dir_vector, _ = NO_DIRECTION
    result_vector, _ = result
    np.testing.assert_array_equal(result_vector, no_dir_vector)


# ---------------------------------------------------------------------------
# set_waypoints / follow_waypoints
# ---------------------------------------------------------------------------


def test_follow_waypoints_returns_direction_toward_next_waypoint():
    """
    follow_waypoints() must return a unit direction pointing to the current
    waypoint when it is far enough away.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    waypoint = np.array([0.0, 500.0, 0.0])
    nav.set_waypoints([waypoint], is_loop=False)

    direction, _ = nav.follow_waypoints()

    np.testing.assert_allclose(direction, np.array([0.0, 1.0, 0.0]), atol=1e-6)


def test_follow_waypoints_advances_index_when_within_tolerance():
    """
    When the ship is already within the waypoint tolerance radius, the index
    must advance and NO_DIRECTION is returned for that frame.
    """
    tolerance_m = Personality.FIGHTER_DEFAULT["navigator"]["patrol"][
        "waypoint_meeting_tolerance_m"
    ]
    nearby_waypoint = np.array([0.0, tolerance_m * 0.5, 0.0])
    far_waypoint = np.array([0.0, 1000.0, 0.0])
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints([nearby_waypoint, far_waypoint], is_loop=False)

    nav.follow_waypoints()

    assert nav.next_waypoint_idx == 1


def test_follow_waypoints_decelerates_when_not_getting_closer():
    """
    A ship orbiting a waypoint (distance not shrinking) must slow down, but
    never below min_speed_factor.
    """
    patrol = Personality.FIGHTER_DEFAULT["navigator"]["patrol"]
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints([np.array([0.0, 500.0, 0.0])], is_loop=True)
    nav.think_dt_s = 1.0

    _, first_speed = nav.follow_waypoints()
    assert first_speed == patrol["speed_mps"]
    speeds = [nav.follow_waypoints()[1] for _ in range(200)]

    assert speeds[-1] < patrol["speed_mps"]
    assert min(speeds) >= patrol["speed_mps"] * patrol["min_speed_factor"] - 1e-9
    assert speeds == sorted(speeds, reverse=True)


def test_follow_waypoints_keeps_speed_when_approaching():
    """
    A ship steadily closing on its waypoint keeps the full patrol speed.
    """
    patrol = Personality.FIGHTER_DEFAULT["navigator"]["patrol"]
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints([np.array([0.0, 5000.0, 0.0])], is_loop=False)
    nav.think_dt_s = 1.0

    for step in range(50):
        nav.pawn.position = np.array([0.0, 20.0 * step, 0.0])
        _, speed = nav.follow_waypoints()
        assert speed == patrol["speed_mps"]


def test_follow_waypoints_resets_speed_when_waypoint_reached():
    """
    Reaching a waypoint restores full speed for the next leg.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints(
        [np.array([0.0, 500.0, 0.0]), np.array([0.0, 5000.0, 0.0])], is_loop=False
    )
    nav.think_dt_s = 1.0
    for _ in range(100):
        nav.follow_waypoints()
    assert nav.patrol_speed_factor < 1.0

    nav.pawn.position = np.array([0.0, 490.0, 0.0])
    nav.follow_waypoints()

    assert nav.next_waypoint_idx == 1
    assert nav.patrol_speed_factor == 1.0


def test_follow_waypoints_loops_when_has_waypoint_loop():
    """
    After all waypoints are visited in loop mode, the index wraps back to 0
    and the navigator points toward the first waypoint again.
    """
    tolerance_m = Personality.FIGHTER_DEFAULT["navigator"]["patrol"][
        "waypoint_meeting_tolerance_m"
    ]
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    # Place the waypoint far enough away so it is NOT reached within tolerance
    far_waypoint = np.array([0.0, tolerance_m * 10.0, 0.0])
    nav.set_waypoints([far_waypoint], is_loop=True)
    nav.next_waypoint_idx = 1  # Simulate all waypoints visited

    nav.follow_waypoints()

    # Loop wraps to 0, then processes waypoints[0] which is far → stays at 0
    assert nav.next_waypoint_idx == 0


def test_follow_waypoints_no_loop_clears_waypoints_when_done():
    """
    After all non-loop waypoints are visited the waypoints list is emptied.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints([np.array([0.0, 1000.0, 0.0])], is_loop=False)
    nav.next_waypoint_idx = 1  # All visited

    nav.follow_waypoints()

    assert nav.waypoints == []


def test_follow_waypoints_after_clearing_a_loop_returns_no_direction():
    """
    A cleared looping route (the tactician may still be committed to
    patrolling for a moment) must not be indexed: NO_DIRECTION instead.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints([np.array([0.0, 1000.0, 0.0])], is_loop=True)

    nav.clear_waypoints()
    result_vector, _ = nav.follow_waypoints()

    assert nav.waypoints == []
    assert nav.has_waypoint_loop is False
    np.testing.assert_array_equal(result_vector, NO_DIRECTION[0])


# ---------------------------------------------------------------------------
# compute_follow_speed
# ---------------------------------------------------------------------------


def test_compute_follow_speed_clamped_above_zero():
    """
    compute_follow_speed must never return a negative speed even when the
    target's speed and distance contribution would pull it below zero.
    """
    nav = make_ship_navigator(max_speed_mps=100.0)

    speed = nav.compute_follow_speed(
        distance_m=0.0,
        target_speed_mps=0.0,
        longitudinal_speed_scalar_mps=0.0,
        intent="formation",
    )

    assert speed >= 0.0


def test_compute_follow_speed_respects_minimum_speed():
    """
    With a minimum_speed_factor in the intent's personality section, the follow
    speed never drops below that fraction of max_speed_mps, even when the
    target is slow and close.
    """
    personality = copy.deepcopy(Personality.FIGHTER_DEFAULT)
    personality["navigator"]["attack"]["minimum_speed_factor"] = 0.5
    nav = make_ship_navigator(max_speed_mps=300.0, personality=personality)

    speed = nav.compute_follow_speed(
        distance_m=0.0,
        target_speed_mps=0.0,
        longitudinal_speed_scalar_mps=0.0,
        intent="attack",
    )

    assert speed == pytest.approx(150.0)


def test_compute_minimum_speed_defaults_to_zero():
    """An intent section without minimum_speed_factor has no speed floor."""
    nav = make_ship_navigator(max_speed_mps=300.0)

    assert nav.compute_minimum_speed("formation") == 0.0


def test_compute_follow_speed_clamped_below_max_speed():
    """
    compute_follow_speed must never exceed pawn.max_speed_mps.
    """
    max_speed = 300.0
    nav = make_ship_navigator(max_speed_mps=max_speed)

    speed = nav.compute_follow_speed(
        distance_m=10000.0,
        target_speed_mps=max_speed,
        longitudinal_speed_scalar_mps=0.0,
        intent="formation",
    )

    assert speed <= max_speed


# ---------------------------------------------------------------------------
# navigate — blending intent and avoidance
# ---------------------------------------------------------------------------


def test_navigate_with_zero_avoidance_equals_intent_output():
    """
    When the collision sensor returns zero avoidance weight the navigate()
    result must match the intent output directly (no blending penalty).
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.collision_sensor.compute_repulsion.return_value = (np.zeros(3), 0.0)

    intent_direction = np.array([0.0, 1.0, 0.0])
    intent_speed = 200.0

    nav.navigate_intent = MagicMock(return_value=(intent_direction, intent_speed))

    result_direction, result_speed = nav.navigate(
        intent=Intent.REGROUP, target_dict={"position": np.array([0.0, 500.0, 0.0])}
    )

    np.testing.assert_allclose(result_direction, intent_direction, atol=1e-6)
    assert result_speed == pytest.approx(intent_speed)


def _navigate_with_avoidance(nav, minimum_speed_mps: float) -> float:
    """
    Run navigate() with a strong collision-avoidance contribution (weight 3)
    and an intent at 200 m/s that sets the given speed floor.

    :return: The blended speed
    """
    nav.collision_sensor.compute_repulsion.return_value = (
        np.array([1.0, 0.0, 0.0]),
        3.0,
    )

    def navigate_intent(intent, target_dict):
        nav.minimum_speed_mps = minimum_speed_mps
        return np.array([0.0, 1.0, 0.0]), 200.0

    nav.navigate_intent = navigate_intent
    _, speed = nav.navigate(intent=Intent.ENGAGE, target_dict={})
    return speed


# Blend of a 200 m/s intent with avoidance at weight 3: (200 + 50) / (1 + 3)
BLENDED_SPEED_MPS = 62.5


def test_navigate_speed_floor_caps_the_avoidance_slowdown():
    """
    With minimum_speed_overrides_avoidance, collision avoidance can't slow the
    ship below the intent's speed floor.
    """
    nav = make_ship_navigator()

    speed = _navigate_with_avoidance(nav, minimum_speed_mps=150.0)

    assert speed == pytest.approx(150.0)


def test_navigate_speed_floor_ignored_without_the_override():
    """
    Without minimum_speed_overrides_avoidance, avoidance slows the ship as
    before, floor or not.
    """
    personality = copy.deepcopy(Personality.FIGHTER_DEFAULT)
    personality["navigator"]["attack"]["minimum_speed_overrides_avoidance"] = False
    nav = make_ship_navigator(personality=personality)

    speed = _navigate_with_avoidance(nav, minimum_speed_mps=150.0)

    assert speed == pytest.approx(BLENDED_SPEED_MPS)


def test_navigate_resets_the_speed_floor():
    """
    The floor only lasts one navigate(): an intent that doesn't raise it
    (anything but a pursuit) flies without one.
    """
    nav = make_ship_navigator()
    nav.minimum_speed_mps = 150.0  # left by a previous pursuit

    speed = _navigate_with_avoidance(nav, minimum_speed_mps=0.0)

    assert nav.minimum_speed_mps == 0.0
    assert speed == pytest.approx(BLENDED_SPEED_MPS)


# ---------------------------------------------------------------------------
# formation — route progress kept in step with the leader
# ---------------------------------------------------------------------------

ROUTE = [np.array([0.0, 1000.0, 0.0]), np.array([1000.0, 1000.0, 0.0])]


def _wingman_and_leader(leader_waypoints, leader_idx: int, has_navigator=True):
    """
    A wingman navigator on ROUTE (at its first waypoint) and its leader's pawn,
    registered in the mocked interactions.

    :return: The wingman navigator and the formation target dict
    """
    nav = make_ship_navigator(pawn_position=np.array([0.0, -100.0, 0.0]))
    nav.pawn.speed = np.array([0.0, 100.0, 0.0])
    nav.waypoints = list(ROUTE)
    nav._best_distance_to_waypoint_m = 42.0
    leader = MagicMock()
    leader.position = np.zeros(3)
    leader.speed = np.array([0.0, 100.0, 0.0])
    leader.forward = np.array([0.0, 1.0, 0.0])
    leader.right = np.array([1.0, 0.0, 0.0])
    leader.up = np.array([0.0, 0.0, 1.0])
    if has_navigator:
        leader.parent.navigator.waypoints = leader_waypoints
        leader.parent.navigator.next_waypoint_idx = leader_idx
    else:
        leader.parent = MagicMock(spec=[])  # e.g. the player: no navigator
    nav.game.interactions.get_actor_index_from_id.return_value = 0
    nav.game.interactions.actors = [leader]
    target_dict = {
        "target_id": "leader",
        "target_relative_position": np.array([30.0, -60.0, 0.0]),
    }
    return nav, target_dict


def test_formation_syncs_route_progress_with_the_leader():
    """
    A wingman on the leader's route mirrors its progress, so it resumes the
    route where the leader left it if it takes the lead.
    """
    nav, target_dict = _wingman_and_leader([w.copy() for w in ROUTE], leader_idx=1)

    nav.formation(target_dict)

    assert nav.next_waypoint_idx == 1
    assert nav._best_distance_to_waypoint_m == float("inf")


def test_formation_does_not_sync_a_different_route():
    """
    A leader on another route leaves the wingman's progress alone.
    """
    nav, target_dict = _wingman_and_leader([ROUTE[1], ROUTE[0]], leader_idx=1)

    nav.formation(target_dict)

    assert nav.next_waypoint_idx == 0


def test_formation_does_not_sync_without_a_leader_navigator():
    """
    A leader without a navigator (the player) leaves the progress alone.
    """
    nav, target_dict = _wingman_and_leader(None, leader_idx=1, has_navigator=False)

    nav.formation(target_dict)

    assert nav.next_waypoint_idx == 0
