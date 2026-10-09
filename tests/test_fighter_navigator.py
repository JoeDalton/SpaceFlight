"""
Unit tests for FighterNavigator (space_flight.ai.fighter.fighter_navigator).

FighterNavigator.__init__ creates a CollisionSensor which requires Panda3D.
All tests bypass __init__ via object.__new__() and populate the instance with
the minimal attributes consumed by each method.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Intent, Personality
from space_flight.ai.fighter.fighter_navigator import FighterNavigator
from space_flight.ai.generic.generic_ship_navigator import NO_DIRECTION
from space_flight.ai.missile.incoming_missile import IncomingMissile
from space_flight.utils.state_machine import StateMachine


class _Clock:
    """A controllable time source for the behaviour state machine."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _enter_behaviour(nav, name: str, duration_s: float = 0.0):
    """Put the navigator in *name* with the given time-in-state on its clock."""
    nav._clock.t = 0.0
    nav.behaviour_sm.request(name, force=True)
    nav._clock.t = duration_s


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
    clock = _Clock()
    nav._clock = clock
    nav.game.game_time.get_current_time.side_effect = clock
    nav.pawn = MagicMock()
    nav.pawn.position = np.zeros(3) if pawn_position is None else pawn_position.copy()
    nav.pawn.max_speed_mps = 500.0
    nav.pawn.parent = MagicMock()
    nav.personality = personality
    nav.debug = False
    nav.behaviour_sm = StateMachine("idle", clock=clock)
    nav.game.game_time.get_time_step.return_value = 0.1
    nav.waypoints = []
    nav.next_waypoint_idx = 0
    nav.distance_to_waypoint_m = 0.0
    nav.has_waypoint_loop = False
    nav._best_distance_to_waypoint_m = float("inf")
    nav._time_without_progress_s = 0.0
    nav.patrol_speed_factor = 1.0
    nav.time_in_spiral_s = 0.0
    nav._last_navigate_s = None
    nav.think_dt_s = 0.1  # matches get_time_step above
    nav._armed_trigger = None
    nav._flared_missile_ids = set()
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
    _enter_behaviour(nav, "pursuit", 10.0)
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
    minimum_duration = nav.personality["navigator"]["extend"]["minimum_duration_s"]
    _enter_behaviour(nav, "extend", minimum_duration * 0.3)  # too short

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
    minimum_duration = nav.personality["navigator"]["extend"]["minimum_duration_s"]
    _enter_behaviour(nav, "extend", minimum_duration * 2.0)  # long enough
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
    nav._clock.t = 0.3  # behaviour_duration_s -> 0.3
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
    Reposition extends directly away from the target at reposition_speed_factor
    of the ship's top speed.
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
    _enter_behaviour(nav, "strafe_attack", 10.0)  # long in the phase
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
    _enter_behaviour(nav, "strafe_attack", strafe["stall_time_s"] + 1.0)
    # longitudinal 0 -> closing 0 (stalled)
    target_dict = _strafe_target_dict(400.0)

    nav.strafe_target(target_dict=target_dict)

    assert nav.behaviour == "strafe_break"


# ---------------------------------------------------------------------------
# bombing run
# ---------------------------------------------------------------------------


BOMB_LAUNCH_SPEED_MPS = 75.0


def _augment_pawn_for_bomb(nav):
    """
    Give the mocked pawn what the bomb run + release solver read: a bomb
    launcher, dropping bombs along the belly, as its selected secondary weapon.
    """
    nav.pawn.position = np.zeros(3)
    nav.pawn.forward = np.array([0.0, 1.0, 0.0])
    nav.pawn.up = np.array([0.0, 0.0, 1.0])
    nav.pawn.speed = np.array([0.0, 100.0, 0.0])
    launcher = MagicMock(category="bomb", stock=6)
    launcher.initial_velocity.side_effect = lambda: (
        nav.pawn.speed - BOMB_LAUNCH_SPEED_MPS * nav.pawn.up
    )
    nav.pawn.selected_secondary = launcher
    nav.pawn.fire_secondary = MagicMock(return_value=True)
    nav.bomb_launcher = launcher
    nav.game.scene.up_direction = np.array([0.0, 0.0, 1.0])
    nav.up_reference = None


