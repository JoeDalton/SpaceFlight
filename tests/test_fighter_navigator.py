"""
Unit tests for FighterNavigator (space_flight.ai.fighter.fighter_navigator).

FighterNavigator.__init__ creates a CollisionSensor which requires Panda3D.
All tests bypass __init__ via object.__new__() and populate the instance with
the minimal attributes consumed by each method.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.fighter.fighter_navigator import FighterNavigator


def make_fighter_navigator(
    personality: dict = None,
    pawn_position: np.ndarray = None,
) -> FighterNavigator:
    """
    Build a FighterNavigator that bypasses __init__.

    :param personality: personality dict; defaults to FIGHTER_DEFAULT
    :param pawn_position: world-space position of the owning ship
    :return: a FighterNavigator whose methods can be tested in isolation
    """
    if personality is None:
        personality = Personality.FIGHTER_DEFAULT
    nav = object.__new__(FighterNavigator)
    nav.game = MagicMock()
    nav.game.game_time.get_current_time.return_value = 0.0
    nav.pawn = MagicMock()
    nav.pawn.position = np.zeros(3) if pawn_position is None else pawn_position.copy()
    nav.pawn.max_speed_mps = 500.0
    nav.pawn.parent = MagicMock()
    nav.personality = personality
    nav.debug = False
    nav.behaviour = "idle"
    nav.behaviour_duration_s = 0.0
    nav.last_update_time = 0.0
    nav.waypoints = []
    nav.next_waypoint_idx = 0
    nav.distance_to_waypoint_m = 0.0
    nav.has_waypoint_loop = False
    nav.time_in_spiral_s = 0.0
    nav.collision_sensor = MagicMock()
    nav.collision_sensor.compute_repulsion.return_value = (np.zeros(3), 0.0)
    nav.engage_phase = ""
    return nav


# ---------------------------------------------------------------------------
# check_overshoot_risk
# ---------------------------------------------------------------------------


def test_check_overshoot_risk_negative_closing_speed_returns_false():
    """
    When the closing speed is negative (target moving away), there is no
    overshoot risk and the method must return False.
    """
    nav = make_fighter_navigator()

    assert nav.check_overshoot_risk(closing_speed_mps=-10.0, distance_m=500.0) is False


def test_check_overshoot_risk_zero_closing_speed_returns_false():
    """
    At exactly zero closing speed (target stationary relative to self) there
    is no overshoot risk.
    """
    nav = make_fighter_navigator()

    assert nav.check_overshoot_risk(closing_speed_mps=0.0, distance_m=500.0) is False


def test_check_overshoot_risk_high_speed_short_distance_returns_true():
    """
    A very high closing speed combined with a very short distance means the
    ship will overshoot before it can manoeuvre — must return True.
    """
    nav = make_fighter_navigator()
    minimum_time = nav.personality["navigator"]["reposition"][
        "minimum_time_to_overshoot_s"
    ]
    closing_speed = 1000.0
    distance_m = closing_speed * minimum_time * 0.1  # well below time threshold

    assert (
        nav.check_overshoot_risk(closing_speed_mps=closing_speed, distance_m=distance_m)
        is True
    )


def test_check_overshoot_risk_large_distance_returns_false():
    """
    Even with a high closing speed, a large enough distance gives plenty of
    time to react — must return False.
    """
    nav = make_fighter_navigator()
    minimum_time = nav.personality["navigator"]["reposition"][
        "minimum_time_to_overshoot_s"
    ]
    closing_speed = 100.0
    distance_m = closing_speed * minimum_time * 10.0  # well above time threshold

    assert (
        nav.check_overshoot_risk(closing_speed_mps=closing_speed, distance_m=distance_m)
        is False
    )


# ---------------------------------------------------------------------------
# check_extend_conditions
# ---------------------------------------------------------------------------


def test_check_extend_conditions_velocity_condition_not_met_returns_false():
    """
    When neither the low-closing-speed+high-lateral-speed condition nor the
    already-extending condition holds, check_extend_conditions returns False.
    """
    nav = make_fighter_navigator()
    nav.behaviour = "pursuit"
    nav.behaviour_duration_s = 10.0
    nav.time_in_spiral_s = 0.0

    result = nav.check_extend_conditions(
        longitudinal_speed_scalar_mps=500.0,  # well above minimum
        lateral_speed_scalar_mps=0.0,  # well below maximum
    )

    assert result is False


def test_check_extend_conditions_already_extending_not_long_enough_returns_true():
    """
    If the navigator is already in extend mode but has not been extending for
    the minimum required duration, the condition must remain True.
    """
    nav = make_fighter_navigator()
    nav.behaviour = "extend"
    minimum_duration = nav.personality["navigator"]["extend"]["minimum_duration_s"]
    nav.behaviour_duration_s = minimum_duration * 0.3  # too short

    result = nav.check_extend_conditions(
        longitudinal_speed_scalar_mps=500.0,
        lateral_speed_scalar_mps=0.0,
    )

    assert result is True


def test_check_extend_conditions_already_extending_long_enough_returns_false():
    """
    If the navigator is already in extend mode and has been extending for
    longer than the minimum required duration, the condition must be False
    (assuming velocity conditions are not met).
    """
    nav = make_fighter_navigator()
    nav.behaviour = "extend"
    minimum_duration = nav.personality["navigator"]["extend"]["minimum_duration_s"]
    nav.behaviour_duration_s = minimum_duration * 2.0  # long enough
    nav.time_in_spiral_s = 0.0

    result = nav.check_extend_conditions(
        longitudinal_speed_scalar_mps=500.0,
        lateral_speed_scalar_mps=0.0,
    )

    assert result is False


# ---------------------------------------------------------------------------
# reposition
# ---------------------------------------------------------------------------


def test_reposition_returns_negated_direction():
    """
    reposition() must return a direction that is the exact negation of the
    input direction.
    """
    nav = make_fighter_navigator()
    direction = np.array([0.0, 1.0, 0.0])

    result_direction, _ = nav.reposition(direction)

    np.testing.assert_allclose(result_direction, -direction, atol=1e-9)


def test_reposition_returns_turning_speed():
    """
    reposition() must return the turning speed from the personality dict.
    """
    nav = make_fighter_navigator()
    expected_speed = nav.personality["navigator"]["turning"]["speed_mps"]

    _, speed = nav.reposition(np.array([1.0, 0.0, 0.0]))

    assert speed == pytest.approx(expected_speed)


def test_reposition_resets_time_in_spiral():
    """
    reposition() must reset time_in_spiral_s to zero.
    """
    nav = make_fighter_navigator()
    nav.time_in_spiral_s = 3.0

    nav.reposition(np.array([0.0, 1.0, 0.0]))

    assert nav.time_in_spiral_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# extend
# ---------------------------------------------------------------------------


def test_extend_returns_zero_direction():
    """
    extend() must return the zero vector as its direction (go straight ahead).
    """
    nav = make_fighter_navigator()

    direction, _ = nav.extend()

    np.testing.assert_array_equal(direction, np.zeros(3))


def test_extend_returns_speeding_speed():
    """
    extend() must return the speeding speed from the personality dict.
    """
    nav = make_fighter_navigator()
    expected_speed = nav.personality["navigator"]["speeding"]["speed_mps"]

    _, speed = nav.extend()

    assert speed == pytest.approx(expected_speed)


# ---------------------------------------------------------------------------
# compute_engage_weights
# ---------------------------------------------------------------------------


def test_compute_engage_weights_far_distance_cap_weight_is_high():
    """
    At long range (beyond cap_cutoff_distance_m), the CAP weight must be
    close to 1 and the lag weight close to 0.
    """
    nav = make_fighter_navigator()
    far_distance = nav.personality["navigator"]["attack"]["cap_cutoff_distance_m"] * 5.0

    cap_weight, lead_weight, lag_weight = nav.compute_engage_weights(far_distance)

    assert cap_weight > 0.8
    assert lag_weight < 0.2


def test_compute_engage_weights_short_distance_lag_weight_is_high():
    """
    At very short range (below lag_cutoff_distance_m), the lag weight must be
    close to 1 and the CAP weight close to 0.
    """
    nav = make_fighter_navigator()
    short_distance = (
        nav.personality["navigator"]["attack"]["lag_cutoff_distance_m"] * 0.1
    )

    cap_weight, lead_weight, lag_weight = nav.compute_engage_weights(short_distance)

    assert lag_weight > 0.8
    assert cap_weight < 0.2


def test_compute_engage_weights_returns_three_values():
    """
    compute_engage_weights must return exactly three scalar weights.
    """
    nav = make_fighter_navigator()

    result = nav.compute_engage_weights(500.0)

    assert len(result) == 3


# ---------------------------------------------------------------------------
# compute_evasive_weave
# ---------------------------------------------------------------------------


def test_compute_evasive_weave_zero_amplitude_returns_base():
    """
    With zero amplitude the weave is a no-op and returns the base direction.
    """
    nav = make_fighter_navigator()
    base = np.array([0.0, 1.0, 0.0])

    result = nav.compute_evasive_weave(
        base_direction=base,
        up_reference=np.array([0.0, 0.0, 1.0]),
        amplitude=0.0,
        frequency_hz=0.5,
    )

    np.testing.assert_array_equal(result, base)


def test_compute_evasive_weave_stays_in_plane_and_unit():
    """
    Weaving a forward direction about the world-up reference keeps the result a
    unit vector in the horizontal plane (no vertical component introduced).
    """
    nav = make_fighter_navigator()
    nav.behaviour_duration_s = 0.3
    nav.weave_phase_rad = 1.0

    result = nav.compute_evasive_weave(
        base_direction=np.array([0.0, 1.0, 0.0]),
        up_reference=np.array([0.0, 0.0, 1.0]),
        amplitude=0.6,
        frequency_hz=0.5,
    )

    assert np.linalg.norm(result) == pytest.approx(1.0, abs=1e-6)
    assert result[2] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# strafe helpers
# ---------------------------------------------------------------------------


def test_below_altitude_floor_no_surface_info_returns_false():
    """
    Without surface info there is no altitude floor (open-space pass).
    """
    nav = make_fighter_navigator()
    strafe = nav.personality["navigator"]["strafe"]

    assert (
        nav._below_altitude_floor(
            surface_normal=None, surface_hit_point=None, strafe=strafe
        )
        is False
    )


def test_below_altitude_floor_true_when_too_low():
    """
    With the ship below the floor above the surface, the floor is breached.
    """
    nav = make_fighter_navigator()
    strafe = nav.personality["navigator"]["strafe"]
    normal = np.array([0.0, 0.0, 1.0])
    hit_point = np.zeros(3)
    nav.pawn.position = np.array([0.0, 0.0, strafe["altitude_floor_m"] * 0.5])

    assert (
        nav._below_altitude_floor(
            surface_normal=normal, surface_hit_point=hit_point, strafe=strafe
        )
        is True
    )


def test_below_altitude_floor_false_when_high_enough():
    """
    Well above the floor, it is not breached.
    """
    nav = make_fighter_navigator()
    strafe = nav.personality["navigator"]["strafe"]
    normal = np.array([0.0, 0.0, 1.0])
    hit_point = np.zeros(3)
    nav.pawn.position = np.array([0.0, 0.0, strafe["altitude_floor_m"] * 3.0])

    assert (
        nav._below_altitude_floor(
            surface_normal=normal, surface_hit_point=hit_point, strafe=strafe
        )
        is False
    )


def test_strafe_break_open_space_returns_negated_direction():
    """
    Without surface info the break simply turns back the way we came.
    """
    nav = make_fighter_navigator()
    strafe = nav.personality["navigator"]["strafe"]
    direction = np.array([0.0, 1.0, 0.0])

    break_direction, speed = nav._strafe_break(
        direction=direction, surface_normal=None, strafe=strafe
    )

    np.testing.assert_allclose(break_direction, -direction, atol=1e-9)
    assert speed == pytest.approx(strafe["break_speed_factor"] * nav.pawn.max_speed_mps)


def test_strafe_break_surface_climbs_along_normal():
    """
    With a surface normal the break has a positive component along it (climbs
    away from the surface) and is a unit vector.
    """
    nav = make_fighter_navigator()
    strafe = nav.personality["navigator"]["strafe"]
    normal = np.array([0.0, 0.0, 1.0])
    direction = np.array([0.0, 1.0, 0.0])

    break_direction, _ = nav._strafe_break(
        direction=direction, surface_normal=normal, strafe=strafe
    )

    assert np.dot(break_direction, normal) > 0.0
    assert np.linalg.norm(break_direction) == pytest.approx(1.0, abs=1e-6)


def test_strafe_reposition_extends_away_at_speeding_speed():
    """
    Reposition extends directly away from the target at the speeding speed.
    """
    nav = make_fighter_navigator()
    strafe = nav.personality["navigator"]["strafe"]
    direction = np.array([0.0, 1.0, 0.0])

    reposition_direction, speed = nav._strafe_reposition(
        direction=direction, strafe=strafe
    )

    np.testing.assert_allclose(reposition_direction, -direction, atol=1e-9)
    assert speed == pytest.approx(
        strafe["reposition_speed_factor"] * nav.pawn.max_speed_mps
    )


def _augment_pawn_for_strafe(nav):
    """Give the navigator's mocked pawn the attributes strafe_target reads."""
    nav.pawn.forward = np.array([0.0, 1.0, 0.0])
    nav.pawn.speed = np.zeros(3)
    nav.pawn.position = np.zeros(3)
    nav.pawn.laser_cannon = MagicMock()
    nav.game.scene.up_direction = np.array([0.0, 0.0, 1.0])


