"""
Unit tests for the levels' shared tutorial hints (space_flight.game.levels.hints).
"""

from types import SimpleNamespace

import pytest

from space_flight.actors.energy import ENGINES, LASERS
from space_flight.game.levels.hints import power_hint

BINDINGS = {
    "contexts": {
        "flight": {
            "keyboard": {"energy_engines": "1", "energy_lasers": "2"},
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