def _bomb_engagement(
    distance_m, direction, target_position, longitudinal=0.0, target_speed=None
):
    return {
        "distance_m": distance_m,
        "direction": direction,
        "relative_speed_vector": np.zeros(3),
        "longitudinal_speed_scalar_mps": longitudinal,
        "target_current_position": target_position,
        "target_current_speed": (np.zeros(3) if target_speed is None else target_speed),
    }


def _bomb_velocity_dir(nav):
    """The bomb's launch direction for the current pawn (speed - launch * up)."""
    v_bomb = nav.pawn.speed - BOMB_LAUNCH_SPEED_MPS * nav.pawn.up
    return v_bomb / np.linalg.norm(v_bomb)


def test_compute_release_condition_aligned_in_range_returns_true():
    """
    A target lying along the bomb's (forward-and-down) velocity within range
    yields a release.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    bomb = nav.personality["navigator"]["bomb"]
    target_position = _bomb_velocity_dir(nav) * 100.0  # on the bomb line, 100 m

    assert (
        nav.compute_release_condition(
            target_position, np.zeros(3), bomb, nav.bomb_launcher
        )
        is True
    )


def test_compute_release_condition_out_of_range_returns_false():
    """
    On the bomb line but beyond the release range: no drop.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    bomb = nav.personality["navigator"]["bomb"]
    target_position = _bomb_velocity_dir(nav) * 500.0  # aligned but too far

    assert (
        nav.compute_release_condition(
            target_position, np.zeros(3), bomb, nav.bomb_launcher
        )
        is False
    )


def test_compute_release_condition_misaligned_returns_false():
    """
    A target dead ahead (not under the belly) is not on the bomb's velocity.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    bomb = nav.personality["navigator"]["bomb"]
    target_position = np.array([0.0, 100.0, 0.0])  # straight ahead, level

    assert (
        nav.compute_release_condition(
            target_position, np.zeros(3), bomb, nav.bomb_launcher
        )
        is False
    )


def test_bomb_target_not_yet_behind_runs_ingress():
    """
    When not yet on the target's tail (here abeam a target crossing +X), the bombing
    run is in its ingress phase, banking toward the entry point.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    bomb = nav.personality["navigator"]["bomb"]
    engagement = _bomb_engagement(
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        target_position=np.array([0.0, 1000.0, 0.0]),
        target_speed=np.array([50.0, 0.0, 0.0]),  # crossing +X -> bomber is abeam
    )

    _, speed = nav.bomb_target(engagement)

    assert nav.behaviour == "bomb_ingress"
    assert speed == pytest.approx(bomb["ingress_speed_factor"] * nav.pawn.max_speed_mps)
    assert nav.up_reference is None  # ingress banks, no belly aim


def test_bomb_ingress_aims_at_entry_point_along_target_track():
    """
    The ingress flies to the entry point: entry_distance_m behind the target along
    its velocity track, at run altitude above it (and publishes no up-reference).
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    bomb = nav.personality["navigator"]["bomb"]
    target_position = np.array([0.0, 1000.0, 0.0])
    target_speed = np.array([50.0, 0.0, 0.0])  # crossing +X -> bomber is abeam
    engagement = _bomb_engagement(
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        target_position=target_position,
        target_speed=target_speed,
    )

    desired_direction, _ = nav.bomb_target(engagement)

    up = nav.game.scene.up_direction
    expected_entry = (
        target_position
        - np.array([1.0, 0.0, 0.0]) * bomb["entry_distance_m"]
        + up * bomb["run_altitude_m"]
    )
    expected_dir = expected_entry / np.linalg.norm(expected_entry)
    assert nav.behaviour == "bomb_ingress"
    assert np.allclose(desired_direction, expected_dir, atol=1e-6)
    assert nav.up_reference is None


def test_bomb_ingress_reaches_entry_transitions_to_approach():
    """
    At the entry point (behind the target, on its track line) the ingress hands
    off to the approach run.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    bomb = nav.personality["navigator"]["bomb"]
    up = nav.game.scene.up_direction
    target_position = np.array([0.0, 3000.0, 0.0])
    target_speed = np.array([0.0, 50.0, 0.0])
    entry_point = (
        target_position
        - np.array([0.0, 1.0, 0.0]) * bomb["entry_distance_m"]
        + up * bomb["run_altitude_m"]
    )
    nav.pawn.position = entry_point.copy()  # sitting at the entry point
    engagement = _bomb_engagement(
        distance_m=float(np.linalg.norm(target_position - nav.pawn.position)),
        direction=np.array([0.0, 1.0, 0.0]),
        target_position=target_position,
        longitudinal=-30.0,
        target_speed=target_speed,
    )

    nav.bomb_target(engagement)

    assert nav.behaviour == "bomb_approach"


