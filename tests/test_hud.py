"""
Unit tests for the HUD's ordnance cues (space_flight.ui.hud): the target box
tint while auto-aim is locked, and the ordnance HUD (secondary weapons drum and
flares left).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from panda3d.core import NodePath

from space_flight.ui.hud import (
    TARGET_BOX_COLOR,
    TARGET_BOX_LOCKED_COLOR,
    OrdnanceHUD,
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


class FakeClock:
    def __init__(self):
        self.time_s = 0.0

    def get_current_time(self) -> float:
        return self.time_s


class FakePawn:
    """A fighter's ordnance, as the ordnance HUD reads it."""

    def __init__(self, launchers, flare_launcher=None):
        self.launchers = list(launchers)
        self.selected_secondary = self.launchers[0] if self.launchers else None
        self.flare_launcher = flare_launcher

    def secondary_cycle(self):
        return list(self.launchers)

    def cycle_secondary(self, step: int = 1):
        cycle = self.secondary_cycle()
        index = cycle.index(self.selected_secondary)
        self.selected_secondary = cycle[(index + step) % len(cycle)]


def launcher(name: str, stock: int = 4) -> SimpleNamespace:
    return SimpleNamespace(display_name=name, stock=stock)


def make_ordnance_hud(pawn: FakePawn) -> OrdnanceHUD:
    game = SimpleNamespace(game_time=FakeClock(), player=SimpleNamespace(pawn=pawn))
    return OrdnanceHUD(game=game, parent_node=NodePath("corner"))


def drum_texts(ordnance_hud: OrdnanceHUD) -> dict:
    """The visible drum lines' text, by slot offset from the selection."""
    return {
        offset: line.node().getText()
        for offset, line in ordnance_hud.drum.slots.items()
    }


def test_drum_shows_the_secondary_weapons_with_their_stock():
    """
    The secondary weapons are on the drum, the selected one in the middle,
    each with the number left.
    """
    pawn = FakePawn([launcher("A", 1), launcher("B", 2), launcher("C", 3)])
    ordnance_hud = make_ordnance_hud(pawn)

    ordnance_hud.update()

    assert drum_texts(ordnance_hud) == {-1: "C 3", 0: "A 1", 1: "B 2"}


def test_spent_secondary_weapons_keep_their_line():
    """
    A spent secondary weapon stays on the drum, at x0.
    """
    pawn = FakePawn([launcher("A", 0), launcher("B", 2)])
    ordnance_hud = make_ordnance_hud(pawn)

    ordnance_hud.update()

    assert drum_texts(ordnance_hud)[0] == "A 0"


def test_drum_rolls_when_the_selection_changes():
    """
    Cycling the secondary weapon rolls the drum.
    """
    pawn = FakePawn([launcher("A"), launcher("B"), launcher("C")])
    ordnance_hud = make_ordnance_hud(pawn)
    ordnance_hud.update()

    pawn.cycle_secondary()
    ordnance_hud.update()

    assert ordnance_hud.drum.roll_rad() > 0.0


@pytest.mark.parametrize(
    "flare_launcher, text", [(launcher("FLARE", 7), "FLARE 7"), (None, "FLARE 0")]
)
def test_flare_line_always_shows_the_flares_left(flare_launcher, text):
    """
    The flares line is always shown, in the secondary weapons' format, even
    for a ship without flares.
    """
    ordnance_hud = make_ordnance_hud(FakePawn([], flare_launcher=flare_launcher))

    ordnance_hud.update()

    assert ordnance_hud.flare_line.node().getText() == text
    assert not ordnance_hud.flare_line.isHidden()