def _strafe_target_dict(distance_m):
    """Build a target_dict (with engagement geometry) for a stationary target
    straight ahead (+Y)."""
    return {
        "distance_m": distance_m,
        "direction": np.array([0.0, 1.0, 0.0]),
        "relative_speed_vector": np.zeros(3),
        "longitudinal_speed_scalar_mps": 0.0,
        "target_current_position": np.array([0.0, distance_m, 0.0]),
        "target_current_speed": np.zeros(3),
    }


def test_strafe_target_far_runs_ingress():
    """
    Beyond the attack distance the strafe run is in its ingress phase, at the
    ingress speed, with a unit direction.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_strafe(nav)
    strafe = nav.personality["navigator"]["strafe"]

    direction, speed = nav.strafe_target(
        target_dict=_strafe_target_dict(strafe["attack_distance_m"] * 2.0),
    )

    assert nav.behaviour == "strafe_ingress"
    assert speed == pytest.approx(
        strafe["ingress_speed_factor"] * nav.pawn.max_speed_mps
    )
    assert np.linalg.norm(direction) == pytest.approx(1.0, abs=1e-6)


def test_strafe_target_in_range_attacks_and_fires():
    """
    Inside the attack distance (but beyond the break standoff) the run enters the
    attack phase, at the attack speed, and fires the guns (nose on target).
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_strafe(nav)
    strafe = nav.personality["navigator"]["strafe"]
    distance = 0.5 * (strafe["break_distance_m"] + strafe["attack_distance_m"])

    _, speed = nav.strafe_target(target_dict=_strafe_target_dict(distance))

    assert nav.behaviour == "strafe_attack"
    assert speed == pytest.approx(
        strafe["attack_speed_factor"] * nav.pawn.max_speed_mps
    )
    nav.pawn.laser_cannon.fire.assert_called_once()