def test_bomb_approach_follows_track_line_belly_down():
    """
    In the approach the bomber follows the target's track line (carrot pure-pursuit at
    run altitude, run_lookahead ahead of its own along-track position), flown
    belly-down (publishes the up-reference).
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    _enter_behaviour(nav, "bomb_approach")
    bomb = nav.personality["navigator"]["bomb"]
    up = nav.game.scene.up_direction
    track = np.array([0.0, 1.0, 0.0])
    target_position = np.array([0.0, 800.0, 0.0])
    target_speed = track * 50.0  # moving +Y, bomber on the line behind it
    engagement = _bomb_engagement(
        distance_m=800.0,  # behind, beyond lock distance -> stays in approach
        direction=np.array([0.0, 1.0, 0.0]),
        target_position=target_position,
        longitudinal=-30.0,
        target_speed=target_speed,
    )

    desired_direction, speed = nav.bomb_target(engagement)

    along = float(np.dot(nav.pawn.position - target_position, track))
    carrot = (
        target_position
        + track * (along + bomb["run_lookahead_m"])
        + up * bomb["run_altitude_m"]
    )
    expected_dir = carrot / np.linalg.norm(carrot)
    assert nav.behaviour == "bomb_approach"
    assert np.allclose(desired_direction, expected_dir, atol=1e-6)
    assert nav.up_reference is not None  # approach flies belly-down
    assert speed == pytest.approx(
        bomb["approach_speed_factor"] * nav.pawn.max_speed_mps
    )


def test_bomb_approach_lost_tail_falls_back_to_ingress():
    """
    If the target is no longer ahead along its track (tail lost), the belly-down
    approach drops back to the banking ingress to swing around and re-acquire it.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    _enter_behaviour(nav, "bomb_approach")
    # Target moving +Y but now BEHIND the bomber (it overshot ahead of the target):
    # to_target points -Y while the track is +Y -> not behind -> tail lost.
    target_position = np.array([0.0, -300.0, 0.0])
    target_speed = np.array([0.0, 50.0, 0.0])
    engagement = _bomb_engagement(
        distance_m=300.0,
        direction=np.array([0.0, -1.0, 0.0]),
        target_position=target_position,
        longitudinal=-30.0,
        target_speed=target_speed,
    )

    nav.bomb_target(engagement)

    assert nav.behaviour == "bomb_ingress"


