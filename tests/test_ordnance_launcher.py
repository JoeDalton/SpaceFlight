"""
Unit tests for the ordnance configurations and OrdnanceLauncher
(space_flight.weapons.ordnance_launcher).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import yaml

from space_flight import DATAFILES_PATH
from space_flight.weapons import ordnance_launcher
from space_flight.weapons.ordnance_launcher import (
    ORDNANCE_PATH,
    OrdnanceLauncher,
    load_ordnance_configuration,
)

SHIPPED_ORDNANCE = sorted(path.name for path in ORDNANCE_PATH.iterdir())
SHIP_CONFIGURATIONS = sorted(
    (DATAFILES_PATH / "models/ships").glob("*/configuration.yaml")
)


def make_launcher(name: str = "concussion_missile", stock: int = 3):
    """
    A launcher on a mocked, level ship facing +Y, its clock frozen at 0.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    ship = SimpleNamespace(
        node=MagicMock(),
        speed=np.array([0.0, 100.0, 0.0]),
        forward=np.array([0.0, 1.0, 0.0]),
        up=np.array([0.0, 0.0, 1.0]),
        parent=SimpleNamespace(name="ship"),
    )
    return OrdnanceLauncher(game=game, parent=ship, name=name, stock=stock)


# ---------------------------
# configurations
# ---------------------------


@pytest.mark.parametrize("name", SHIPPED_ORDNANCE)
def test_shipped_ordnance_configurations_are_valid(name):
    """
    Every shipped ordnance configuration loads, passes validation, and holds
    what its launcher and pawn read.
    """
    conf = load_ordnance_configuration(name)

    for key in (
        "life_time_s",
        "damage",
        "reload_s",
        "speed_mps",
        "launch_offset_m",
        "visual_radius_m",
        "collision_radius_m",
    ):
        assert conf[key] >= 0.0, key
    assert len(conf["color"]) == 4
    if conf["type"] == "missile":
        for key in (
            "max_pitch_rate_degps",
            "max_yaw_rate_degps",
            "lock_delay_s",
            "lock_cone_angle_deg",
        ):
            assert conf[key] > 0.0, key


@pytest.mark.parametrize(
    "path", SHIP_CONFIGURATIONS, ids=[path.parent.name for path in SHIP_CONFIGURATIONS]
)
def test_ship_loadouts_name_shipped_ordnance(path):
    """
    Every ordnance named in a ship's loadout has a configuration, and its count
    is a positive integer.
    """
    with open(path) as f:
        loadout = yaml.safe_load(f).get("loadout", {})

    for name, count in loadout.items():
        assert name in SHIPPED_ORDNANCE
        assert isinstance(count, int) and count > 0


@pytest.fixture
def ordnance_directory(tmp_path, monkeypatch):
    """
    Point the ordnance loader at an empty directory (and clear its cache).
    """
    monkeypatch.setattr(ordnance_launcher, "ORDNANCE_PATH", tmp_path)
    ordnance_launcher._read_ordnance_configuration.cache_clear()
    yield tmp_path
    ordnance_launcher._read_ordnance_configuration.cache_clear()


def write_ordnance(directory, name, **overrides):
    """Write a valid ordnance configuration, with some keys overridden."""
    conf = {
        "type": "rocket",
        "launch_direction": "forward",
        "damage_type": "physical",
    }
    conf.update(overrides)
    (directory / name).mkdir()
    with open(directory / name / "configuration.yaml", "w") as f:
        yaml.safe_dump(conf, f)


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"type": "torpedo"}, ValueError),
        ({"launch_direction": "sideways"}, ValueError),
        ({"damage_type": "energy"}, NotImplementedError),
        ({"type": "missile", "lock_delay_s": 1.0}, ValueError),
        ({"type": "missile", "lock_cone_angle_deg": 20.0}, ValueError),
    ],
)
def test_invalid_ordnance_configuration_raises(ordnance_directory, overrides, error):
    """
    An unknown type or launch direction, or a damage type other than physical,
    is refused.
    """
    write_ordnance(ordnance_directory, "bad", **overrides)

    with pytest.raises(error):
        load_ordnance_configuration("bad")


def test_loaded_configuration_is_a_private_copy(ordnance_directory):
    """
    Modifying a loaded configuration does not alter the next one loaded.
    """
    write_ordnance(ordnance_directory, "good")

    load_ordnance_configuration("good")["type"] = "changed"

    assert load_ordnance_configuration("good")["type"] == "rocket"


