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
from space_flight.ai.aim_assist import AssistCone
from space_flight.weapons import DAMAGE_TYPES, ordnance_launcher
from space_flight.weapons.loadout import Loadout
from space_flight.weapons.ordnance_launcher import (
    ORDNANCE_PATH,
    OrdnanceLauncher,
    load_ordnance_configuration,
)

SHIPPED_ORDNANCE = sorted(path.name for path in ORDNANCE_PATH.iterdir())
SHIP_CONFIGURATIONS = sorted(
    (DATAFILES_PATH / "models/ships").glob("*/configuration.yaml")
)


def make_launcher(
    name: str = "concussion_missile", stock: int = 3, damage_multiplier: float = 1.0
):
    """
    A launcher on a mocked, level ship facing +Y, its clock frozen at 0.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    ship = SimpleNamespace(
        node=MagicMock(),
        conf={"ordnance_launcher_position": [0.0, 0.0, -1.0]},
        speed=np.array([0.0, 100.0, 0.0]),
        right=np.array([1.0, 0.0, 0.0]),
        forward=np.array([0.0, 1.0, 0.0]),
        up=np.array([0.0, 0.0, 1.0]),
        parent=SimpleNamespace(name="ship"),
    )
    return OrdnanceLauncher(
        game=game,
        parent=ship,
        name=name,
        stock=stock,
        damage_multiplier=damage_multiplier,
    )


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
    is a positive integer; its lasers have a known damage type.
    """
    with open(path) as f:
        conf = yaml.safe_load(f).get("loadout", {})

    assert set(conf) <= {"lasers", "ordnance"}
    assert Loadout.from_conf(conf).lasers in DAMAGE_TYPES
    for name, count in conf.get("ordnance", {}).items():
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
        "target_mobility": "slow",
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
        # A missile or rocket must say which targets it is meant for
        ({"target_mobility": None}, ValueError),
        ({"target_mobility": "fast"}, ValueError),
        # A missile must say how flares decoy it
        ({"type": "missile", "target_mobility": "agile"}, ValueError),
        (
            {
                "type": "missile",
                "target_mobility": "agile",
                "decoy_range_m": 400.0,
                "decoy_cone_angle_deg": 30.0,
                "decoy_chance": 1.5,
            },
            ValueError,
        ),
    ],
)
def test_invalid_ordnance_configuration_raises(ordnance_directory, overrides, error):
    """
    An unknown type or launch direction, a damage type other than physical, a
    missile or rocket without a valid target mobility, or a missile without
    valid decoy keys, is refused.
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


def test_damage_multiplier_scales_the_ordnance_damage():
    """
    A launcher's damage multiplier scales the damage of the ordnance it launches
    (read from its configuration), without affecting other launchers.
    """
    base_damage = load_ordnance_configuration("rocket")["damage"]

    scaled = make_launcher("rocket", damage_multiplier=2.0)
    unscaled = make_launcher("rocket")

    assert scaled.damage_multiplier == 2.0
    assert scaled.conf["damage"] == pytest.approx(2.0 * base_damage)
    assert unscaled.conf["damage"] == pytest.approx(base_damage)


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
    launcher.target_lock = MagicMock(is_locked=True)

    with patch.object(ordnance_launcher, "OrdnanceController") as controller:
        assert launcher.launch(target_id="target") is controller.return_value

    assert launcher.stock == 1
    assert controller.call_args.kwargs["target_id"] == "target"
    assert controller.call_args.kwargs["launcher"] is launcher


def test_launch_fires_an_unlocked_missile_blind():
    """
    A missile not locked on the target ignores it, flying blind like a rocket.
    """
    launcher = make_launcher("concussion_missile")
    launcher.last_fire_time = -np.inf

    with patch.object(ordnance_launcher, "OrdnanceController") as controller:
        launcher.launch(target_id="target")

    assert controller.call_args.kwargs["target_id"] is None


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
        assert launcher.launch() is None

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
        assert launcher.launch() is not None
        clock.return_value = 3.0
        assert launcher.launch() is None
        clock.return_value = 4.0
        assert launcher.launch() is not None

    assert launcher.stock == 1


def test_restart_reload_holds_the_launcher_for_a_full_reload():
    """
    restart_reload() starts a full reload now: a launcher that was ready must
    wait its reload delay again before launching.
    """
    launcher = make_launcher("concussion_missile", stock=3)
    launcher.fire_delay = 2.0
    launcher.last_fire_time = 0.0
    clock = launcher.game.game_time.get_current_time

    with patch.object(ordnance_launcher, "OrdnanceController"):
        clock.return_value = 10.0
        launcher.restart_reload()
        clock.return_value = 11.0
        assert launcher.launch() is None
        clock.return_value = 12.0
        assert launcher.launch() is not None


def test_launch_position_is_the_ships_launcher_position_in_its_frame():
    """
    An ordnance starts at the ship's position plus its ordnance_launcher_position
    along the ship's right / forward / up axes, plus the ordnance's own offset
    along its launch direction.
    """
    launcher = make_launcher("flare")
    launcher.parent.position = np.array([10.0, 20.0, 30.0])
    # A ship rolled and yawed: right = +Y, forward = -X, up = +Z
    launcher.parent.right = np.array([0.0, 1.0, 0.0])
    launcher.parent.forward = np.array([-1.0, 0.0, 0.0])
    launcher.position_m = np.array([2.0, 3.0, -1.0])
    offset_m = launcher.conf["launch_offset_m"]

    # Flares go backward: +X
    np.testing.assert_allclose(
        launcher.launch_position(), [10.0 - 3.0 + offset_m, 22.0, 29.0]
    )


@pytest.mark.parametrize(
    "path", SHIP_CONFIGURATIONS, ids=[path.parent.name for path in SHIP_CONFIGURATIONS]
)
def test_fighters_launch_their_ordnance_from_below_the_hull(path):
    with open(path) as f:
        conf = yaml.safe_load(f)

    if "loadout" in conf and "cannon_positions" in conf:
        assert conf["ordnance_launcher_position"] == [0, 0, -1]


# ---------------------------
# bomb aim assist
# ---------------------------

SHIP_POSITION_M = np.array([0.0, 0.0, 0.0])


def _aimed_launcher(name="proton_bomb", assist_deg=20.0, target=None):
    """
    A launcher on a stationary ship whose single target is described by
    (position, velocity) relative to the ship (or None: no interaction).
    """
    launcher = make_launcher(name)
    launcher.parent.position = SHIP_POSITION_M
    launcher.parent.id = "ship"
    launcher.bomb_assist_cone = AssistCone(assist_deg)
    if target is None:
        launcher.game.interactions = MagicMock()
        return launcher
    position, velocity = (np.array(v, dtype=float) for v in target)
    distance = np.linalg.norm(position)
    interactions = MagicMock()
    interactions.get_actor_index_from_id.side_effect = lambda actor_id: (
        0 if actor_id == "ship" else 1
    )
    interactions.distances = np.array([[0.0, distance], [distance, 0.0]])
    directions = np.zeros((2, 2, 3))
    directions[0, 1] = position / distance
    interactions.directions = directions
    rel_velocities = np.zeros((2, 2, 3))
    rel_velocities[0, 1] = velocity
    interactions.rel_velocities = rel_velocities
    launcher.game.interactions = interactions
    return launcher


def test_aimed_bomb_is_bent_toward_the_target_within_the_assist_angle():
    launcher = _aimed_launcher(
        assist_deg=20.0, target=((60.0, 0.0, -200.0), (0.0, 0.0, 0.0))
    )

    direction = launcher.aimed_direction("target")

    nominal = np.array([0.0, 0.0, -1.0])
    angle = np.degrees(np.arccos(direction @ nominal))
    # The target is ~16.7 deg off the nose: within the 20 deg assist
    assert angle == pytest.approx(np.degrees(np.arctan2(60.0, 200.0)), abs=0.5)
    assert direction[0] > 0


def test_aimed_bomb_is_clamped_to_the_assist_angle():
    launcher = _aimed_launcher(
        assist_deg=5.0, target=((300.0, 0.0, -100.0), (0.0, 0.0, 0.0))
    )

    direction = launcher.aimed_direction("target")

    assert np.degrees(np.arccos(direction @ np.array([0.0, 0.0, -1.0]))) == (
        pytest.approx(5.0)
    )


@pytest.mark.parametrize(
    "name, assist_deg, target_id",
    [
        ("proton_bomb", 0.0, "target"),  # assist off
        ("proton_bomb", 20.0, None),  # no target
        ("rocket", 20.0, "target"),  # only bombs are aided
        ("concussion_missile", 20.0, "target"),
    ],
)
def test_no_aim_assist_goes_along_the_launch_direction(name, assist_deg, target_id):
    launcher = _aimed_launcher(
        name=name,
        assist_deg=assist_deg,
        target=((60.0, 0.0, -200.0), (0.0, 0.0, 0.0)),
    )

    np.testing.assert_allclose(
        launcher.aimed_direction(target_id), launcher.launch_direction_vector()
    )


def test_aim_assist_ignores_an_unknown_target():
    launcher = _aimed_launcher(assist_deg=20.0)
    launcher.game.interactions.get_actor_index_from_id.side_effect = None
    launcher.game.interactions.get_actor_index_from_id.return_value = 0

    with patch("space_flight.ai.aim_assist.pair_geometry", return_value=None):
        np.testing.assert_allclose(launcher.aimed_direction("gone"), [0.0, 0.0, -1.0])


@pytest.mark.parametrize(
    "assist_deg, target_x, in_cone",
    [(20.0, 60.0, True), (5.0, 300.0, False), (0.0, 60.0, False)],
)
def test_target_in_assist_cone(assist_deg, target_x, in_cone):
    launcher = _aimed_launcher(
        assist_deg=assist_deg, target=((target_x, 0.0, -200.0), (0.0, 0.0, 0.0))
    )

    assert launcher.is_target_in_assist_cone("target") is in_cone


def test_no_target_is_not_in_the_assist_cone():
    assert _aimed_launcher(assist_deg=20.0).is_target_in_assist_cone(None) is False


def test_is_reloaded_follows_the_reload_gate_without_consuming_it():
    launcher = make_launcher("proton_bomb")
    launcher.game.game_time.get_current_time.return_value = 0.0
    launcher.last_fire_time = 0.0
    launcher.fire_delay = 2.0

    assert launcher.is_reloaded is False
    launcher.game.game_time.get_current_time.return_value = 2.0
    assert launcher.is_reloaded is True
    # Checking did not consume it
    assert launcher.is_reloaded is True
    assert launcher.last_fire_time == 0.0