def test_bomb_approach_locks_to_run_when_close():
    """
    When the target is within lock_time_s of flight (at the bomber's speed) the
    approach locks into the belly-down run and publishes the up-reference.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    _enter_behaviour(nav, "bomb_approach")
    # Bomber speed 100 m/s, lock_time_s 2 s -> lock within ~200 m.
    engagement = _bomb_engagement(
        distance_m=80.0,
        direction=np.array([0.0, 1.0, 0.0]),
        target_position=np.array([0.0, 80.0, 0.0]),
        longitudinal=-100.0,
        target_speed=np.array([0.0, 50.0, 0.0]),
    )

    nav.bomb_target(engagement)

    assert nav.behaviour == "bomb_run"
    assert nav.up_reference is not None  # belly aim published for the run


def test_bomb_run_releases_and_breaks():
    """
    In the run phase, once the release solution is met the bomb is dropped and
    the run breaks off.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    _enter_behaviour(nav, "bomb_run")
    direction = _bomb_velocity_dir(nav)
    target_position = direction * 100.0  # aligned, in range
    engagement = _bomb_engagement(
        distance_m=100.0,
        direction=direction,
        target_position=target_position,
        longitudinal=-55.0,  # closing (~ -dot; positive closing)
    )

    nav.bomb_target(engagement)

    assert nav.behaviour == "bomb_break"
    nav.pawn.fire_secondary.assert_called_once()


@pytest.mark.parametrize(
    "selected",
    [MagicMock(category="missile", stock=4), MagicMock(category="bomb", stock=0), None],
    ids=["missile", "spent bomb", "nothing"],
)
def test_bomb_run_does_not_release_without_a_bomb_selected(selected):
    """
    The bomb is the selected secondary weapon: with a missile selected instead,
    spent bombs, or nothing, the run releases nothing even on a perfect solution.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    nav.pawn.selected_secondary = selected
    _enter_behaviour(nav, "bomb_run")
    direction = _bomb_velocity_dir(nav)
    engagement = _bomb_engagement(
        distance_m=100.0,
        direction=direction,
        target_position=direction * 100.0,  # aligned, in range
        longitudinal=-55.0,
    )

    nav.bomb_target(engagement)

    nav.pawn.fire_secondary.assert_not_called()


def test_bomb_run_without_solution_holds_and_aims_belly():
    """
    While closing but not yet lined up, the run continues and publishes an
    up-reference so the pilot rolls the belly onto the target.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    _enter_behaviour(nav, "bomb_run")
    direction = np.array([0.0, 1.0, 0.0])  # target dead ahead -> no solution yet
    engagement = _bomb_engagement(
        distance_m=400.0,
        direction=direction,
        target_position=np.array([0.0, 400.0, 0.0]),
        longitudinal=-100.0,  # still closing
    )

    nav.bomb_target(engagement)

    assert nav.behaviour == "bomb_run"
    assert nav.up_reference is not None  # belly aim published
    nav.pawn.fire_secondary.assert_not_called()


