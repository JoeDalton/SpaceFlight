"""
Unit tests for the local warp: the ship's warp flight model
(space_flight.actors.ship), the warp speed rule (space_flight.scenes.scenes) and
the warp drive (space_flight.actors.warp_drive).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import BitMask32, CollisionNode, CollisionSphere, NodePath

from space_flight import (
    WARP_AUTO_EXIT_ALTITUDE_M,
    WARP_CRUISE_THROTTLE,
    WARP_MIN_ALTITUDE_M,
    WARP_MIN_SPEED_MPS,
    WARP_RELAX_MIN_FRAMES,
    WARP_RELAX_TIME_S,
    WARP_SPACE_SPEED_MPS,
    WARP_SPEED_PER_ALTITUDE,
    WARP_TURN_RATE_FACTOR,
)
from space_flight.actors.ship import DIVERGENCE_SPEED_FACTOR, Ship
from space_flight.actors.warp_drive import (
    CHARGE_DURATION_S,
    EXIT_DURATION_S,
    WarpDrive,
    WarpState,
)
from space_flight.fx.hyperspace_overlay import WARP_LOOK
from space_flight.game.collisions import CollisionLayers
from space_flight.game.integrator import Integrator
from space_flight.scenes.scenes import Scene, warp_speed_at_altitude

IDENTITY = np.array([1.0, 0.0, 0.0, 0.0])
FORWARD = np.array([0.0, 1.0, 0.0])  # the nose, with the identity attitude


class _Ship(Ship):
    def apply_damage(self, damage, damage_type):
        pass

    def ship_handle_health(self):
        pass


def make_flying_ship(dt: float = 1 / 60, speed=(0.0, 0.0, 0.0)) -> _Ship:
    """
    A ship, without Panda3D nor assets, flying with the identity attitude (nose
    along +Y), ready for compute_derivatives and move_ship_physics.
    """
    ship = object.__new__(_Ship)
    ship.game = MagicMock()
    ship.game.game_time.get_time_step.return_value = dt
    ship.parent = SimpleNamespace(name="test", record=False)
    ship.state = np.zeros(10)
    ship.state[3:7] = IDENTITY
    ship.state[7:10] = speed
    ship.state_dot = np.zeros(10)
    ship.state_dot_previous = np.zeros(10)
    ship.position = ship.state[:3].copy()
    ship.orientation = IDENTITY.copy()
    ship.speed = np.array(speed, dtype=float)
    ship._last_finite_position = ship.position.copy()
    ship._last_finite_orientation = ship.orientation.copy()
    ship.position_correction = np.zeros(3)
    ship.velocity_correction = np.zeros(3)
    ship.pqr = np.zeros(3)
    ship.scalar_thrust_n = 0.0
    ship.mass_kg = 1000.0
    ship.additional_force_n = np.zeros(3)
    ship.impact_force_n = np.zeros(3)
    ship.external_force_n = np.zeros(3)
    ship.drag_factor = 0.5
    ship.lift_factor = 0.0
    ship.lateral_lift_factor = 0.0
    ship.lift_inefficiency = 0.0
    ship.max_thrust_n = 12800.0
    ship.max_speed_mps = ship._compute_max_speed_mps()
    return ship


# ---------------------------
# Ship: warp flight model
# ---------------------------


def test_warp_acceleration_relaxes_to_the_target_along_the_nose():
    ship = make_flying_ship(speed=(10.0, 100.0, 0.0))
    ship.warp_target_speed_mps = 5000.0

    ship.compute_derivatives()

    expected = (5000.0 * FORWARD - ship.speed) / WARP_RELAX_TIME_S
    np.testing.assert_allclose(ship.state_dot[7:10], expected)
    # No thrust, lift nor drag in warp
    np.testing.assert_array_equal(ship.drag_n, np.zeros(3))
    np.testing.assert_array_equal(ship.lift_n, np.zeros(3))
    np.testing.assert_array_equal(ship.thrust_n, np.zeros(3))


def test_warp_still_feels_impacts_and_consumes_external_forces():
    ship = make_flying_ship(speed=5000.0 * FORWARD)
    ship.warp_target_speed_mps = 5000.0
    ship.impact_force_n = np.array([1000.0, 0.0, 0.0])
    ship.external_force_n = np.array([0.0, 0.0, 2000.0])

    ship.compute_derivatives()

    np.testing.assert_allclose(ship.state_dot[7:10], [1.0, 0.0, 2.0])
    np.testing.assert_array_equal(ship.external_force_n, np.zeros(3))


def test_warp_relaxation_is_stretched_at_low_frame_rates():
    """A frame longer than the time constant would destabilise the integrator."""
    dt = 0.5
    ship = make_flying_ship(dt=dt)
    ship.warp_target_speed_mps = 1000.0

    ship.compute_derivatives()

    expected_relax_s = WARP_RELAX_MIN_FRAMES * dt
    np.testing.assert_allclose(
        ship.state_dot[7:10], 1000.0 * FORWARD / expected_relax_s
    )


def test_sanitize_lets_a_warping_ship_go_past_its_top_speed():
    speed = 100.0 * DIVERGENCE_SPEED_FACTOR * FORWARD * 1000.0
    ship = make_flying_ship(speed=speed)
    ship.warp_target_speed_mps = float(np.linalg.norm(speed))

    ship._sanitize_state()

    np.testing.assert_array_equal(ship.speed, speed)


def test_sanitize_still_snaps_a_runaway_ship_in_normal_flight():
    speed = 2 * DIVERGENCE_SPEED_FACTOR * 160.0 * FORWARD
    ship = make_flying_ship(speed=speed)

    ship._sanitize_state()

    assert np.linalg.norm(ship.speed) == pytest.approx(ship.max_speed_mps)


def test_cruise_speed_is_where_thrust_balances_drag():
    ship = make_flying_ship()

    assert ship.cruise_speed_mps(1.0) == pytest.approx(ship.max_speed_mps)
    cruise = ship.cruise_speed_mps(WARP_CRUISE_THROTTLE)
    assert ship.drag_factor * cruise**2 == pytest.approx(
        ship.forward_thrust_n(WARP_CRUISE_THROTTLE)
    )
    assert 0.0 < cruise < ship.max_speed_mps


# ---------------------------
# Warp speed rule
# ---------------------------


def test_warp_speed_grows_with_altitude():
    assert warp_speed_at_altitude(50_000.0) == pytest.approx(
        WARP_SPEED_PER_ALTITUDE * 50_000.0
    )


def test_warp_speed_has_a_floor():
    assert warp_speed_at_altitude(0.0) == WARP_MIN_SPEED_MPS


def test_warp_speed_without_bodies_is_fixed():
    assert warp_speed_at_altitude(np.inf) == WARP_SPACE_SPEED_MPS


def test_scene_without_bodies_has_infinite_altitude():
    scene = Scene(game=MagicMock())

    assert scene.altitude_m((1e6, 0.0, 0.0)) == np.inf
    assert scene.warp_speed_mps((1e6, 0.0, 0.0)) == WARP_SPACE_SPEED_MPS


def test_scene_altitude_is_above_the_nearest_ground():
    """Measured from the nearest body's ground, in its planet frame."""
    scene = Scene(game=MagicMock())
    body = MagicMock()
    body.position = np.array([0.0, 1000.0, 0.0])
    body.radius = 600_000.0
    body.terrain.query.height_at.return_value = 2000.0
    scene.world = MagicMock()
    scene.world.bodies = [body]
    scene.world.nearest.return_value = body

    altitude = scene.altitude_m((0.0, 1000.0, 700_000.0))

    assert altitude == pytest.approx(700_000.0 - 600_000.0 - 2000.0)
    relative = body.terrain.query.height_at.call_args.args[0]
    np.testing.assert_allclose(relative, [0.0, 0.0, 700_000.0])
    assert body.terrain.query.height_at.call_args.kwargs == {"generate": False}


