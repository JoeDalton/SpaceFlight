from unittest.mock import MagicMock

import pytest

from space_flight.actors.fighter import Fighter


def make_fighter_without_init(
    max_health: float = 200.0,
    current_health: float = 200.0,
    max_shield: float = 100.0,
    current_shield: float = 100.0,
    shield_regen_rate: float = 10.0,
):
    """
    Build a Fighter instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    fighter = object.__new__(Fighter)
    fighter.max_health = max_health
    fighter.health = current_health
    fighter.max_shield = max_shield
    fighter.shield = current_shield
    fighter.shield_regen_rate = shield_regen_rate
    # apply_damage reads is_dying -- a property mirroring the controlling
    # Bot/Player -- to make a dying wreck inert; give it a live controller.
    fighter.parent = MagicMock(is_dying=False)
    return fighter


# ---------------------------
# apply_damage
# ---------------------------


def test_apply_damage_physical_reduces_shield_first():
    """
    Physical damage is absorbed by the shield before touching health.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=100.0)

    fighter.apply_damage(damage=40.0, damage_type="physical")

    assert fighter.shield == pytest.approx(60.0)
    assert fighter.health == pytest.approx(200.0)


def test_apply_damage_physical_overflow_carries_to_health():
    """
    When damage exceeds the remaining shield, the overflow reduces health.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=30.0)

    fighter.apply_damage(damage=50.0, damage_type="physical")

    assert fighter.shield == pytest.approx(0.0)
    assert fighter.health == pytest.approx(180.0)


def test_apply_damage_physical_with_zero_shield_only_reduces_health():
    """
    When the shield is already depleted, all physical damage hits health directly.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=0.0)

    fighter.apply_damage(damage=25.0, damage_type="physical")

    assert fighter.shield == pytest.approx(0.0)
    assert fighter.health == pytest.approx(175.0)