def test_strafe_attack_presses_in_while_closing():
    """
    In the attack phase, a fast-closing fighter that is not near point-blank keeps
    attacking however long it has been in the phase (no fixed timer).
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_strafe(nav)
    strafe = nav.personality["navigator"]["strafe"]
    nav.behaviour = "strafe_attack"
    nav.behaviour_duration_s = 10.0  # well past the old timer
    target_dict = _strafe_target_dict(400.0)
    target_dict["longitudinal_speed_scalar_mps"] = -200.0  # closing at 200 m/s

    _, speed = nav.strafe_target(target_dict=target_dict)

    assert nav.behaviour == "strafe_attack"
    assert speed == pytest.approx(
        strafe["attack_speed_factor"] * nav.pawn.max_speed_mps
    )


def test_strafe_ingress_leads_a_moving_target():
    """
    Against a laterally-moving target the ingress aims at the intercept (lead)
    point, so the flown direction gains a component in the target's motion
    direction rather than pointing at its current position.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_strafe(nav)
    target_dict = {
        "distance_m": 800.0,  # beyond attack_distance -> ingress phase
        "direction": np.array([0.0, 1.0, 0.0]),
        "relative_speed_vector": np.array([50.0, -100.0, 0.0]),
        "longitudinal_speed_scalar_mps": -100.0,  # closing at 100 m/s
        "target_current_position": np.array([0.0, 800.0, 0.0]),
        "target_current_speed": np.array([50.0, 0.0, 0.0]),  # moving +X
    }

    direction, _ = nav.strafe_target(target_dict=target_dict)

    assert nav.behaviour == "strafe_ingress"
    # Pure line-of-sight would be +Y only; leading tilts it toward +X.
    assert direction[0] > 0.05


def test_strafe_attack_breaks_when_stalled():
    """
    In the attack phase, a fighter that cannot close (near-zero closing speed) for
    longer than the stall grace peels off into the break.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_strafe(nav)
    strafe = nav.personality["navigator"]["strafe"]
    nav.behaviour = "strafe_attack"
    nav.behaviour_duration_s = strafe["stall_time_s"] + 1.0
    # longitudinal 0 -> closing 0 (stalled)
    target_dict = _strafe_target_dict(400.0)

    nav.strafe_target(target_dict=target_dict)

    assert nav.behaviour == "strafe_break"
