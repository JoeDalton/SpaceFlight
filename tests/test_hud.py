"""
Unit tests for the HUD (space_flight.ui.hud): the screen projection, the target
box tint while a missile is locked, the aiming cues (crosshair and lead
indicator), the ordnance HUD (secondary weapons drum and flares left) and the
energy gauges.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from panda3d.core import NodePath, PerspectiveLens, Point3, Vec3

from space_flight.actors.energy import ENGINES, LASERS, SHIELDS, EnergySystem
from space_flight.ui.hud import (
    CROSSHAIR_COLOR,
    CROSSHAIR_LOCKED_COLOR,
    FAVOURED_GAUGE_BRIGHTNESS,
    GAUGE_BRIGHTNESS,
    MIN_PROJECTION_DEPTH,
    TARGET_BOX_COLOR,
    TARGET_BOX_MISSILE_LOCKED_COLOR,
    AimHUD,
    EnergyHUD,
    OrdnanceHUD,
    gauge_brightness,
    is_on_screen,
    project_to_screen,
)

# ---------------------------
# screen projection
# ---------------------------


def test_project_to_screen_centre_ahead():
    """A point straight ahead projects to the screen centre, not behind."""
    x, z, behind = project_to_screen(PerspectiveLens(), Point3(0, 100, 0))

    assert (x, z) == pytest.approx((0.0, 0.0))
    assert behind is False


def test_project_to_screen_flags_points_behind():
    """A point behind the camera is flagged, its projection mirrored."""
    x, _, behind = project_to_screen(PerspectiveLens(), Point3(10, -100, 0))

    assert behind is True
    assert x < 0.0  # mirrored through the centre: true bearing is to the right


def test_project_to_screen_clamps_a_null_depth():
    """A point in the camera's XZ plane gets a non-zero depth: finite result."""
    cam_space_pos = Point3(1, 0, 0)

    x, z, behind = project_to_screen(PerspectiveLens(), cam_space_pos)

    assert cam_space_pos.y == pytest.approx(MIN_PROJECTION_DEPTH)
    assert np.isfinite(x) and np.isfinite(z)
    assert behind is False


@pytest.mark.parametrize(
    "x, z, behind, expected",
    [
        (0.0, 0.0, False, True),
        (1.0, -1.0, False, True),  # on the border
        (1.2, 0.0, False, False),
        (0.0, -1.2, False, False),
        (0.0, 0.0, True, False),  # behind the camera
    ],
)
def test_is_on_screen(x, z, behind, expected):
    """On screen means ahead of the camera and inside [-1, 1] on both axes."""
    assert is_on_screen(x, z, behind) is expected


# ---------------------------
# AimHUD: target box, crosshair, lead indicator
# ---------------------------


def make_aim_hud() -> AimHUD:
    """
    An AimHUD bypassing __init__, its cards and labels mocked. The camera sits at the
    world origin looking down +Y (camera space = world space), through a real
    lens. The player has a live target ahead, its predicted position straight
    ahead.
    """
    aim_hud = object.__new__(AimHUD)
    aim_hud.game = MagicMock()
    aim_hud.show_lead_indicator = True
    app = aim_hud.game.app
    app.camLens = PerspectiveLens()
    app.cam.getRelativeVector.side_effect = lambda _, vector: Vec3(vector)
    app.cam.getRelativePoint.side_effect = lambda _, point: Point3(point)
    pawn = aim_hud.game.player.pawn
    pawn.forward = np.array([0.0, 1.0, 0.0])
    pawn.auto_aim.is_target_acquired = False
    pawn.target.is_dead = False
    pawn.auto_aim.predict_target_position.return_value = np.array([0.0, 100.0, 0.0])
    for node in (
        "target_anchor",
        "target_aspect",
        "square",
        "scan_bar",
        "name_label",
        "distance_label",
        "crosshair",
        "lead_indicator",
    ):
        setattr(aim_hud, node, MagicMock())
    return aim_hud


