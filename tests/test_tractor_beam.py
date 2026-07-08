"""
Unit tests for the TractorBeamProjector
(space_flight.actors.capital_ship.tractor_beam).

Instances are built with object.__new__ so the grab state machine and force
model can be exercised without Panda3D assets or a running game.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.capital_ship.tractor_beam import TractorBeamProjector
from space_flight.ai import Personality

GRAB = Personality.TRACTOR_BEAM_DEFAULT["tractor_beam"]


def make_prey(position, speed, prey_id="prey"):
    """
    A grabbable prey stub: real position/speed arrays and an id, with a mocked
    apply_external_force to capture the tractor forces.
    """
    prey = MagicMock()
    prey.position = np.array(position, dtype=float)
    prey.speed = np.array(speed, dtype=float)
    prey.id = prey_id
    return prey


def make_tractor(prey=None, host_speed=(0.0, 0.0, 0.0)):
    """
    Build a TractorBeamProjector (bypassing __init__) aimed down +Y, with the
    grab hardware set and its game wired to resolve ``prey`` from interactions.
    """
    tractor = object.__new__(TractorBeamProjector)
    tractor.personality = Personality.TRACTOR_BEAM_DEFAULT
    tractor.range_m = 800.0
    tractor.grab_cone_cos = np.cos(np.deg2rad(20.0))
    tractor.drag_coefficient = 5.0
    tractor.attraction_force_n = 20000.0

    tractor.position = np.zeros(3)
    tractor.forward = np.array([0.0, 1.0, 0.0])
    tractor.mounted_on = SimpleNamespace(speed=np.array(host_speed, dtype=float))

    tractor.is_grabbing = False
    tractor.grabbed_prey_id = None
    tractor.grab_start_time = None
    tractor.last_release_time = None
    tractor.target_id = prey.id if prey is not None else None

    tractor.game = MagicMock()
    if prey is not None:
        tractor.game.interactions.get_actor_index_from_id.return_value = 0
        tractor.game.interactions.actors = [prey]
    else:
        tractor.game.interactions.get_actor_index_from_id.side_effect = ValueError
    # Player is someone else unless a test says otherwise.
    tractor.game.player.pawn.id = "the_player"
    return tractor


# ---------------------------
# _prey_kinematics
# ---------------------------


def test_prey_kinematics_uses_relative_velocity_to_host():
    """
    The relative velocity is the prey's velocity minus the projector's ship's,
    and the direction/distance are measured from the projector.
    """
    tractor = make_tractor(host_speed=(10.0, 0.0, 0.0))
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[10.0, 20.0, 0.0])

    distance_m, v_rel, to_prey_dir = tractor._prey_kinematics(prey)

    assert distance_m == pytest.approx(100.0)
    np.testing.assert_allclose(to_prey_dir, [0.0, 1.0, 0.0])
    np.testing.assert_allclose(v_rel, [0.0, 20.0, 0.0])  # host x-velocity cancels


# ---------------------------
# _try_acquire
# ---------------------------


def test_acquire_when_prey_in_cone_and_range():
    """
    A prey inside the antenna cone and within range starts a grab.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = make_tractor(prey=prey)

    tractor._try_acquire(now=0.0)

    assert tractor.is_grabbing is True
    assert tractor.grabbed_prey_id == prey.id


