"""
Unit tests for the collision helpers and the subsystem collision handling.

These exercise pure logic (bitmask selection, the same-vehicle owner test) and
the ship_into_subsystem pushback, which is built without __init__ and fed
a mocked collision entry so no ShowBase/traversal is needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import BitMask32, Vec3

from space_flight.fx import spark_fx
from space_flight.game.collisions import (
    CollisionLayers,
    CollisionSystem,
    owners_share_vehicle,
)

if TYPE_CHECKING:
    from space_flight.actors.capital_ship.shield import Shield
    from space_flight.actors.capital_ship.sub_system import SubSystem
    from space_flight.actors.ship import Ship
    from space_flight.weapons.laser_cannon import LaserShot

# ---------------------------
# define_collision_masks
# ---------------------------


def test_subsystem_masks_are_into_only() -> None:
    """
    A "subsystem" collider is into-only (like terrain): it never initiates
    collisions and is not added to the collision handler, but it is hit by
    lasers, sensors and destructibles.
    """
    from_mask, into_mask, add_to_handler = CollisionLayers.define_collision_masks(
        "subsystem"
    )

    assert from_mask == BitMask32.allOff()
    assert into_mask == (
        CollisionLayers.MUNITION | CollisionLayers.SENSOR | CollisionLayers.DESTRUCTIBLE
    )
    assert add_to_handler is False


def test_unknown_collider_type_raises() -> None:
    """
    An unrecognised collider type is rejected.
    """
    with pytest.raises(ValueError):
        CollisionLayers.define_collision_masks("not_a_type")


# ---------------------------
# owners_share_vehicle
# ---------------------------


def test_same_object_shares_vehicle() -> None:
    """
    An owner always shares a vehicle with itself.
    """
    owner = SimpleNamespace(mounted_on=None)

    assert owners_share_vehicle(owner, owner) is True


def test_subsystem_shares_vehicle_with_its_ship_both_orders() -> None:
    """
    A subsystem and the ship it is mounted on are the same vehicle, whichever
    way round the collision is reported.
    """
    ship = SimpleNamespace(mounted_on=None)
    subsystem = SimpleNamespace(mounted_on=ship)

    assert owners_share_vehicle(subsystem, ship) is True
    assert owners_share_vehicle(ship, subsystem) is True


def test_sibling_subsystems_share_vehicle() -> None:
    """
    Two subsystems bolted onto the same ship are the same vehicle.
    """
    ship = SimpleNamespace(mounted_on=None)
    generator = SimpleNamespace(mounted_on=ship)
    turret = SimpleNamespace(mounted_on=ship)

    assert owners_share_vehicle(generator, turret) is True


def test_unrelated_ships_do_not_share_vehicle() -> None:
    """
    Two independent ships (and a subsystem vs a foreign ship) are not exempt.
    """
    ship_a = SimpleNamespace(mounted_on=None)
    ship_b = SimpleNamespace(mounted_on=None)
    subsystem_a = SimpleNamespace(mounted_on=ship_a)

    assert owners_share_vehicle(ship_a, ship_b) is False
    assert owners_share_vehicle(subsystem_a, ship_b) is False


def test_standalone_mountables_do_not_share_vehicle() -> None:
    """
    Two owners that are mounted on nothing (mounted_on=None) are not exempt just
    because they both stand alone.
    """
    standalone_a = SimpleNamespace(mounted_on=None)
    standalone_b = SimpleNamespace(mounted_on=None)

    assert owners_share_vehicle(standalone_a, standalone_b) is False


def test_none_owner_never_shares_vehicle() -> None:
    """
    A missing owner (mid-removal) never shares a vehicle.
    """
    owner = SimpleNamespace(mounted_on=None)

    assert owners_share_vehicle(None, owner) is False
    assert owners_share_vehicle(owner, None) is False


def test_owner_without_mounted_on_attribute_is_safe() -> None:
    """
    Owners that predate the mounted_on convention are treated as unmounted.
    """
    plain_a = object()
    plain_b = object()

    assert owners_share_vehicle(plain_a, plain_b) is False


# ---------------------------
# ship_into_subsystem pushback
# ---------------------------


def make_collision_system_without_init() -> CollisionSystem:
    """
    Build a CollisionSystem that bypasses __init__ (no ShowBase/traverser) with
    just enough game state for the handlers under test.

    :return: A bare :class:`CollisionSystem` with a mocked game.
    """
    system = object.__new__(CollisionSystem)
    system.game = MagicMock()
    return system


def make_pushback_entry(
    ship: Ship, subsystem: SubSystem, surface_normal: Vec3
) -> MagicMock:
    """
    Fake a Panda3D collision entry for a ship-into-subsystem collision.

    :param ship: The incoming ship (from-owner)
    :param subsystem: The subsystem being hit (into-owner)
    :param surface_normal: The outward surface normal the entry reports
    :return: A mock collision entry wired with those owners and normal.
    """
    entry = MagicMock()
    entry.from_node_path.python_tags = {"owner": ship}
    entry.into_node_path.python_tags = {"owner": subsystem}
    entry.getSurfaceNormal.return_value = surface_normal
    return entry


def test_ship_into_subsystem_pushes_parent_not_subsystem() -> None:
    """
    A ship ramming a subsystem pushes the incoming ship and the subsystem's
    parent ship apart, damages the incoming ship and the subsystem, but never
    pushes the subsystem itself nor damages the parent ship.
    """
    system = make_collision_system_without_init()

    host = MagicMock()
    host.speed = np.zeros(3)
    host.mass_kg = 800.0
    host.mounted_on = None

    subsystem = MagicMock()
    subsystem.mounted_on = host

    ship = MagicMock()
    ship.speed = np.array([-10.0, 0.0, 0.0])  # closing on the subsystem
    ship.mass_kg = 100.0
    ship.mounted_on = None

    # Normal points out of the subsystem, towards the incoming ship (+x)
    entry = make_pushback_entry(ship, subsystem, Vec3(1.0, 0.0, 0.0))

    system.ship_into_subsystem_pushback(entry)

    # The incoming ship is pushed back (away from the subsystem, +x) and damaged
    ship.push.assert_called_once()
    ship_kwargs = ship.push.call_args.kwargs
    assert ship_kwargs["damage"] == pytest.approx(0.05 * 10.0**2)
    assert ship_kwargs["velocity_correction"][0] > 0.0

    # The parent ship recoils (-x) but takes no damage
    host.push.assert_called_once()
    host_kwargs = host.push.call_args.kwargs
    assert host_kwargs["damage"] == pytest.approx(0.0)
    assert host_kwargs["velocity_correction"][0] < 0.0

    # The subsystem takes the damage but is never pushed
    subsystem.apply_damage.assert_called_once_with(
        damage=pytest.approx(0.05 * 10.0**2), damage_type="physical"
    )
    subsystem.push.assert_not_called()

    # The heavy host barely moves compared to the light incoming ship
    assert abs(host_kwargs["velocity_correction"][0]) < abs(
        ship_kwargs["velocity_correction"][0]
    )


def test_ship_into_subsystem_ignores_own_ship() -> None:
    """
    A ship never collides with its own subsystems: the handler bails out with no
    pushback or damage.
    """
    system = make_collision_system_without_init()

    ship = MagicMock()
    ship.mounted_on = None
    subsystem = MagicMock()
    subsystem.mounted_on = ship  # bolted onto this very ship

    entry = make_pushback_entry(ship, subsystem, Vec3(1.0, 0.0, 0.0))

    system.ship_into_subsystem_pushback(entry)

    ship.push.assert_not_called()
    subsystem.apply_damage.assert_not_called()


def test_ship_into_subsystem_no_pushback_when_separating() -> None:
    """
    If the ship is already moving away from the subsystem, no impulse is applied,
    though the (zero-speed) grazing contact still registers no damage push.
    """
    system = make_collision_system_without_init()

    host = MagicMock()
    host.speed = np.zeros(3)
    host.mass_kg = 800.0
    host.mounted_on = None

    subsystem = MagicMock()
    subsystem.mounted_on = host

    ship = MagicMock()
    ship.speed = np.array([10.0, 0.0, 0.0])  # moving away (+x), same as normal
    ship.mass_kg = 100.0
    ship.mounted_on = None

    entry = make_pushback_entry(ship, subsystem, Vec3(1.0, 0.0, 0.0))

    system.ship_into_subsystem_pushback(entry)

    # Separating: velocity corrections are zero for both bodies
    np.testing.assert_allclose(ship.push.call_args.kwargs["velocity_correction"], 0.0)
    np.testing.assert_allclose(host.push.call_args.kwargs["velocity_correction"], 0.0)


# ---------------------------
# shield masks
# ---------------------------


def test_shield_masks_are_laser_only_into() -> None:
    """
    A "shield" collider is into-only and only lasers hit it: its into-mask is the
    SHIELD bit alone, so ships/sensors (whose from-masks lack SHIELD) pass through.
    """
    from_mask, into_mask, add_to_handler = CollisionLayers.define_collision_masks(
        "shield"
    )

    assert from_mask == BitMask32.allOff()
    assert into_mask == CollisionLayers.SHIELD
    assert add_to_handler is False


def test_lasers_test_against_shields_but_ships_do_not() -> None:
    """
    Only lasers interact with a shield: the laser from-mask carries SHIELD while
    the ship/sensor from-masks do not.
    """
    assert bool(CollisionLayers.MUNITION_FROM & CollisionLayers.SHIELD)
    assert not bool(CollisionLayers.DESTRUCTIBLE_FROM & CollisionLayers.SHIELD)
    assert not bool(CollisionLayers.SENSOR_FROM & CollisionLayers.SHIELD)


# ---------------------------
# munition_into_shield
# ---------------------------


def make_laser_and_shield(
    velocity: list[float], enabled: bool = True, power: float = 60.0
) -> tuple[MagicMock, MagicMock]:
    """
    Build mock laser (from-owner) and shield (into-owner) for the handler.

    :param velocity: The laser's world velocity
    :param enabled: Whether the shield is currently up
    :param power: The laser's damage
    :return: A (laser, shield) pair of mocks.
    """
    laser = MagicMock()
    laser.speed = np.asarray(velocity, dtype=float)
    laser.power = power

    shield = MagicMock()
    shield.is_enabled = enabled
    # A shield has no velocity of its own; it rides the ship it is mounted on.
    # Sparks spawned on a blocked hit read that velocity via _hit_velocity.
    shield.speed = None
    shield.mounted_on = SimpleNamespace(speed=np.zeros(3))
    return laser, shield


def make_shield_entry(
    laser: LaserShot, shield: Shield, surface_normal: Vec3
) -> MagicMock:
    """
    Fake a Panda3D collision entry for a laser-into-shield collision.

    :param laser: The laser (from-owner).
    :param shield: The shield being hit (into-owner).
    :param surface_normal: The outward surface normal the entry reports.
    :return: A mock collision entry wired with those owners and normal.
    """
    entry = MagicMock()
    entry.from_node_path.python_tags = {"owner": laser}
    entry.into_node_path.python_tags = {"owner": shield}
    entry.getSurfaceNormal.return_value = surface_normal
    return entry


def test_laser_from_outside_is_blocked() -> None:
    """
    A laser crossing inward (velocity opposed to the outward normal, dot < 0) is
    absorbed by the shield and removed.
    """
    system = make_collision_system_without_init()
    laser, shield = make_laser_and_shield(velocity=[-10.0, 0.0, 0.0])
    entry = make_shield_entry(laser, shield, Vec3(1.0, 0.0, 0.0))

    system.munition_into_shield(entry)

    shield.take_hit.assert_called_once()
    assert shield.take_hit.call_args.kwargs["damage"] == pytest.approx(60.0)
    laser.shot.removeNode.assert_called_once()


def test_laser_from_inside_passes_through() -> None:
    """
    A laser fired from inside, crossing outward (dot > 0), is not blocked.
    """
    system = make_collision_system_without_init()
    laser, shield = make_laser_and_shield(velocity=[10.0, 0.0, 0.0])
    entry = make_shield_entry(laser, shield, Vec3(1.0, 0.0, 0.0))

    system.munition_into_shield(entry)

    shield.take_hit.assert_not_called()
    laser.shot.removeNode.assert_not_called()


def test_laser_with_degenerate_normal_passes_through() -> None:
    """
    A segment originating inside the solid yields a degenerate (zero) normal;
    dot == 0 is treated as a pass, so the laser is not blocked.
    """
    system = make_collision_system_without_init()
    laser, shield = make_laser_and_shield(velocity=[-10.0, 0.0, 0.0])
    entry = make_shield_entry(laser, shield, Vec3(0.0, 0.0, 0.0))

    system.munition_into_shield(entry)

    shield.take_hit.assert_not_called()
    laser.shot.removeNode.assert_not_called()


def test_disabled_shield_lets_lasers_through() -> None:
    """
    A downed (disabled) shield stops nothing, even a laser crossing inward.
    """
    system = make_collision_system_without_init()
    laser, shield = make_laser_and_shield(velocity=[-10.0, 0.0, 0.0], enabled=False)
    entry = make_shield_entry(laser, shield, Vec3(1.0, 0.0, 0.0))

    system.munition_into_shield(entry)

    shield.take_hit.assert_not_called()
    laser.shot.removeNode.assert_not_called()


def test_munition_into_shield_ignores_missing_owners() -> None:
    """
    A laser or shield removed mid-frame (owner None) is handled without error.
    """
    system = make_collision_system_without_init()
    laser, shield = make_laser_and_shield(velocity=[-10.0, 0.0, 0.0])

    entry_no_laser = make_shield_entry(None, shield, Vec3(1.0, 0.0, 0.0))
    entry_no_shield = make_shield_entry(laser, None, Vec3(1.0, 0.0, 0.0))

    system.munition_into_shield(entry_no_laser)
    system.munition_into_shield(entry_no_shield)

    shield.take_hit.assert_not_called()


def test_laser_does_not_hit_its_own_ships_shield() -> None:
    """
    A laser fired by a turret mounted on a ship passes through that ship's own
    shield, even crossing inward (which would otherwise be blocked).
    """
    system = make_collision_system_without_init()
    ship = SimpleNamespace(mounted_on=None)
    turret = SimpleNamespace(mounted_on=ship)
    # Inward crossing (dot < 0) -> normally blocked; the owner check must win.
    laser, shield = make_laser_and_shield(velocity=[-10.0, 0.0, 0.0])
    laser.origin_ship = turret
    shield.mounted_on = ship
    entry = make_shield_entry(laser, shield, Vec3(1.0, 0.0, 0.0))

    system.munition_into_shield(entry)

    shield.take_hit.assert_not_called()
    laser.shot.removeNode.assert_not_called()


# ---------------------------
# munition_into_destructible — friendly fire
# ---------------------------


def make_destructible_entry(
    laser: LaserShot,
    destructible: Ship | SubSystem,
    surface_normal: Vec3 = Vec3(1.0, 0.0, 0.0),
) -> MagicMock:
    """
    Fake a Panda3D collision entry for a laser-into-destructible collision.

    :param laser: The laser (from-owner).
    :param destructible: The ship or subsystem being hit (into-owner).
    :param surface_normal: The outward surface normal the entry reports.
    :return: A mock collision entry wired with those owners and normal.
    """
    entry = MagicMock()
    entry.from_node_path.python_tags = {"owner": laser}
    entry.into_node_path.python_tags = {"owner": destructible}
    entry.getSurfaceNormal.return_value = surface_normal
    return entry


def test_laser_does_not_hit_the_ship_it_was_fired_from() -> None:
    """
    A turret's laser passes through the very ship it is mounted on.
    """
    system = make_collision_system_without_init()
    ship = MagicMock()
    ship.mounted_on = None
    turret = SimpleNamespace(mounted_on=ship, id="turret-id")
    laser = MagicMock()
    laser.origin_ship = turret
    laser.origin_ship_id = turret.id
    entry = make_destructible_entry(laser, ship)

    system.munition_into_destructible(entry)

    ship.take_hit.assert_not_called()
    laser.shot.removeNode.assert_not_called()


def test_laser_does_not_hit_a_sibling_subsystem() -> None:
    """
    A turret's laser passes through another subsystem bolted onto the same ship
    (e.g. a shield generator or a second turret).
    """
    system = make_collision_system_without_init()
    ship = SimpleNamespace(mounted_on=None)
    turret = SimpleNamespace(mounted_on=ship, id="turret-id")
    sibling = MagicMock()
    sibling.mounted_on = ship
    sibling.id = "sibling-id"
    laser = MagicMock()
    laser.origin_ship = turret
    laser.origin_ship_id = turret.id
    entry = make_destructible_entry(laser, sibling)

    system.munition_into_destructible(entry)

    sibling.take_hit.assert_not_called()
    laser.shot.removeNode.assert_not_called()


# ---------------------------
# munition_into_destructible — shielded vs bare-hull spark colour
# ---------------------------


def make_target_fighter(shield_level: float) -> SimpleNamespace:
    """
    A minimal enemy fighter for the destructible handler's spark-colour branch.

    Its take_hit depletes the shield, so a test that still expects ICE proves the
    handler samples the shield state BEFORE applying the hit.

    :param shield_level: Shield strength at the moment of impact.
    :return: A fighter stand-in with id, speed, shield_level and take_hit.
    """
    fighter = SimpleNamespace(
        id="target-id",
        mounted_on=None,
        speed=np.zeros(3),
        shield_level=shield_level,
    )
    fighter.take_hit = lambda damage, normal_world_vector: setattr(
        fighter, "shield_level", max(0.0, fighter.shield_level - damage)
    )
    return fighter


def make_enemy_laser() -> MagicMock:
    """A laser fired by some other ship (so it is a genuine hit on the target)."""
    laser = MagicMock()
    laser.origin_ship = SimpleNamespace(mounted_on=None)
    laser.origin_ship_id = "shooter-id"
    laser.power = 10.0
    return laser


def spawned_spark_preset(system: CollisionSystem) -> object:
    """Return the preset passed to the single expected spark spawn."""
    system.game.spark_fx_pool.spawn.assert_called_once()
    return system.game.spark_fx_pool.spawn.call_args.kwargs["preset"]


def test_hit_on_shielded_fighter_sparks_ice() -> None:
    """
    A laser hitting an enemy fighter whose shield is still up throws blue ICE
    sparks -- even though take_hit then drains that shield (state read first).
    """
    system = make_collision_system_without_init()
    system.game.player.pawn.id = "player-id"
    fighter = make_target_fighter(shield_level=50.0)
    entry = make_destructible_entry(make_enemy_laser(), fighter)

    system.munition_into_destructible(entry)

    assert spawned_spark_preset(system) is spark_fx.ICE


def test_hit_on_bare_hull_sparks_metal() -> None:
    """
    A laser hitting an enemy fighter with no shield left throws metal sparks.
    """
    system = make_collision_system_without_init()
    system.game.player.pawn.id = "player-id"
    fighter = make_target_fighter(shield_level=0.0)
    entry = make_destructible_entry(make_enemy_laser(), fighter)

    system.munition_into_destructible(entry)

    assert spawned_spark_preset(system) is spark_fx.METAL