@pytest.mark.parametrize("auto_aim_locked", [True, False])
@pytest.mark.parametrize(
    "missile_locked, color",
    [(True, TARGET_BOX_MISSILE_LOCKED_COLOR), (False, TARGET_BOX_COLOR)],
)
def test_target_box_is_red_only_while_missile_locked(
    missile_locked, color, auto_aim_locked
):
    """
    The target box turns red while the armed missile is locked, white
    otherwise, whatever the laser auto-aim lock.
    """
    aim_hud = make_aim_hud()
    aim_hud.game.player.pawn.is_missile_locked = missile_locked
    aim_hud.game.player.pawn.auto_aim.is_target_acquired = auto_aim_locked

    aim_hud.update_lock_tint()

    aim_hud.square.setColorScale.assert_called_once_with(*color)


@pytest.mark.parametrize("dead", [False, True])
def test_target_box_is_hidden_and_target_dropped_without_a_live_target(dead):
    """
    Without a target, or with a target that has just died, the target box is
    hidden and the player's target is dropped.
    """
    aim_hud = make_aim_hud()
    pawn = aim_hud.game.player.pawn
    if dead:
        pawn.target.is_dead = True
    else:
        pawn.target = None

    aim_hud.update_target_box()

    aim_hud.target_anchor.hide.assert_called_once()
    aim_hud.target_anchor.show.assert_not_called()
    assert (pawn.target, pawn.target_id, pawn.target_idx) == (None, None, None)


def test_target_box_sits_on_a_target_ahead():
    """A target ahead is boxed where it projects, labelled with its distance."""
    aim_hud = make_aim_hud()
    pawn = aim_hud.game.player.pawn
    pawn.target.position = np.array([0.0, 250.0, 0.0])
    pawn.target.scan = None
    aim_hud.game.app.camera.getPos.return_value = Point3(0, 0, 0)

    aim_hud.update_target_box()

    aim_hud.target_anchor.show.assert_called_once()
    x, _, z = aim_hud.target_anchor.setPos.call_args.args
    assert (x, z) == pytest.approx((0.0, 0.0))
    aim_hud.distance_label.__setitem__.assert_called_once_with("text", "250 m")


@pytest.mark.parametrize(
    "locked, color", [(True, CROSSHAIR_LOCKED_COLOR), (False, CROSSHAIR_COLOR)]
)
def test_crosshair_sits_on_the_nose_red_while_auto_aim_locked(locked, color):
    """
    The crosshair sits where the nose points (the centre, when looking ahead),
    red while auto-aim is locked, white otherwise.
    """
    aim_hud = make_aim_hud()
    aim_hud.game.player.pawn.auto_aim.is_target_acquired = locked

    aim_hud.update_crosshair()

    x, _, z = aim_hud.crosshair.setPos.call_args.args
    assert (x, z) == pytest.approx((0.0, 0.0))
    aim_hud.crosshair.setColorScale.assert_called_once_with(*color)
    aim_hud.crosshair.show.assert_called_once()


def test_crosshair_follows_the_nose_off_centre():
    """
    With the nose away from the camera axis (head turned or jolted), the
    crosshair leaves the centre, toward the nose.
    """
    aim_hud = make_aim_hud()
    aim_hud.game.player.pawn.forward = np.array([0.1, 1.0, 0.0])

    aim_hud.update_crosshair()

    x, _, z = aim_hud.crosshair.setPos.call_args.args
    assert x > 0.0
    assert z == pytest.approx(0.0)


@pytest.mark.parametrize(
    "forward", [np.array([0.0, -1.0, 0.0]), np.array([1.0, 0.1, 0.0])]
)
def test_crosshair_is_hidden_when_the_nose_is_off_screen(forward):
    """Looking far away from the nose (behind or aside) hides the crosshair."""
    aim_hud = make_aim_hud()
    aim_hud.game.player.pawn.forward = forward

    aim_hud.update_crosshair()

    aim_hud.crosshair.hide.assert_called_once()
    aim_hud.crosshair.show.assert_not_called()


