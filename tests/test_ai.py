"""
Unit tests for the space_flight.ai module-level constants and enumerations.
"""

import numpy as np
import pytest

from space_flight.ai import (
    HALF_PI,
    INTERACT_MAX_DISTANCE_M,
    REFERENCE_ERROR_VELOCITY_MPS,
    ROLL_TOLERANCE,
    TARGET_DISTANCE_TOLERANCE_M,
    Intent,
    Personality,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_half_pi_matches_numpy():
    """
    HALF_PI must equal the standard numpy half-pi constant.
    """
    assert HALF_PI == pytest.approx(np.pi / 2)


def test_target_distance_tolerance_is_positive():
    """
    TARGET_DISTANCE_TOLERANCE_M must be a positive threshold.
    """
    assert TARGET_DISTANCE_TOLERANCE_M > 0


def test_interact_max_distance_is_positive():
    """
    INTERACT_MAX_DISTANCE_M must be positive and large enough to span
    a meaningful combat space.
    """
    assert INTERACT_MAX_DISTANCE_M > 0


def test_reference_error_velocity_is_positive():
    """
    REFERENCE_ERROR_VELOCITY_MPS must be positive so it can be used as a
    normalisation denominator without a divide-by-zero.
    """
    assert REFERENCE_ERROR_VELOCITY_MPS > 0


def test_roll_tolerance_is_small_and_positive():
    """
    ROLL_TOLERANCE must be a small positive value so that roll corrections are
    only suppressed when both yaw and pitch errors are truly negligible.
    """
    assert 0 < ROLL_TOLERANCE < 1


# ---------------------------------------------------------------------------
# Intent enum
# ---------------------------------------------------------------------------


def test_intent_contains_all_expected_members():
    """
    The Intent enum must expose exactly the seven expected combat-state labels.
    """
    expected_names = {
        "ENGAGE",
        "EVADE",
        "DISENGAGE",
        "REGROUP",
        "PATROL",
        "FORMATION",
        "IDLE",
    }

    assert {member.name for member in Intent} == expected_names


def test_intent_member_values_are_unique():
    """
    Each Intent member must have a distinct auto() value.
    """
    values = [member.value for member in Intent]

    assert len(values) == len(set(values))


def test_intent_engage_is_different_from_idle():
    """
    ENGAGE and IDLE must be distinct enum members.
    """
    assert Intent.ENGAGE != Intent.IDLE


# ---------------------------------------------------------------------------
# Personality dicts — structural checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "personality_dict",
    [
        Personality.FIGHTER_DEFAULT,
        Personality.TURRET_DEFAULT,
        Personality.CAPITAL_SHIP_DEFAULT,
    ],
    ids=["fighter", "turret", "capital_ship"],
)
def test_personality_has_all_three_sub_dicts(personality_dict):
    """
    Every predefined personality dict must contain 'pilot', 'navigator', and
    'tactician' sub-dicts.
    """
    for key in ("pilot", "navigator", "tactician"):
        assert key in personality_dict


def test_fighter_personality_pilot_has_pid_gains():
    """
    The fighter pilot sub-dict must contain PID gain keys for all four
    controlled axes (yaw, pitch, roll, throttle).
    """
    pilot = Personality.FIGHTER_DEFAULT["pilot"]

    for gain in ("yaw_kp", "pitch_kp", "roll_kp", "throttle_kp"):
        assert gain in pilot


def test_fighter_personality_tactician_has_commitment_times():
    """
    The fighter tactician sub-dict must contain a 'commitment_times' entry
    keyed by Intent members.
    """
    commitment_times = Personality.FIGHTER_DEFAULT["tactician"]["commitment_times"]

    for intent in Intent:
        if intent in commitment_times:
            assert commitment_times[intent] > 0


def test_turret_personality_tactician_has_intent_update_delay():
    """
    The turret tactician sub-dict must specify an intent_update_delay.
    """
    assert "intent_update_delay" in Personality.TURRET_DEFAULT["tactician"]


def test_capital_ship_personality_pilot_has_throttle_gains():
    """
    The capital ship pilot sub-dict must include throttle PID gains.
    """
    pilot = Personality.CAPITAL_SHIP_DEFAULT["pilot"]

    assert "throttle_kp" in pilot
    assert "throttle_ki" in pilot