def test_bomb_run_follows_track_line_and_publishes_up_reference():
    """
    The run follows the target's track line (carrot pure-pursuit at run altitude --
    above the diving line of sight to the target) and publishes the belly-aim
    up-reference so the fighter pilot flies belly-down.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    _enter_behaviour(nav, "bomb_run")
    bomb = nav.personality["navigator"]["bomb"]
    up = nav.game.scene.up_direction
    track = np.array([0.0, 1.0, 0.0])
    target_position = np.array([0.0, 500.0, 0.0])
    target_speed = track * 50.0
    engagement = _bomb_engagement(
        distance_m=500.0,  # beyond release range -> no drop, stays in the run
        direction=np.array([0.0, 1.0, 0.0]),
        target_position=target_position,
        longitudinal=-100.0,  # closing
        target_speed=target_speed,
    )

    desired_direction, _ = nav.bomb_target(engagement)

    along = float(np.dot(nav.pawn.position - target_position, track))
    carrot = (
        target_position
        + track * (along + bomb["run_lookahead_m"])
        + up * bomb["run_altitude_m"]
    )
    expected_dir = carrot / np.linalg.norm(carrot)
    assert np.allclose(desired_direction, expected_dir, atol=1e-6)
    assert desired_direction[2] > 0.0  # aims up toward the run altitude
    assert nav.up_reference is not None  # belly aim published for the run


# ---------------------------------------------------------------------------
# Weapon triggers between thinks
# ---------------------------------------------------------------------------


def _held_on_target(nav):
    """
    A target dead ahead in gun range. The geometry is given directly, so
    _resolve_engagement (which refreshes it from Interactions) is stubbed.
    """
    _augment_pawn_for_strafe(nav)
    target_dict = _strafe_target_dict(300.0)
    target_dict["target_id"] = "prey"
    nav._resolve_engagement = lambda target_dict: True
    return target_dict


def test_guns_fire_on_every_frame_between_thinks():
    """
    navigate() only runs when the bot thinks (every 6th frame here), but a gun
    reloads faster than that: the armed decision is taken on every frame, so the
    rate of fire is unchanged (the cannon's own reload gate still applies).
    """
    nav = make_fighter_navigator()
    target_dict = _held_on_target(nav)
    min_cos = nav.personality["navigator"]["fire"]["minimum_cos_angle"]

    for frame in range(12):
        if frame % 6 == 0:
            nav._arm_trigger(target_dict, weapon="guns", min_cos_angle=min_cos)
        else:
            nav.update_triggers(Intent.ENGAGE, target_dict)

    assert nav.pawn.laser_cannon.fire.call_count == 12


@pytest.mark.parametrize("change", ["new_target", "no_longer_engaging", "disarmed"])
def test_guns_hold_fire_once_the_decision_no_longer_applies(change):
    nav = make_fighter_navigator()
    target_dict = _held_on_target(nav)
    nav._arm_trigger(
        target_dict,
        weapon="guns",
        min_cos_angle=nav.personality["navigator"]["fire"]["minimum_cos_angle"],
    )
    nav.pawn.laser_cannon.fire.reset_mock()

    intent = Intent.ENGAGE
    if change == "new_target":
        target_dict = dict(target_dict, target_id="another_prey")
    elif change == "no_longer_engaging":
        intent = Intent.EVADE
    else:  # the next think chose not to attack
        nav.navigate_intent(intent=Intent.IDLE, target_dict={})
    nav.update_triggers(intent, target_dict)

    nav.pawn.laser_cannon.fire.assert_not_called()


def test_bomb_released_between_thinks_once_the_solution_is_met():
    """
    A bomb run armed at a think without a solution yet releases on the frame the
    solution is met, not up to a think period later, then breaks off, once.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_bomb(nav)
    nav._resolve_engagement = lambda target_dict: True
    _enter_behaviour(nav, "bomb_run")
    target_dict = _bomb_engagement(
        distance_m=400.0,
        direction=np.array([0.0, 1.0, 0.0]),
        target_position=np.array([0.0, 400.0, 0.0]),  # dead ahead: no solution
        longitudinal=-100.0,
    )
    target_dict["target_id"] = "prey"

    nav.bomb_target(target_dict)  # the think
    assert nav.behaviour == "bomb_run"
    nav.pawn.fire_secondary.assert_not_called()

    # A few frames later (fresh geometry): the target now lies on the bomb path
    direction = _bomb_velocity_dir(nav)
    target_dict.update(
        distance_m=100.0,
        direction=direction,
        target_current_position=direction * 100.0,
    )
    nav.update_triggers(Intent.ENGAGE, target_dict)
    nav.update_triggers(Intent.ENGAGE, target_dict)

    nav.pawn.fire_secondary.assert_called_once()
    assert nav.behaviour == "bomb_break"


def _secondary(category: str, stock: int = 4) -> SimpleNamespace:
    """A stand-in missile or rocket launcher: 300 m/s for 10 s."""
    return SimpleNamespace(
        category=category, stock=stock, speed_mps=300.0, conf={"life_time_s": 10.0}
    )


def _held_with(nav, weapon: str, launcher, locked: bool = True, in_flight: int = 0):
    """
    A primary target dead ahead at 300 m (see _held_on_target), to attack with
    this weapon and launcher, already selected. in_flight of our missiles
    already home on it.
    """
    target_dict = _held_on_target(nav)
    target_dict.update(weapon=weapon, launcher=launcher)
    nav.pawn.selected_secondary = launcher
    nav.pawn.is_missile_locked = locked
    missile = SimpleNamespace(pawn=SimpleNamespace(origin_ship=nav.pawn))
    ours = SimpleNamespace(controller=missile)
    target = SimpleNamespace(incoming_missiles=dict(enumerate([ours] * in_flight)))
    nav.game.interactions.get_actor_index_from_id.return_value = 0
    nav.game.interactions.actors = [target]
    return target_dict


@pytest.mark.parametrize("stock, selected", [(4, True), (0, False)])
def test_arming_selects_the_tacticians_secondary_weapon(stock, selected):
    """
    Arming a trigger selects the secondary weapon the tactician chose, while it
    has stock left.
    """
    nav = make_fighter_navigator()
    launcher = _secondary("missile", stock=stock)
    target_dict = _held_with(nav, "missile", launcher)

    nav._arm_trigger(target_dict, weapon="missile", min_cos_angle=0.99)

    if selected:
        nav.pawn.select_secondary.assert_called_once_with(launcher)
    else:
        nav.pawn.select_secondary.assert_not_called()


def test_locked_missile_is_launched_along_the_guns():
    """
    A missile locked on a target within reach is launched, the guns firing as
    well.
    """
    nav = make_fighter_navigator()
    target_dict = _held_with(nav, "missile", _secondary("missile"))

    nav._arm_trigger(target_dict, weapon="missile", min_cos_angle=0.99)

    nav.pawn.fire_secondary.assert_called_once()
    nav.pawn.laser_cannon.fire.assert_called_once()


@pytest.mark.parametrize(
    "change", ["not_locked", "out_of_reach", "one_in_flight", "spent", "not_selected"]
)
def test_missile_held_until_its_solution_is_met(change):
    """
    No missile without a lock, beyond the missile's reach, while one of ours
    already homes on the target, or without a missile with stock selected.
    """
    nav = make_fighter_navigator()
    launcher = _secondary("missile")
    target_dict = _held_with(
        nav,
        "missile",
        launcher,
        locked=change != "not_locked",
        in_flight=int(change == "one_in_flight"),
    )
    reach_m = launcher.speed_mps * launcher.conf["life_time_s"]
    fraction = nav.personality["navigator"]["ordnance"]["missile_max_range_fraction"]
    if change == "out_of_reach":
        target_dict["distance_m"] = 1.1 * fraction * reach_m
    elif change == "spent":
        launcher.stock = 0
    elif change == "not_selected":
        nav.pawn.selected_secondary = _secondary("rocket")

    nav._arm_trigger(target_dict, weapon="missile", min_cos_angle=0.99)

    nav.pawn.fire_secondary.assert_not_called()


def test_aligned_rocket_is_fired_along_the_guns():
    """
    A rocket is fired when its lead solution is dead ahead, the guns firing as
    well.
    """
    nav = make_fighter_navigator()
    target_dict = _held_with(nav, "rocket", _secondary("rocket"))

    nav._arm_trigger(target_dict, weapon="rocket", min_cos_angle=0.99)

    nav.pawn.fire_secondary.assert_called_once()
    nav.pawn.laser_cannon.fire.assert_called_once()


@pytest.mark.parametrize("change", ["off_cone", "out_of_range"])
def test_rocket_held_off_its_solution(change):
    """
    No rocket outside its (tight) cone or beyond gun range.
    """
    nav = make_fighter_navigator()
    target_dict = _held_with(nav, "rocket", _secondary("rocket"))
    if change == "off_cone":
        angle = np.deg2rad(4.0)  # the rocket cone is 3 deg
        nav.pawn.forward = np.array([np.sin(angle), np.cos(angle), 0.0])
    else:
        fire = nav.personality["navigator"]["fire"]
        distance_m = 1.1 * fire["maximum_distance_m"]
        target_dict.update(
            distance_m=distance_m,
            target_current_position=np.array([0.0, distance_m, 0.0]),
        )

    nav._arm_trigger(target_dict, weapon="rocket", min_cos_angle=0.99)

    nav.pawn.fire_secondary.assert_not_called()


@pytest.mark.parametrize("attack", ["pursue_target", "strafe_target"])
def test_pursuit_and_strafe_arm_the_tacticians_weapon(attack):
    """
    The pursuit and strafe runs arm the weapon the tactician chose.
    """
    nav = make_fighter_navigator()
    target_dict = _held_with(nav, "rocket", _secondary("rocket"))
    nav.check_overshoot_risk = MagicMock(return_value=False)
    nav.check_extend_conditions = MagicMock(return_value=False)

    getattr(nav, attack)(target_dict)

    assert nav._armed_trigger[0] == "rocket"


# ---------------------------------------------------------------------------
# Missile defense: beam turn and flares
# ---------------------------------------------------------------------------


def _under_fire(nav, *missiles):
    """
    The navigator's ship at the origin, flying +Y, with these (missile id,
    position) homing on it, closing in at 400 m/s, each with a 400 m decoy
    range. It carries flares.
    """
    nav.pawn.forward = np.array([0.0, 1.0, 0.0])
    nav.pawn.right = np.array([1.0, 0.0, 0.0])
    nav.pawn.flare_launcher = SimpleNamespace(stock=10)
    nav.pawn.drop_flare.return_value = True
    nav.pawn.incoming_missiles = {
        missile_id: IncomingMissile(
            controller=SimpleNamespace(
                id=missile_id, pawn=SimpleNamespace(conf={"decoy_range_m": 400.0})
            ),
            position=np.array(position, dtype=float),
            distance_m=float(np.linalg.norm(position)),
            closing_speed_mps=400.0,
        )
        for missile_id, position in missiles
    }


@pytest.mark.parametrize(
    "missile_position, expected",
    [
        # From behind-left: the perpendicular closest to the heading (+Y)
        ([-300.0, -400.0, 0.0], [-0.8, 0.6, 0.0]),
        # Dead astern: straight along the line of sight, break right
        ([0.0, -500.0, 0.0], [1.0, 0.0, 0.0]),
    ],
)
def test_defend_missile_beams_the_missile(missile_position, expected):
    """
    The ship turns perpendicular to the missile's line of sight, on the side
    of its heading, at full speed.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("m", missile_position))

    direction, speed_mps = nav.navigate_intent(
        intent=Intent.DEFEND_MISSILE, target_dict={"target_id": "m"}
    )

    line_of_sight = -np.asarray(missile_position) / np.linalg.norm(missile_position)
    assert np.dot(direction, line_of_sight) == pytest.approx(0.0, abs=1e-9)
    np.testing.assert_allclose(direction, expected, atol=1e-9)
    assert speed_mps == nav.pawn.max_speed_mps


def test_defend_missile_turns_to_the_next_missile_once_it_is_gone():
    """
    The missile the tactician picked is gone (decoyed, spent): defend against
    the nearest one left, or fly on if there is none.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("other", [500.0, 0.0, 0.0]))

    direction, _ = nav.defend_missile({"target_id": "gone"})
    assert np.dot(direction, [1.0, 0.0, 0.0]) == pytest.approx(0.0, abs=1e-9)

    nav.pawn.incoming_missiles = {}
    assert nav.defend_missile({"target_id": "gone"}) == NO_DIRECTION