# ---------------------------
# Closed loop: warping at a planet, then dropping out
# ---------------------------

PLANET_RADIUS_M = 600_000.0


@pytest.mark.parametrize("dt", [1 / 60, 1 / 10])
def test_warp_approach_never_reaches_the_ground(dt):
    """
    Warping nose-first at a (smooth, sphere) planet from 1000 km up: the speed
    follows the altitude down, so the ship closes in exponentially and reaches
    the drive's auto drop-out altitude without overshooting. Dropping out
    there then stops it well above the ground, at cruise speed. Physics goes
    through the game's integrator, at 60 and at 10 fps.
    """
    start_altitude_m = 1_000_000.0
    # Above the planet, nose (+Y) pointing down at its centre
    position = np.array([0.0, -(PLANET_RADIUS_M + start_altitude_m), 0.0])
    ship = make_flying_ship(dt=dt, speed=100.0 * FORWARD)
    ship.state[:3] = position
    ship.position = position.copy()
    integrator = Integrator(game=ship.game)
    ship.game.integrator = integrator

    def altitude():
        return float(np.linalg.norm(ship.position)) - PLANET_RADIUS_M

    def frame():
        ship._register_integrator()
        integrator.step()
        ship.move_ship_physics()
        # move_ship_physics registered again: start the next frame afresh
        integrator.next_idx = 0

    ship.compute_derivatives()
    altitudes = []
    for _ in range(int(60 / dt)):
        if altitude() < WARP_AUTO_EXIT_ALTITUDE_M:
            break
        ship.warp_target_speed_mps = warp_speed_at_altitude(altitude())
        frame()
        altitudes.append(altitude())
    else:
        pytest.fail("never reached the auto drop-out altitude")

    # Closing in steadily, never past the ground
    assert np.all(np.diff(altitudes) < 0)
    exit_altitude_m = altitude()
    assert exit_altitude_m > 0.5 * WARP_AUTO_EXIT_ALTITUDE_M

    # Drop out: slow down to cruise speed
    cruise_mps = ship.cruise_speed_mps(WARP_CRUISE_THROTTLE)
    ship.warp_target_speed_mps = cruise_mps
    for _ in range(int(EXIT_DURATION_S / dt)):
        frame()
        assert altitude() > 0.0

    assert altitude() > 0.5 * exit_altitude_m
    assert np.linalg.norm(ship.speed) == pytest.approx(cruise_mps, rel=0.05)