def test_apply_damage_physical_exact_shield_depletion():
    """
    Damage exactly equal to the remaining shield brings it to zero without
    touching health.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=50.0)

    fighter.apply_damage(damage=50.0, damage_type="physical")

    assert fighter.shield == pytest.approx(0.0)
    assert fighter.health == pytest.approx(200.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    fighter = make_fighter_without_init()

    with pytest.raises(NotImplementedError):
        fighter.apply_damage(damage=10.0, damage_type="energy")


@pytest.mark.parametrize(
    "initial_shield, initial_health, damage, expected_shield, expected_health",
    [
        (100.0, 200.0, 80.0, 20.0, 200.0),  # damage < shield
        (100.0, 200.0, 100.0, 0.0, 200.0),  # damage == shield
        (100.0, 200.0, 150.0, 0.0, 150.0),  # damage > shield
        (0.0, 200.0, 30.0, 0.0, 170.0),  # no shield at all
        (50.0, 200.0, 0.0, 50.0, 200.0),  # zero damage
    ],
)
def test_apply_damage_parametrized(
    initial_shield,
    initial_health,
    damage,
    expected_shield,
    expected_health,
):
    """
    Parametrised table covering the full shield/health damage distribution logic.
    """
    fighter = make_fighter_without_init(
        current_health=initial_health, current_shield=initial_shield
    )

    fighter.apply_damage(damage=damage, damage_type="physical")

    assert fighter.shield == pytest.approx(expected_shield)
    assert fighter.health == pytest.approx(expected_health)


# ---------------------------
# ordnance (loadout launchers)
# ---------------------------


class FakeLauncher:
    """
    Stands in for an OrdnanceLauncher: spends one unit of stock per launch and
    records the target it was given.
    """

    def __init__(self, category: str, stock: int, name: str = ""):
        self.category = category
        self.stock = stock
        self.name = name or category
        self.targets = []

    def launch(self, target_id=None) -> bool:
        if self.stock <= 0:
            return False
        self.stock -= 1
        self.targets.append(target_id)
        return True


def _fighter_with_loadout(*launchers: FakeLauncher, locked: bool = False):
    """
    A fighter carrying these launchers, its secondary and flare launcher picked
    as at construction.
    """
    fighter = make_fighter_without_init()
    fighter.ordnance_launchers = list(launchers)
    fighter.selected_secondary = None
    fighter.cycle_secondary()
    fighter.flare_launcher = next(
        (launcher for launcher in launchers if launcher.category == "flare"), None
    )
    fighter.target_id = "target"
    fighter.auto_aim = MagicMock(is_target_acquired=locked)
    return fighter


def test_first_secondary_with_stock_is_selected_initially():
    """
    The initial secondary weapon is the first bomb, rocket or missile launcher
    with stock left, in loadout order; flares are never a secondary.
    """
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(
        FakeLauncher("flare", 10), FakeLauncher("missile", 0), rocket
    )

    assert fighter.selected_secondary is rocket


def test_fire_secondary_gives_a_missile_the_target_only_when_locked():
    """
    A missile carries the current target only while auto-aim is locked on it;
    otherwise it flies blind.
    """
    missile = FakeLauncher("missile", 2)
    fighter = _fighter_with_loadout(missile, locked=False)

    assert fighter.fire_secondary() is True
    fighter.auto_aim.is_target_acquired = True
    assert fighter.fire_secondary() is True

    assert missile.targets == [None, "target"]


def test_fire_secondary_launches_the_selected_launcher():
    """
    fire_secondary spends one unit of the selected secondary weapon.
    """
    rocket = FakeLauncher("rocket", 5)
    fighter = _fighter_with_loadout(rocket)

    assert fighter.fire_secondary() is True
    assert rocket.stock == 4


def test_fire_secondary_moves_on_once_the_selection_is_spent():
    """
    Once the selected launcher runs out, the next one with stock is selected.
    """
    missile = FakeLauncher("missile", 1)
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(missile, rocket)
    assert fighter.selected_secondary is missile

    assert fighter.fire_secondary() is True
    assert fighter.selected_secondary is rocket


def test_cycle_secondary_loops_over_launchers_with_stock_and_skips_flares():
    """
    cycle_secondary goes through the bomb/rocket/missile launchers with stock,
    in loadout order, and wraps around; flares and empty launchers are skipped.
    """
    missile = FakeLauncher("missile", 2)
    flare = FakeLauncher("flare", 10)
    empty_bomb = FakeLauncher("bomb", 0)
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(missile, flare, empty_bomb, rocket)

    fighter.cycle_secondary()
    assert fighter.selected_secondary is rocket
    fighter.cycle_secondary()
    assert fighter.selected_secondary is missile


def test_secondary_is_none_without_secondary_ordnance():
    """
    A ship without bombs, rockets or missiles has no secondary weapon, and
    firing it does nothing.
    """
    fighter = _fighter_with_loadout(FakeLauncher("flare", 10))

    assert fighter.selected_secondary is None
    assert fighter.fire_secondary() is False


def test_drop_flare_without_flares_returns_false():
    """
    A ship without flares drops nothing.
    """
    fighter = _fighter_with_loadout(FakeLauncher("missile", 2))

    assert fighter.drop_flare() is False


def test_drop_flare_launches_a_flare_not_the_secondary():
    """
    drop_flare spends a flare, whatever the selected secondary weapon.
    """
    missile = FakeLauncher("missile", 2)
    flare = FakeLauncher("flare", 10)
    fighter = _fighter_with_loadout(missile, flare)

    assert fighter.drop_flare() is True
    assert flare.stock == 9
    assert missile.stock == 2


# ---------------------------
# ship_handle_health
# ---------------------------


def make_fighter_with_game(
    current_shield: float,
    max_shield: float,
    current_health: float,
    max_health: float,
    shield_regen_rate: float,
    time_step_s: float,
):
    """
    Build a Fighter with a mocked game for ship_handle_health tests.
    """
    fighter = make_fighter_without_init(
        max_health=max_health,
        current_health=current_health,
        max_shield=max_shield,
        current_shield=current_shield,
        shield_regen_rate=shield_regen_rate,
    )
    mock_game = MagicMock()
    mock_game.game_time.get_time_step.return_value = time_step_s
    fighter.game = mock_game
    return fighter


def test_ship_handle_health_regenerates_shield_by_rate_times_dt():
    """
    ship_handle_health increases shield by shield_regen_rate * dt.
    """
    fighter = make_fighter_with_game(
        current_shield=80.0,
        max_shield=100.0,
        current_health=200.0,
        max_health=200.0,
        shield_regen_rate=5.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(85.0)


def test_ship_handle_health_does_not_regenerate_shield_above_max():
    """
    ship_handle_health clamps shield to max_shield.
    """
    fighter = make_fighter_with_game(
        current_shield=98.0,
        max_shield=100.0,
        current_health=200.0,
        max_health=200.0,
        shield_regen_rate=5.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(100.0)


def test_ship_handle_health_clamps_health_to_max():
    """
    ship_handle_health clamps health to max_health even if it somehow exceeded it.
    """
    fighter = make_fighter_with_game(
        current_shield=100.0,
        max_shield=100.0,
        current_health=250.0,  # artificially above max
        max_health=200.0,
        shield_regen_rate=0.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.health == pytest.approx(200.0)


def test_ship_handle_health_shield_stays_zero_when_fully_depleted_and_no_regen():
    """
    A fully depleted shield remains at zero when shield_regen_rate is zero.
    """
    fighter = make_fighter_with_game(
        current_shield=0.0,
        max_shield=100.0,
        current_health=200.0,
        max_health=200.0,
        shield_regen_rate=0.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(0.0)