def test_lead_indicator_shows_the_projected_prediction():
    """
    With a live target whose prediction is ahead and on screen, the lead
    indicator is shown at its projection.
    """
    aim_hud = make_aim_hud()
    aim_hud.game.player.pawn.auto_aim.predict_target_position.return_value = np.array(
        [5.0, 100.0, -3.0]
    )

    aim_hud.update_lead_indicator()

    x, _, z = aim_hud.lead_indicator.setPos.call_args.args
    assert x > 0.0 and z < 0.0
    aim_hud.lead_indicator.show.assert_called_once()


def test_disabled_lead_indicator_is_never_shown():
    """
    With the lead indicator disabled in the gameplay settings, it is never
    shown, even with a live target on screen.
    """
    aim_hud = make_aim_hud()
    aim_hud.show_lead_indicator = False

    aim_hud.update_lead_indicator()

    aim_hud.lead_indicator.show.assert_not_called()
    aim_hud.game.player.pawn.auto_aim.predict_target_position.assert_not_called()


@pytest.mark.parametrize("enabled", [True, False])
def test_aim_hud_reads_the_lead_indicator_setting(enabled):
    """The AimHUD reads whether to show the lead indicator once, when built."""
    game = MagicMock()
    game.app.gameplay_settings.config = {"player": {"lead_indicator": enabled}}

    with (
        # A distinct card each, to tell which one is hidden
        patch("space_flight.ui.hud.make_hud_card", side_effect=lambda *_: MagicMock()),
        patch("space_flight.ui.hud.DirectLabel"),
    ):
        aim_hud = AimHUD(game=game)

    assert aim_hud.show_lead_indicator is enabled
    aim_hud.lead_indicator.hide.assert_called_once()  # Hidden at startup


def _no_target(pawn):
    pawn.target = None


def _no_prediction(pawn):
    pawn.auto_aim.predict_target_position.return_value = None


def _prediction_behind(pawn):
    pawn.auto_aim.predict_target_position.return_value = np.array([0.0, -100.0, 0])


def _prediction_off_screen(pawn):
    pawn.auto_aim.predict_target_position.return_value = np.array([500.0, 100.0, 0])


@pytest.mark.parametrize(
    "setup",
    [
        _no_target,
        _no_prediction,
        _prediction_behind,
        _prediction_off_screen,
    ],
)
def test_lead_indicator_is_hidden(setup):
    """
    The lead indicator is hidden without a target, without a prediction, or
    when the prediction is behind the camera or off screen.
    """
    aim_hud = make_aim_hud()
    setup(aim_hud.game.player.pawn)

    aim_hud.update_lead_indicator()

    aim_hud.lead_indicator.hide.assert_called_once()
    aim_hud.lead_indicator.show.assert_not_called()


def test_lead_indicator_is_hidden_on_a_dead_target():
    """
    A target that has just died is dropped by the target box, updated first,
    so the lead indicator is hidden.
    """
    aim_hud = make_aim_hud()
    aim_hud.game.player.pawn.target.is_dead = True

    aim_hud.aim_hud_update_task()

    aim_hud.lead_indicator.hide.assert_called_once()
    aim_hud.lead_indicator.show.assert_not_called()


def test_aim_hud_clean_unregisters_its_update_task():
    """clean() removes the update task, the labels and the cards, and drops
    the game."""
    aim_hud = make_aim_hud()
    aim_hud.id = "aim"
    game = aim_hud.game
    game.method_lists = {"aim": [aim_hud.aim_hud_update_task]}
    aim_hud.root = MagicMock()

    aim_hud.clean()

    assert "aim" not in game.method_lists
    aim_hud.root.removeNode.assert_called_once()
    aim_hud.name_label.destroy.assert_called_once()
    aim_hud.distance_label.destroy.assert_called_once()
    assert aim_hud.game is None