@pytest.mark.parametrize(
    "distance_m, dropped",
    [(500.0, False), (330.0, False), (310.0, True), (50.0, True)],
)
def test_flare_dropped_within_reach_of_its_lure(distance_m, dropped):
    """
    Defending against a missile, a flare is dropped once it is within the
    configured fraction (0.8) of its decoy range (400 m), so 320 m.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("m", [0.0, -distance_m, 0.0]))

    nav.navigate_intent(intent=Intent.DEFEND_MISSILE, target_dict={"target_id": "m"})

    assert nav.pawn.drop_flare.called is dropped


def test_no_flare_unless_defending_against_the_missile():
    """
    Flares are only dropped while defending against a missile.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("m", [0.0, -100.0, 0.0]))

    nav.navigate_intent(intent=Intent.IDLE, target_dict={})

    nav.pawn.drop_flare.assert_not_called()


def test_one_flare_per_missile():
    """
    One flare per missile, then one against the next missile defended against.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("first", [0.0, -100.0, 0.0]))

    for _ in range(5):
        nav.defend_missile({"target_id": "first"})
    assert nav.pawn.drop_flare.call_count == 1

    _under_fire(nav, ("first", [0.0, -100.0, 0.0]), ("second", [0.0, -50.0, 0.0]))
    nav.defend_missile({"target_id": "second"})
    assert nav.pawn.drop_flare.call_count == 2


def test_flare_retried_when_the_drop_is_refused():
    """
    A refused drop (reloading) is retried at the next think.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("m", [0.0, -100.0, 0.0]))
    nav.pawn.drop_flare.return_value = False

    nav.defend_missile({"target_id": "m"})
    nav.pawn.drop_flare.return_value = True
    nav.defend_missile({"target_id": "m"})
    nav.defend_missile({"target_id": "m"})

    assert nav.pawn.drop_flare.call_count == 2


