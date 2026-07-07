from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from panda3d.core import NodePath

from space_flight.actors.capital_ship.sub_system import SubSystem
from space_flight.actors.capital_ship.targeting_system import TargetingSystem
from space_flight.actors.turret import Turret


def make_turret_without_init(
    max_health: float = 150.0,
    current_health: float = 150.0,
):
    """
    Build a Turret instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    turret = object.__new__(Turret)
    turret.max_health = max_health
    turret.health = current_health
    return turret


# ---------------------------
# apply_damage
# ---------------------------


def test_apply_damage_physical_reduces_health():
    """
    Physical damage is subtracted directly from the turret's health.
    """
    turret = make_turret_without_init(current_health=150.0)

    turret.apply_damage(damage=40.0, damage_type="physical")

    assert turret.health == pytest.approx(110.0)


def test_apply_damage_physical_can_reduce_health_to_zero():
    """
    Physical damage equal to the current health leaves health at exactly zero.
    """
    turret = make_turret_without_init(current_health=50.0)

    turret.apply_damage(damage=50.0, damage_type="physical")

    assert turret.health == pytest.approx(0.0)


def test_apply_damage_physical_can_drive_health_negative():
    """
    Overkill damage drives health below zero; the caller is responsible for
    checking the result.
    """
    turret = make_turret_without_init(current_health=10.0)

    turret.apply_damage(damage=30.0, damage_type="physical")

    assert turret.health == pytest.approx(-20.0)


def test_apply_damage_physical_with_zero_damage_leaves_health_unchanged():
    """
    Applying zero damage does not modify health.
    """
    turret = make_turret_without_init(current_health=150.0)

    turret.apply_damage(damage=0.0, damage_type="physical")

    assert turret.health == pytest.approx(150.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    turret = make_turret_without_init()

    with pytest.raises(NotImplementedError):
        turret.apply_damage(damage=10.0, damage_type="energy")


@pytest.mark.parametrize(
    "initial_health, damage, expected_health",
    [
        (150.0, 0.0, 150.0),  # no damage
        (150.0, 75.0, 75.0),  # half health removed
        (150.0, 150.0, 0.0),  # exactly depleted
        (150.0, 200.0, -50.0),  # overkill
        (0.0, 10.0, -10.0),  # already dead
    ],
)
def test_apply_damage_parametrized(initial_health, damage, expected_health):
    """
    Parametrised table covering the physical damage arithmetic.
    """
    turret = make_turret_without_init(current_health=initial_health)

    turret.apply_damage(damage=damage, damage_type="physical")

    assert turret.health == pytest.approx(expected_health)


# ---------------------------
# handle_health (inherited from SubSystem)
# ---------------------------


def test_handle_health_clamps_health_to_max():
    """
    A turret inherits SubSystem.handle_health, which clamps health to its maximum
    while its ship lives and refreshes its world position.
    """
    turret = make_turret_without_init(max_health=150.0, current_health=200.0)
    turret.mounted_on = SimpleNamespace(is_dead=False)
    turret.game = MagicMock()
    turret.node = MagicMock()
    turret.node.getPos.return_value = (0.0, 0.0, 0.0)

    turret.handle_health()

    assert turret.health == pytest.approx(150.0)


def test_handle_health_zeroes_health_when_ship_dead():
    """
    A turret whose ship is destroyed drops its health to zero so it is cleaned up.
    """
    turret = make_turret_without_init(max_health=150.0, current_health=150.0)
    turret.mounted_on = SimpleNamespace(is_dead=True)

    turret.handle_health()

    assert turret.health == pytest.approx(0.0)


# ---------------------------
# turret is a subsystem (real __init__, asset-heavy parts patched)
# ---------------------------


def test_turret_is_a_subsystem_of_its_ship():
    """
    A turret builds as a SubSystem of the ship it is mounted on: it takes the
    ship's team, keeps the bot as its controller, exposes the "sub_system"
    category, and registers itself with the interaction actors.
    """
    game = MagicMock()
    game.destructibles.alive_objects = []
    game.method_lists = {}
    game.root_node = NodePath("root")
    ship = SimpleNamespace(
        team=2, node=NodePath("ship"), is_dead=False, speed=np.zeros(3)
    )
    ship.node.reparentTo(game.root_node)
    bot = SimpleNamespace(name="turret_bot")

    with patch("space_flight.actors.turret.TurretModel") as mock_model_cls, patch(
        "space_flight.actors.turret.LaserCannon"
    ):
        mock_model_cls.return_value.set_yaw = MagicMock()
        mock_model_cls.return_value.set_pitch = MagicMock()
        mock_model_cls.return_value.cannon_node = NodePath("cannon")
        turret = Turret(game=game, parent=bot, turret_type="test", mounted_on=ship)

    assert isinstance(turret, SubSystem)
    assert turret.mounted_on is ship
    assert turret.parent is bot  # the bot stays the controller
    assert turret.team == 2  # taken from the ship
    assert turret.category == "sub_system"
    game.interactions.add_actor.assert_called_once_with(turret)
    # Directions the turret AI reads exist from the start
    for attr in ("forward", "base_forward", "base_right", "base_up"):
        assert hasattr(turret, attr)


# ---------------------------
# targeting-system boosts (auto-aim + rate of fire)
# ---------------------------


def make_targeting_system(
    is_dead: bool = False,
    fire_rate_multiplier: float = 2.0,
    auto_aim_params: dict = None,
):
    """
    Build a TargetingSystem stub (bypassing __init__) that satisfies the turret's
    isinstance check and exposes the alive/dead flag, multiplier and auto-aim
    tuning it reads.
    """
    targeting_system = object.__new__(TargetingSystem)
    targeting_system.is_dead = is_dead
    targeting_system.fire_rate_multiplier = fire_rate_multiplier
    targeting_system.auto_aim_params = auto_aim_params or {}
    return targeting_system


def make_boostable_turret(base_fire_delay: float = 1.0):
    """
    Build a Turret (bypassing __init__) with just the attributes the targeting
    support logic touches.
    """
    turret = make_turret_without_init()
    turret._auto_aim = MagicMock(name="auto_aim")
    turret.auto_aim = None
    turret._targeting_source = None
    turret.base_fire_delay = base_fire_delay
    turret.laser_cannon = SimpleNamespace(fire_delay=base_fire_delay)
    return turret


def test_active_targeting_system_found_when_alive():
    """
    _active_targeting_system returns a live targeting system mounted on the ship.
    """
    turret = make_boostable_turret()
    targeting_system = make_targeting_system(is_dead=False)
    turret.mounted_on = SimpleNamespace(sub_systems=[targeting_system])

    assert turret._active_targeting_system() is targeting_system


def test_active_targeting_system_ignores_dead_and_other_subsystems():
    """
    A dead targeting system (or any non-targeting subsystem) does not count.
    """
    turret = make_boostable_turret()
    turret.mounted_on = SimpleNamespace(
        sub_systems=[make_targeting_system(is_dead=True), SimpleNamespace()]
    )

    assert turret._active_targeting_system() is None


def test_apply_targeting_support_grants_autoaim_and_faster_fire():
    """
    With a live targeting system, the turret retunes and exposes its auto-aim to
    the cannon, refreshes acquisition, and speeds up its fire rate by the
    multiplier.
    """
    turret = make_boostable_turret(base_fire_delay=1.0)
    params = {"max_assist_angle_deg": 8.0, "target_lock_delay_s": 0.5}
    turret.mounted_on = SimpleNamespace(
        sub_systems=[
            make_targeting_system(
                is_dead=False, fire_rate_multiplier=2.0, auto_aim_params=params
            )
        ]
    )

    turret._apply_targeting_support()

    assert turret.auto_aim is turret._auto_aim
    turret._auto_aim.configure.assert_called_once_with(**params)
    turret._auto_aim.compute_acquisition.assert_called_once()
    assert turret.laser_cannon.fire_delay == pytest.approx(0.5)


def test_apply_targeting_support_reconfigures_only_when_source_changes():
    """
    The auto-aim is retuned when a targeting system comes online, but not again
    on the next frame while the same system keeps boosting the turret.
    """
    turret = make_boostable_turret(base_fire_delay=1.0)
    targeting_system = make_targeting_system(is_dead=False)
    turret.mounted_on = SimpleNamespace(sub_systems=[targeting_system])

    turret._apply_targeting_support()
    turret._apply_targeting_support()

    turret._auto_aim.configure.assert_called_once()
    assert turret._targeting_source is targeting_system


def test_apply_targeting_support_reverts_when_no_targeting_system():
    """
    With no live targeting system, auto-aim is disabled (None, so the cannon
    fires straight) and the fire delay returns to its base value.
    """
    turret = make_boostable_turret(base_fire_delay=1.0)
    # Start from a boosted state to prove it is undone
    turret.auto_aim = turret._auto_aim
    turret.laser_cannon.fire_delay = 0.5
    turret._targeting_source = make_targeting_system()
    turret.mounted_on = SimpleNamespace(sub_systems=[])

    turret._apply_targeting_support()

    assert turret.auto_aim is None
    assert turret.laser_cannon.fire_delay == pytest.approx(1.0)
    assert turret._targeting_source is None
    turret._auto_aim.compute_acquisition.assert_not_called()