# ---------------------------
# WarpDrive
# ---------------------------

HULL_FROM = CollisionLayers.DESTRUCTIBLE_FROM
HULL_INTO = CollisionLayers.DESTRUCTIBLE_INTO
SENSOR_FROM = CollisionLayers.SENSOR_FROM
CRUISE_MPS = 75.0
DT = 1 / 60


def add_collider(parent: NodePath, name: str, from_mask, into_mask) -> NodePath:
    node = CollisionNode(name)
    node.addSolid(CollisionSphere(0, 0, 0, 1))
    node.setFromCollideMask(from_mask)
    node.setIntoCollideMask(into_mask)
    return parent.attachNewNode(node)


def make_drive_ship(altitude_m: float = 100_000.0):
    """A ship stand-in for the drive: a real node with a hull and a sensor."""
    ship = SimpleNamespace()
    ship.node = NodePath("ship")
    ship.collision_sphere_np = add_collider(ship.node, "ship", HULL_FROM, HULL_INTO)
    ship.sensor_np = add_collider(ship.node, "sensor", SENSOR_FROM, BitMask32.allOff())
    ship.position = np.zeros(3)
    ship.is_dead = False
    ship.is_dying = False
    ship.in_hyperspace = False
    ship.warp_target_speed_mps = None
    ship.engines_online = MagicMock(return_value=True)
    ship.cruise_speed_mps = MagicMock(return_value=CRUISE_MPS)
    ship.game = SimpleNamespace(scene=MagicMock())
    ship.game.scene.altitude_m.return_value = altitude_m
    return ship


def make_drive(altitude_m: float = 100_000.0, overlay=None) -> WarpDrive:
    drive = WarpDrive(make_drive_ship(altitude_m), overlay=overlay)
    drive.allowed = True
    return drive