# ---------------------------
# launcher
# ---------------------------


def test_launcher_reads_its_configuration():
    """
    The launcher exposes its ordnance's name, type, stock, speed and reload.
    """
    launcher = make_launcher("proton_bomb", stock=6)

    assert launcher.name == "proton_bomb"
    assert launcher.category == "bomb"
    assert launcher.stock == 6
    assert launcher.speed_mps == pytest.approx(75.0)
    assert launcher.fire_delay == pytest.approx(launcher.conf["reload_s"])
    assert launcher.display_name == "PROTON BOMB"


def test_a_missile_launcher_has_a_target_lock_tuned_by_its_configuration():
    """
    A missile launcher's target lock takes its delay and cone from the
    missile's configuration.
    """
    launcher = make_launcher("concussion_missile")
    conf = load_ordnance_configuration("concussion_missile")

    assert launcher.target_lock.lock_delay_s == pytest.approx(conf["lock_delay_s"])
    assert launcher.target_lock.min_alignment == pytest.approx(
        np.cos(np.deg2rad(conf["lock_cone_angle_deg"]))
    )


@pytest.mark.parametrize("name", ["rocket", "proton_bomb", "flare"])
def test_unguided_ordnance_launcher_has_no_target_lock(name):
    """Only missiles lock on: other launchers have no target lock."""
    assert make_launcher(name).target_lock is None


def test_clean_cleans_the_target_lock():
    """clean() cleans the missile's target lock and drops it."""
    launcher = make_launcher("concussion_missile")
    target_lock = launcher.target_lock

    launcher.clean()

    assert launcher.target_lock is None
    assert target_lock.game is None


@pytest.mark.parametrize(
    "name, expected_velocity",
    [
        ("proton_bomb", [0.0, 100.0, -75.0]),  # belly
        ("rocket", [0.0, 500.0, 0.0]),  # forward
        ("flare", [0.0, 100.0, 0.0]),  # backward, at 0 m/s
    ],
)
def test_initial_velocity_adds_the_launch_speed_to_the_ship_velocity(
    name, expected_velocity
):
    """
    An ordnance leaves with the ship's velocity plus its launch speed along its
    launch direction.
    """
    velocity = make_launcher(name).initial_velocity()

    np.testing.assert_allclose(velocity, expected_velocity)


def test_launch_spends_one_and_passes_the_target_to_a_missile():
    """
    Launching a missile spends one unit and hands it the target.
    """
    launcher = make_launcher("concussion_missile", stock=2)
    launcher.last_fire_time = -np.inf

    with patch.object(ordnance_launcher, "OrdnanceController") as controller:
        assert launcher.launch(target_id="target") is True

    assert launcher.stock == 1
    assert controller.call_args.kwargs["target_id"] == "target"
    assert controller.call_args.kwargs["launcher"] is launcher


def test_launch_does_not_give_a_target_to_unguided_ordnance():
    """
    Only missiles are guided: a rocket ignores the target it is given.
    """
    launcher = make_launcher("rocket")
    launcher.last_fire_time = -np.inf

    with patch.object(ordnance_launcher, "OrdnanceController") as controller:
        launcher.launch(target_id="target")

    assert controller.call_args.kwargs["target_id"] is None


def test_launch_refuses_when_out_of_stock():
    """
    With no stock left, nothing is launched.
    """
    launcher = make_launcher(stock=0)
    launcher.last_fire_time = -np.inf

    with patch.object(ordnance_launcher, "OrdnanceController") as controller:
        assert launcher.launch() is False

    controller.assert_not_called()


def test_launch_is_rate_limited_and_reloading_spends_nothing():
    """
    Launches are spaced by the reload delay; a refused launch keeps its stock.
    """
    launcher = make_launcher("concussion_missile", stock=3)
    launcher.fire_delay = 2.0
    launcher.last_fire_time = 0.0
    clock = launcher.game.game_time.get_current_time

    with patch.object(ordnance_launcher, "OrdnanceController"):
        clock.return_value = 2.0
        assert launcher.launch() is True
        clock.return_value = 3.0
        assert launcher.launch() is False
        clock.return_value = 4.0
        assert launcher.launch() is True

    assert launcher.stock == 1