# ---------------------------
# ordnance
# ---------------------------


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


# ---------------------------
# Energy HUD
# ---------------------------


def make_energy_hud(has_shields: bool = True) -> tuple[EnergyHUD, SimpleNamespace]:
    """An energy HUD on a fake player pawn, with that pawn."""
    pawn = SimpleNamespace(
        health=600.0,
        max_health=1200.0,
        shield=200.0,
        max_shield=800.0 if has_shields else 0.0,
        speed=np.array([0.0, 120.4, 0.0]),
        energy=EnergySystem(has_shields=has_shields, laser_shot_energy_cost=0.02),
    )
    game = SimpleNamespace(player=SimpleNamespace(pawn=pawn))
    return EnergyHUD(game=game, parent_node=NodePath("corner")), pawn


def test_energy_hud_is_hidden_until_its_first_update():
    """
    Like the rest of the HUD, the gauges show nothing before the game runs
    (e.g. during the hyperspace loading state).
    """
    energy_hud, _ = make_energy_hud()
    assert energy_hud.root.isHidden()

    energy_hud.update()

    assert not energy_hud.root.isHidden()


def test_energy_hud_shows_hp_speed_and_shield():
    """
    The half-ring gauges show the health left, the speed and the shield
    strength, filled to their share of the maximum.
    """
    energy_hud, pawn = make_energy_hud()
    pawn.energy.engines = 0.5
    pawn.energy.lasers = 0.25

    energy_hud.update()

    assert energy_hud.hp_gauge.text.node().getText() == "600"
    assert energy_hud.hp_gauge.fill_steps == energy_hud.hp_gauge.n_segments // 2
    assert energy_hud.engine_gauge.text.node().getText() == "120 m/s"
    assert energy_hud.engine_gauge.fill_steps == energy_hud.engine_gauge.n_segments // 2
    assert energy_hud.shield_gauge.text.node().getText() == "200"
    assert energy_hud.shield_gauge.fill_steps == energy_hud.shield_gauge.n_segments // 4
    assert energy_hud.laser_gauge.level == pytest.approx(0.25)


def test_energy_hud_hides_the_shield_gauge_without_shields():
    """
    An unshielded ship (a TIE) has no shield gauge, and updating does not trip
    over its zero max shield.
    """
    energy_hud, _ = make_energy_hud(has_shields=False)

    energy_hud.update()

    assert energy_hud.shield_gauge.root.isHidden()
    assert not energy_hud.engine_gauge.root.isHidden()


def test_energy_hud_clamps_negative_health():
    """
    A dead ship's negative health reads as 0.
    """
    energy_hud, pawn = make_energy_hud()
    pawn.health = -35.0

    energy_hud.update()

    assert energy_hud.hp_gauge.text.node().getText() == "0"
    assert energy_hud.hp_gauge.fill_steps == 0


@pytest.mark.parametrize("favoured", [ENGINES, LASERS, SHIELDS])
def test_favoured_system_gauge_is_brighter(favoured):
    """
    The gauge of the system power is redirected to is brighter than the others.
    """
    energy_hud, pawn = make_energy_hud()
    pawn.energy.set_mode(favoured)

    energy_hud.update()

    gauges = {
        ENGINES: energy_hud.engine_gauge,
        LASERS: energy_hud.laser_gauge,
        SHIELDS: energy_hud.shield_gauge,
    }
    for system, gauge in gauges.items():
        expected = FAVOURED_GAUGE_BRIGHTNESS if system == favoured else GAUGE_BRIGHTNESS
        assert gauge.brightness == expected


def test_balanced_power_brightens_no_gauge():
    """
    With balanced power, every gauge has the normal brightness.
    """
    energy = EnergySystem(has_shields=True, laser_shot_energy_cost=0.02)
    for system in (ENGINES, LASERS, SHIELDS):
        assert gauge_brightness(energy, system) == GAUGE_BRIGHTNESS