def run(drive: WarpDrive, seconds: float, key_held: bool = True, dt: float = DT):
    for _ in range(round(seconds / dt)):
        drive.update(key_held=key_held, dt=dt)


def masks(collider: NodePath):
    node = collider.node()
    return node.getFromCollideMask(), node.getIntoCollideMask()


def charge_and_go_inside(drive: WarpDrive):
    run(drive, CHARGE_DURATION_S + 2 * DT)
    assert drive.state is WarpState.INSIDE


def test_idle_drive_imposes_nothing():
    drive = make_drive()

    assert not drive.active
    assert drive.turn_rate_factor == 1.0
    assert drive.throttle is None


def test_holding_the_key_charges():
    drive = make_drive()

    drive.update(key_held=True, dt=DT)

    assert drive.state is WarpState.CHARGING
    assert drive.turn_rate_factor == WARP_TURN_RATE_FACTOR
    assert drive.throttle == WARP_CRUISE_THROTTLE
    # Still in normal flight, and in the fight, while charging
    assert drive.ship.warp_target_speed_mps is None
    assert not drive.ship.in_hyperspace


@pytest.mark.parametrize(
    "setup",
    [
        lambda drive: setattr(drive, "allowed", False),
        lambda drive: drive.ship.engines_online.configure_mock(return_value=False),
        lambda drive: drive.ship.game.scene.altitude_m.configure_mock(
            return_value=WARP_MIN_ALTITUDE_M - 1.0
        ),
    ],
    ids=["not allowed", "engines offline", "too low"],
)
def test_no_jump_when_it_cannot_start(setup):
    drive = make_drive()
    setup(drive)

    run(drive, 1.0)

    assert drive.state is WarpState.IDLE


def test_jump_starts_anywhere_in_a_scene_without_bodies():
    drive = make_drive(altitude_m=np.inf)

    drive.update(key_held=True, dt=DT)

    assert drive.state is WarpState.CHARGING


def test_releasing_the_key_while_charging_aborts():
    drive = make_drive()
    run(drive, CHARGE_DURATION_S / 2)

    drive.update(key_held=False, dt=DT)

    assert drive.state is WarpState.IDLE
    assert drive.ship.warp_target_speed_mps is None


def test_engines_dying_while_charging_aborts():
    drive = make_drive()
    run(drive, CHARGE_DURATION_S / 2)

    drive.ship.engines_online.return_value = False
    drive.update(key_held=True, dt=DT)

    assert drive.state is WarpState.IDLE


def test_charged_drive_goes_into_hyperspace():
    drive = make_drive(altitude_m=100_000.0)

    charge_and_go_inside(drive)

    ship = drive.ship
    assert ship.in_hyperspace
    assert ship.warp_target_speed_mps == warp_speed_at_altitude(100_000.0)
    # The hull only hits terrain; everything else is muted
    assert masks(ship.collision_sphere_np) == (
        CollisionLayers.WARPING_HULL_FROM,
        CollisionLayers.WARPING_HULL_INTO,
    )
    assert masks(ship.sensor_np) == (BitMask32.allOff(), BitMask32.allOff())


def test_warp_speed_follows_the_altitude():
    drive = make_drive()
    charge_and_go_inside(drive)

    drive.ship.game.scene.altitude_m.return_value = 3_000_000.0
    drive.update(key_held=True, dt=DT)

    assert drive.ship.warp_target_speed_mps == warp_speed_at_altitude(3_000_000.0)


def test_releasing_the_key_drops_out_to_cruise_speed():
    drive = make_drive()
    charge_and_go_inside(drive)

    drive.update(key_held=False, dt=DT)

    assert drive.state is WarpState.EXITING
    assert drive.ship.warp_target_speed_mps == CRUISE_MPS
    drive.ship.cruise_speed_mps.assert_called_with(WARP_CRUISE_THROTTLE)
    assert drive.ship.in_hyperspace


