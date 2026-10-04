from unittest.mock import MagicMock

import pytest

from space_flight.actors.energy import (
    SHIELD_REGEN_DELAY_S,
    SHIELDS,
    EnergySystem,
)
from space_flight.actors.fighter import Fighter
from space_flight.utils.state_machine import Cooldown

LASER_SHOT_ENERGY_COST = 0.02


def make_fighter_without_init(
    max_health: float = 200.0,
    current_health: float = 200.0,
    max_shield: float = 100.0,
    current_shield: float = 100.0,
    shield_regen_rate: float = 10.0,
    clock: MagicMock | None = None,
):
    """
    Build a Fighter instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.

    :param clock: The shield regeneration cooldown's clock (time 0 if None)
    """
    fighter = object.__new__(Fighter)
    fighter.max_health = max_health
    fighter.health = current_health
    fighter.max_shield = max_shield
    fighter.shield = current_shield
    fighter.shield_regen_rate = shield_regen_rate
    fighter.shield_regen_cooldown = Cooldown(
        duration_s=SHIELD_REGEN_DELAY_S,
        clock=clock if clock is not None else MagicMock(return_value=0.0),
    )
    fighter.energy = EnergySystem(
        has_shields=max_shield > 0.0, laser_shot_energy_cost=LASER_SHOT_ENERGY_COST
    )
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


class FakeLock:
    """Stands in for a TargetLock: a settable lock, counting updates and resets."""

    def __init__(self, is_locked: bool = False):
        self.is_locked = is_locked
        self.updates = 0
        self.resets = 0

    def update(self):
        self.updates += 1

    def reset(self):
        self.resets += 1
        self.is_locked = False


class FakeLauncher:
    """
    Stands in for an OrdnanceLauncher: spends one unit of stock per launch and
    records the target it was given. Only a missile launcher has a target lock.
    """

    def __init__(self, category: str, stock: int, name: str = ""):
        self.category = category
        self.stock = stock
        self.name = name or category
        self.targets = []
        self.target_lock = FakeLock() if category == "missile" else None
        self.reloads = 0

    def restart_reload(self):
        self.reloads += 1

    def launch(self, target_id=None) -> bool:
        if self.stock <= 0:
            return False
        self.stock -= 1
        self.targets.append(target_id)
        return True


def _fighter_with_loadout(*launchers: FakeLauncher, auto_aim_locked: bool = False):
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
    fighter.auto_aim = MagicMock(is_target_acquired=auto_aim_locked)
    return fighter


def test_first_secondary_is_selected_initially():
    """
    The initial secondary weapon is the first bomb, rocket or missile launcher
    in loadout order; flares are never a secondary.
    """
    missile = FakeLauncher("missile", 2)
    fighter = _fighter_with_loadout(
        FakeLauncher("flare", 10), missile, FakeLauncher("rocket", 3)
    )

    assert fighter.selected_secondary is missile


def test_fire_secondary_gives_a_missile_the_target_only_when_missile_locked():
    """
    A missile carries the current target only while its own lock holds;
    otherwise it flies blind. The laser auto-aim lock plays no part.
    """
    missile = FakeLauncher("missile", 3)
    fighter = _fighter_with_loadout(missile, auto_aim_locked=True)

    assert fighter.fire_secondary() is True
    missile.target_lock.is_locked = True
    assert fighter.fire_secondary() is True
    fighter.auto_aim.is_target_acquired = False
    assert fighter.fire_secondary() is True

    assert missile.targets == [None, "target", "target"]


def test_cycling_to_another_secondary_restarts_its_reload():
    """
    Switching to another secondary weapon costs a full reload of it; the one
    switched away from is left alone.
    """
    missile = FakeLauncher("missile", 2)
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(missile, rocket)
    missile.reloads = rocket.reloads = 0

    fighter.cycle_secondary()

    assert fighter.selected_secondary is rocket
    assert (missile.reloads, rocket.reloads) == (0, 1)


def test_cycling_a_single_secondary_does_not_restart_its_reload():
    """With a single secondary weapon, cycling keeps it and costs no reload."""
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(rocket)
    rocket.reloads = 0

    fighter.cycle_secondary()

    assert rocket.reloads == 0


def test_moving_on_from_a_spent_secondary_restarts_the_next_ones_reload():
    """
    The automatic switch once the selection is spent is a switch too: the next
    weapon must reload before it can fire.
    """
    missile = FakeLauncher("missile", 1)
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(missile, rocket)
    rocket.reloads = 0

    fighter.fire_secondary()

    assert fighter.selected_secondary is rocket
    assert rocket.reloads == 1


def test_only_the_armed_missile_works_on_its_lock():
    """
    Each frame, the selected missile launcher with stock left updates its lock;
    every other missile launcher drops its own.
    """
    selected = FakeLauncher("missile", 2)
    other = FakeLauncher("missile", 2)
    fighter = _fighter_with_loadout(selected, other, FakeLauncher("rocket", 3))

    fighter._update_missile_locks()

    assert (selected.target_lock.updates, selected.target_lock.resets) == (1, 0)
    assert (other.target_lock.updates, other.target_lock.resets) == (0, 1)


def test_switching_secondary_drops_the_missile_lock():
    """
    Cycling away from a locked missile drops its lock, so coming back to it
    starts the lock delay over.
    """
    missile = FakeLauncher("missile", 2)
    fighter = _fighter_with_loadout(missile, FakeLauncher("rocket", 3))
    missile.target_lock.is_locked = True

    fighter.cycle_secondary()
    fighter._update_missile_locks()

    assert not missile.target_lock.is_locked
    assert missile.target_lock.resets == 1