def test_flared_missiles_are_forgotten_once_gone():
    """
    The flared missiles no longer homing on the ship are forgotten.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("m", [0.0, -100.0, 0.0]))
    nav.defend_missile({"target_id": "m"})

    _under_fire(nav, ("other", [0.0, -900.0, 0.0]))
    nav.defend_missile({"target_id": "other"})

    assert nav._flared_missile_ids == set()


@pytest.mark.parametrize("flare_launcher", [None, SimpleNamespace(stock=0)])
def test_no_flare_without_flares(flare_launcher):
    """
    Without flares (none carried, or all spent), nothing is dropped: the beam
    turn goes on.
    """
    nav = make_fighter_navigator()
    _under_fire(nav, ("m", [0.0, -100.0, 0.0]))
    nav.pawn.flare_launcher = flare_launcher

    direction, _ = nav.defend_missile({"target_id": "m"})

    nav.pawn.drop_flare.assert_not_called()
    assert np.linalg.norm(direction) == pytest.approx(1.0)


def test_time_in_spiral_accrues_the_time_between_thinks():
    """Checked every 0.1 s instead of every frame, a spiral lasts as long."""
    extend = Personality.FIGHTER_DEFAULT["navigator"]["extend"]
    in_spiral = dict(
        longitudinal_speed_scalar_mps=0.0,
        lateral_speed_scalar_mps=2.0 * extend["maximum_lateral_speed_mps"] + 1.0,
    )
    per_frame, per_think = make_fighter_navigator(), make_fighter_navigator()
    per_frame.think_dt_s = 1.0 / 60.0
    per_think.think_dt_s = 0.1
    for _ in range(60):
        per_frame.check_extend_conditions(**in_spiral)
    for _ in range(10):
        per_think.check_extend_conditions(**in_spiral)
    assert per_think.time_in_spiral_s == pytest.approx(per_frame.time_in_spiral_s)
    assert per_think.time_in_spiral_s == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Pursuit speed floor
# ---------------------------------------------------------------------------


def test_pursuit_repositions_no_slower_than_the_speed_floor():
    """
    About to overshoot, a pursuit repositions; the pursuit's speed floor (a
    fraction of max_speed_mps) still applies over the slow turning speed.
    """
    nav = make_fighter_navigator()
    _augment_pawn_for_strafe(nav)
    nav._resolve_engagement = lambda target_dict: True
    target_dict = _strafe_target_dict(100.0)
    target_dict.update(target_id="prey", longitudinal_speed_scalar_mps=-1000.0)
    attack = nav.personality["navigator"]["attack"]

    _, speed = nav.navigate(intent=Intent.ENGAGE, target_dict=target_dict)

    assert nav.behaviour == "reposition"
    floor_mps = attack["minimum_speed_factor"] * nav.pawn.max_speed_mps
    assert nav.minimum_speed_mps == pytest.approx(floor_mps)
    assert speed == pytest.approx(floor_mps)
    assert speed > nav.personality["navigator"]["turning"]["speed_mps"]