def test_drop_out_ends_back_in_normal_flight():
    drive = make_drive()
    charge_and_go_inside(drive)
    drive.update(key_held=False, dt=DT)

    run(drive, EXIT_DURATION_S + DT, key_held=False)

    ship = drive.ship
    assert drive.state is WarpState.IDLE
    assert ship.warp_target_speed_mps is None
    assert not ship.in_hyperspace
    assert masks(ship.collision_sphere_np) == (HULL_FROM, HULL_INTO)
    assert masks(ship.sensor_np) == (SENSOR_FROM, BitMask32.allOff())


def test_too_close_to_a_body_drops_out_automatically():
    drive = make_drive()
    charge_and_go_inside(drive)

    drive.ship.game.scene.altitude_m.return_value = WARP_AUTO_EXIT_ALTITUDE_M - 1.0
    drive.update(key_held=True, dt=DT)

    assert drive.state is WarpState.EXITING


def test_after_an_auto_drop_out_the_key_must_be_released():
    drive = make_drive()
    charge_and_go_inside(drive)
    drive.ship.game.scene.altitude_m.return_value = WARP_AUTO_EXIT_ALTITUDE_M - 1.0
    drive.update(key_held=True, dt=DT)
    # Back up high enough, key still held through the drop out
    drive.ship.game.scene.altitude_m.return_value = 100_000.0
    run(drive, EXIT_DURATION_S + 1.0)
    assert drive.state is WarpState.IDLE

    drive.update(key_held=False, dt=DT)
    drive.update(key_held=True, dt=DT)

    assert drive.state is WarpState.CHARGING


def test_disallowing_the_warp_mid_jump_drops_out():
    drive = make_drive()
    charge_and_go_inside(drive)

    drive.allowed = False
    drive.update(key_held=True, dt=DT)

    assert drive.state is WarpState.EXITING


def test_pause_freezes_the_drive():
    drive = make_drive()
    run(drive, CHARGE_DURATION_S / 2)
    charged_s = drive.state_time_s

    for _ in range(600):
        drive.update(key_held=True, dt=0.0)

    assert drive.state is WarpState.CHARGING
    assert drive.state_time_s == charged_s


@pytest.mark.parametrize("flag", ["is_dead", "is_dying"])
def test_losing_the_ship_stops_the_jump_at_once(flag):
    drive = make_drive()
    charge_and_go_inside(drive)

    setattr(drive.ship, flag, True)
    drive.update(key_held=True, dt=DT)

    assert drive.state is WarpState.IDLE
    assert not drive.ship.in_hyperspace
    assert drive.ship.warp_target_speed_mps is None
    assert masks(drive.ship.collision_sphere_np) == (HULL_FROM, HULL_INTO)


# ---------------------------
# WarpDrive: the animation
# ---------------------------


def test_drive_plays_the_phases(fake_overlay_factory):
    overlay = fake_overlay_factory(look=WARP_LOOK)
    drive = make_drive(overlay=overlay)

    drive.update(key_held=True, dt=DT)
    assert overlay.phase == "into"

    charge_and_go_inside(drive)
    assert overlay._next_phase == "inside"

    drive.update(key_held=False, dt=DT)
    assert overlay._next_phase == "outof"

    run(drive, EXIT_DURATION_S + DT, key_held=False)
    assert not overlay.visible


def test_drive_fades_the_animation_out_on_abort(fake_overlay_factory):
    overlay = fake_overlay_factory(look=WARP_LOOK)
    drive = make_drive(overlay=overlay)
    run(drive, 1.0)

    drive.update(key_held=False, dt=DT)

    assert overlay.transitioning
    assert overlay._next_phase is None


def test_clean_stops_and_removes_the_animation(fake_overlay_factory):
    overlay = fake_overlay_factory(look=WARP_LOOK)
    quads = list(overlay._quads)
    drive = make_drive(overlay=overlay)
    charge_and_go_inside(drive)

    drive.clean()

    assert drive.state is WarpState.IDLE
    assert not drive.ship.in_hyperspace
    assert all(quad.removed for quad in quads)
    assert drive.overlay is None