def test_a_spent_missile_drops_its_lock():
    """
    A selected missile launcher without stock left does not work on its lock.
    """
    missile = FakeLauncher("missile", 0)
    fighter = _fighter_with_loadout(missile)
    missile.target_lock.is_locked = True

    fighter._update_missile_locks()

    assert missile.target_lock.updates == 0
    assert not missile.target_lock.is_locked


@pytest.mark.parametrize(
    "category, stock, lock_holds, expected",
    [
        ("missile", 2, True, True),
        ("missile", 2, False, False),
        ("missile", 0, True, False),  # spent
        ("rocket", 3, False, False),  # no lock to hold
    ],
)
def test_is_missile_locked(category, stock, lock_holds, expected):
    """
    is_missile_locked holds only with a missile selected, stock left, and its
    lock confirmed; never with other secondary weapons.
    """
    launcher = FakeLauncher(category, stock)
    if launcher.target_lock is not None:
        launcher.target_lock.is_locked = lock_holds
    fighter = _fighter_with_loadout(launcher, auto_aim_locked=True)

    assert fighter.is_missile_locked is expected


def test_is_missile_locked_without_secondary_weapons():
    """No secondary weapon selected: no missile lock."""
    fighter = _fighter_with_loadout(FakeLauncher("flare", 10))

    assert fighter.is_missile_locked is False


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
    Once the selected launcher runs out, the next one with stock is selected,
    skipping spent ones.
    """
    missile = FakeLauncher("missile", 1)
    spent_bomb = FakeLauncher("bomb", 0)
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(missile, spent_bomb, rocket)
    assert fighter.selected_secondary is missile

    assert fighter.fire_secondary() is True
    assert fighter.selected_secondary is rocket


def test_spent_selection_stays_when_nothing_else_is_left():
    """
    When every secondary weapon is spent, the last one used stays selected,
    and firing it launches nothing.
    """
    missile = FakeLauncher("missile", 1)
    fighter = _fighter_with_loadout(missile, FakeLauncher("rocket", 0))

    assert fighter.fire_secondary() is True
    assert fighter.selected_secondary is missile
    assert fighter.fire_secondary() is False


def test_cycle_secondary_loops_over_all_secondaries_and_skips_flares():
    """
    cycle_secondary goes through the bomb/rocket/missile launchers, spent ones
    included, in loadout order, and wraps around; flares are skipped.
    """
    missile = FakeLauncher("missile", 2)
    flare = FakeLauncher("flare", 10)
    spent_bomb = FakeLauncher("bomb", 0)
    rocket = FakeLauncher("rocket", 3)
    fighter = _fighter_with_loadout(missile, flare, spent_bomb, rocket)

    assert fighter.secondary_cycle() == [missile, spent_bomb, rocket]
    fighter.cycle_secondary()
    assert fighter.selected_secondary is spent_bomb
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


def test_ship_handle_health_holds_shield_regen_after_a_hit():
    """
    The shield does not regenerate until SHIELD_REGEN_DELAY_S after a hit.
    """
    clock = MagicMock(return_value=10.0)
    fighter = make_fighter_without_init(
        current_shield=100.0, max_shield=100.0, shield_regen_rate=5.0, clock=clock
    )
    fighter.game = MagicMock()
    fighter.game.game_time.get_time_step.return_value = 1.0

    fighter.apply_damage(damage=20.0, damage_type="physical")
    clock.return_value = 10.0 + 0.9 * SHIELD_REGEN_DELAY_S
    fighter.ship_handle_health()
    assert fighter.shield == pytest.approx(80.0)

    clock.return_value = 10.0 + SHIELD_REGEN_DELAY_S
    fighter.ship_handle_health()
    assert fighter.shield == pytest.approx(85.0)


def test_ship_handle_health_hull_hit_also_holds_shield_regen():
    """
    A hit landing on the hull (shield already down) holds regeneration too.
    """
    clock = MagicMock(return_value=0.0)
    fighter = make_fighter_without_init(
        current_shield=0.0, max_shield=100.0, shield_regen_rate=5.0, clock=clock
    )
    fighter.game = MagicMock()
    fighter.game.game_time.get_time_step.return_value = 1.0

    fighter.apply_damage(damage=20.0, damage_type="physical")
    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(0.0)


def test_ship_handle_health_shield_regen_follows_energy_distribution():
    """
    Favouring shields speeds their regeneration up by 0.75 / (1/3).
    """
    fighter = make_fighter_with_game(
        current_shield=0.0,
        max_shield=100.0,
        current_health=200.0,
        max_health=200.0,
        shield_regen_rate=4.0,
        time_step_s=1.0,
    )
    fighter.energy.set_mode(SHIELDS)

    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(4.0 * 0.75 * 3.0)


def test_fighter_turn_rate_and_thrust_follow_engine_gauge():
    """
    A fighter's turn rate scale and thrust factor include the engine gauge's
    bonus or penalty.
    """
    fighter = make_fighter_without_init()
    full = (fighter._turn_rate_scale(0.6), fighter._thrust_factor())
    fighter.energy.engines = 0.5
    half = (fighter._turn_rate_scale(0.6), fighter._thrust_factor())

    assert full[0] > half[0]
    assert full[1] > half[1] == pytest.approx(1.0)
