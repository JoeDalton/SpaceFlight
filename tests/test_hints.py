"""
Unit tests for the levels' shared tutorial hints (space_flight.game.levels.hints).
"""

from types import SimpleNamespace

import pytest

from space_flight.actors.energy import ENGINES, LASERS
from space_flight.game.levels.hints import (
    engine_power_hint,
    formation_hint,
    laser_power_hint,
    power_hint,
    scan_hint,
    stay_close_hint,
    subsystem_hint,
    target_menu_hint,
    waypoint_hint,
)

BINDINGS = {
    "contexts": {
        "flight": {
            "keyboard": {
                "energy_engines": "1",
                "energy_lasers": "2",
                "radial_menu": "r",
                "loop_target": ",",
            },
            "gamepad": {"cycle_energy": "gamepad_face_y"},
        }
    }
}


def app_on(device: str) -> SimpleNamespace:
    return SimpleNamespace(
        bindings=BINDINGS, input_reader=SimpleNamespace(last_device=device)
    )


@pytest.mark.parametrize("system, key", [(ENGINES, "1"), (LASERS, "2")])
def test_keyboard_names_the_direct_key(system, key):
    assert power_hint(app_on("keyboard"), system) == (
        f"Press [{key}] to divert power to your {system}."
    )


def test_a_device_without_direct_keys_names_the_cycling_one():
    assert power_hint(app_on("gamepad"), ENGINES) == (
        "Press [GAMEPAD_FACE_Y] to cycle power until your engines gauge brightens."
    )


def test_no_binding_at_all_falls_back_to_words():
    assert "the power-cycling key" in power_hint(app_on("joystick"), LASERS)


def test_target_menu_hint_names_both_keys():
    assert target_menu_hint(app_on("keyboard"), "Fighters", "lock one") == (
        "Hold [R] to open the target menu, point at Fighters, then press [,] "
        "to lock one."
    )


def test_target_menu_hint_falls_back_to_words():
    hint = target_menu_hint(app_on("gamepad"), "Fighters", "lock one")
    assert "[the target-menu key]" in hint and "[the cycle-target key]" in hint


@pytest.mark.parametrize(
    "hint, filter_name",
    [
        (waypoint_hint, "Waypoints"),
        (formation_hint, "Fighters"),
        (scan_hint, "Capital ships"),
        (lambda app: subsystem_hint(app, "target them"), "Subsystems"),
    ],
)
def test_targeting_hints_point_at_their_filter(hint, filter_name):
    text = hint(app_on("keyboard"))
    assert f"point at {filter_name}" in text and "[R]" in text


def test_scan_hint_quotes_the_scan_rules():
    assert "Close to 1000m" in scan_hint(app_on("keyboard"))
    assert "15 seconds" in scan_hint(app_on("keyboard"))


def test_stay_close_hint():
    assert stay_close_hint(300, "Blue squadron") == (
        "Stay within 300m of any Blue squadron ship."
    )


def test_power_hints_for_a_reason():
    assert engine_power_hint(app_on("keyboard")).startswith("Press [1]")
    assert laser_power_hint(app_on("keyboard")).startswith("Press [2]")