def test_no_acquire_when_prey_outside_cone():
    """
    A prey off to the side (outside the cone that turns with the antenna) is not
    grabbed even if within range.
    """
    prey = make_prey(position=[100.0, 0.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = make_tractor(prey=prey)

    tractor._try_acquire(now=0.0)

    assert tractor.is_grabbing is False


def test_no_acquire_when_prey_out_of_range():
    """
    A prey dead ahead but beyond range is not grabbed.
    """
    prey = make_prey(position=[0.0, 900.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = make_tractor(prey=prey)

    tractor._try_acquire(now=0.0)

    assert tractor.is_grabbing is False


def test_no_acquire_during_regrab_cooldown():
    """
    Right after a release, the projector cannot re-grab until the cooldown ends.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = make_tractor(prey=prey)
    tractor.last_release_time = 0.0

    tractor._try_acquire(now=GRAB["regrab_cooldown_s"] - 0.5)

    assert tractor.is_grabbing is False


# ---------------------------
# _apply_tractor_forces
# ---------------------------


def test_apply_tractor_forces_drag_and_attraction():
    """
    The force is a drag opposing the relative velocity plus an attraction pulling
    the prey toward the projector.
    """
    tractor = make_tractor()
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    v_rel = np.array([0.0, 10.0, 0.0])
    to_prey_dir = np.array([0.0, 1.0, 0.0])

    tractor._apply_tractor_forces(prey, v_rel, to_prey_dir)

    # drag = -k*||v||*v = -5*10*[0,10,0] = [0,-500,0];
    # attraction = -20000*[0,1,0] = [0,-20000,0]
    prey.apply_external_force.assert_called_once()
    applied = prey.apply_external_force.call_args.args[0]
    np.testing.assert_allclose(applied, [0.0, -20500.0, 0.0])


# ---------------------------
# _service_grab (release conditions + holding)
# ---------------------------


def _grabbing_tractor(prey, start_time=0.0):
    tractor = make_tractor(prey=prey)
    tractor.is_grabbing = True
    tractor.grabbed_prey_id = prey.id
    tractor.grab_start_time = start_time
    return tractor


def test_service_grab_applies_forces_while_held():
    """
    While in range and within the grab window, the projector pulls the prey.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 5.0, 0.0])
    tractor = _grabbing_tractor(prey)

    tractor._service_grab(now=1.0)  # before min_grab_time, still holding

    assert tractor.is_grabbing is True
    prey.apply_external_force.assert_called_once()


def test_service_grab_releases_after_max_time():
    """
    The prey is released once the maximum grab time elapses.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = _grabbing_tractor(prey)

    tractor._service_grab(now=GRAB["max_grab_time_s"] + 0.1)

    assert tractor.is_grabbing is False
    prey.apply_external_force.assert_not_called()


def test_service_grab_releases_when_fast_after_min_time():
    """
    After the minimum grab time, a prey moving faster than the release speed
    (relative to the host) wrenches free.
    """
    fast = GRAB["release_speed_mps"] + 10.0
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, fast, 0.0])
    tractor = _grabbing_tractor(prey)

    tractor._service_grab(now=GRAB["min_grab_time_s"] + 0.1)

    assert tractor.is_grabbing is False


def test_service_grab_holds_fast_prey_before_min_time():
    """
    Before the minimum grab time, even a fast prey is held (hysteresis).
    """
    fast = GRAB["release_speed_mps"] + 10.0
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, fast, 0.0])
    tractor = _grabbing_tractor(prey)

    tractor._service_grab(now=GRAB["min_grab_time_s"] - 0.5)

    assert tractor.is_grabbing is True
    prey.apply_external_force.assert_called_once()


def test_service_grab_releases_when_out_of_range():
    """
    A prey that leaves the beam's reach is released.
    """
    prey = make_prey(position=[0.0, 900.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = _grabbing_tractor(prey)

    tractor._service_grab(now=1.0)

    assert tractor.is_grabbing is False


def test_service_grab_releases_when_prey_gone():
    """
    A prey that vanished from interactions is released.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = _grabbing_tractor(prey)
    # Prey no longer resolvable.
    tractor.game.interactions.get_actor_index_from_id.side_effect = ValueError

    tractor._service_grab(now=1.0)

    assert tractor.is_grabbing is False


# ---------------------------
# _start_grab / _release / sound
# ---------------------------


def test_start_grab_plays_sfx_when_grabbing_the_player():
    """
    Grabbing the player cues the placeholder tractor-beam SFX.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0], prey_id="p1")
    tractor = make_tractor(prey=prey)
    tractor.game.player.pawn.id = prey.id  # the prey is the player

    tractor._start_grab(prey, now=0.0)

    tractor.game.app.sfx.tractor_beam_grab.assert_called_once()


def test_start_grab_no_sfx_for_non_player_prey():
    """
    Grabbing a non-player prey does not cue the player SFX.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = make_tractor(prey=prey)  # player id is "the_player" != prey.id

    tractor._start_grab(prey, now=0.0)

    tractor.game.app.sfx.tractor_beam_grab.assert_not_called()


def test_release_resets_state_and_starts_cooldown():
    """
    Releasing clears the grab and records the release time for the cooldown.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = _grabbing_tractor(prey)

    tractor._release(now=7.0)

    assert tractor.is_grabbing is False
    assert tractor.grabbed_prey_id is None
    assert tractor.grab_start_time is None
    assert tractor.last_release_time == pytest.approx(7.0)


def test_release_plays_sfx_when_freeing_the_player():
    """
    Releasing the player cues the placeholder ungrab SFX.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0], prey_id="p1")
    tractor = _grabbing_tractor(prey)
    tractor.game.player.pawn.id = prey.id  # the grabbed prey is the player

    tractor._release(now=7.0)

    tractor.game.app.sfx.tractor_beam_release.assert_called_once()


def test_release_no_sfx_for_non_player_prey():
    """
    Releasing a non-player prey does not cue the player ungrab SFX.
    """
    prey = make_prey(position=[0.0, 100.0, 0.0], speed=[0.0, 0.0, 0.0])
    tractor = _grabbing_tractor(prey)  # player id is "the_player" != prey.id

    tractor._release(now=7.0)

    tractor.game.app.sfx.tractor_beam_release.assert_not_called()


def test_resolve_prey_rejects_ungrabbable_actor():
    """
    An actor that cannot take a force (no apply_external_force, e.g. a waypoint)
    is not a grabbable prey.
    """
    ungrabbable = SimpleNamespace(id="rock", position=np.zeros(3))
    tractor = make_tractor()
    tractor.game.interactions.get_actor_index_from_id.side_effect = None
    tractor.game.interactions.get_actor_index_from_id.return_value = 0
    tractor.game.interactions.actors = [ungrabbable]

    assert tractor._resolve_prey("rock") is None
