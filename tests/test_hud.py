"""
Unit tests for the HUD's ordnance cues (space_flight.ui.hud): the target box
tint while auto-aim is locked, and the selected secondary weapon's name.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from space_flight.ui.hud import (
    HUD,
    TARGET_BOX_COLOR,
    TARGET_BOX_LOCKED_COLOR,
    TargetHUD,
)


def make_target_hud(locked: bool) -> TargetHUD:
    """A TargetHUD bypassing __init__, its player's auto-aim lock as given."""
    target_hud = object.__new__(TargetHUD)
    target_hud.game = MagicMock()
    target_hud.game.player.pawn.auto_aim.is_target_acquired = locked
    target_hud.square = MagicMock()
    return target_hud


@pytest.mark.parametrize(
    "locked, color", [(True, TARGET_BOX_LOCKED_COLOR), (False, TARGET_BOX_COLOR)]
)
def test_target_box_is_red_while_locked(locked, color):
    """
    The target box turns red while auto-aim is locked, white otherwise.
    """
    target_hud = make_target_hud(locked)

    target_hud.update_lock_tint()

    target_hud.square.setColorScale.assert_called_once_with(*color)


def make_hud(selected_secondary) -> HUD:
    """A HUD bypassing __init__, its player's selected secondary as given."""
    hud = object.__new__(HUD)
    hud.game = MagicMock()
    hud.game.player.pawn.selected_secondary = selected_secondary
    hud.secondary = MagicMock()
    return hud


def test_secondary_label_shows_the_selected_weapon():
    """
    The label shows the selected secondary weapon's name.
    """
    hud = make_hud(SimpleNamespace(display_name="PROTON TORPEDO"))

    hud.update_secondary_hud()

    hud.secondary.setText.assert_called_once_with("PROTON TORPEDO")


def test_secondary_label_is_empty_without_secondary():
    """
    Without a secondary weapon (none carried, or all spent), the label is empty.
    """
    hud = make_hud(None)

    hud.update_secondary_hud()

    hud.secondary.setText.assert_called_once_with("")
