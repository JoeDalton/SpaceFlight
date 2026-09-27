"""
Unit tests for SFX 3D sound placement and Doppler velocities
(space_flight.fx.sfx).

SFX.__init__ needs a live ShowBase (audio managers, camera), so the SFX tests
bypass it via object.__new__() and mock the Audio3DManager. The
PhysicsAudio3DManager tests build a real one on a mock audio manager and
window-less NodePaths.
"""

import gc
from unittest.mock import MagicMock

import numpy as np
import pytest
from direct.task.TaskManagerGlobal import taskMgr
from panda3d.core import LPoint3f, LVector3f, NodePath

from space_flight.fx.sfx import SFX, PhysicsAudio3DManager


class _Body:
    """Stands in for a ship: anything with a world-frame speed."""

    def __init__(self, speed):
        self.speed = np.array(speed, dtype=float)


@pytest.fixture
def manager():
    root = NodePath("render")
    listener = root.attachNewNode("camera")
    audio3d = PhysicsAudio3DManager(MagicMock(), listener, root=root)
    yield audio3d
    taskMgr.remove("Audio3DManager-updateTask")


def test_sound_velocity_follows_its_source_live(manager):
    sound, body = MagicMock(), _Body([10.0, -150.0, 2.5])
    manager.set_sound_velocity_source(sound, body)
    assert tuple(manager.getSoundVelocity(sound)) == (10.0, -150.0, 2.5)
    body.speed = np.array([0.0, 80.0, 0.0])
    assert tuple(manager.getSoundVelocity(sound)) == (0.0, 80.0, 0.0)


def test_sound_without_source_is_static(manager):
    sound = MagicMock()
    assert tuple(manager.getSoundVelocity(sound)) == (0.0, 0.0, 0.0)
    manager.set_sound_velocity_source(sound, _Body([1.0, 2.0, 3.0]))
    manager.set_sound_velocity_source(sound, None)
    assert tuple(manager.getSoundVelocity(sound)) == (0.0, 0.0, 0.0)


def test_detach_sound_drops_its_velocity_source(manager):
    sound, body = MagicMock(), _Body([5.0, 0.0, 0.0])
    manager.attachSoundToObject(sound, manager.root.attachNewNode("ship"))
    manager.set_sound_velocity_source(sound, body)
    manager.detachSound(sound)
    assert tuple(manager.getSoundVelocity(sound)) == (0.0, 0.0, 0.0)


def test_destroyed_source_falls_back_to_zero_and_is_not_kept_alive(manager):
    sound = MagicMock()
    manager.set_sound_velocity_source(sound, _Body([5.0, 0.0, 0.0]))
    gc.collect()
    assert tuple(manager.getSoundVelocity(sound)) == (0.0, 0.0, 0.0)


def test_listener_velocity_follows_its_source(manager):
    assert tuple(manager.getListenerVelocity()) == (0.0, 0.0, 0.0)
    player = _Body([0.0, 120.0, 0.0])
    manager.set_listener_velocity_source(player)
    assert tuple(manager.getListenerVelocity()) == (0.0, 120.0, 0.0)
    manager.set_listener_velocity_source(None)
    assert tuple(manager.getListenerVelocity()) == (0.0, 0.0, 0.0)


def test_update_feeds_physics_velocities_to_the_audio_backend(manager):
    sound, ship = MagicMock(), _Body([0.0, -100.0, 0.0])
    node = manager.root.attachNewNode("ship")
    node.setPos(0.0, 300.0, 0.0)
    manager.attachSoundToObject(sound, node)
    manager.set_sound_velocity_source(sound, ship)
    player = _Body([0.0, 50.0, 0.0])  # held: sources are weak references
    manager.set_listener_velocity_source(player)

    manager.update()

    sound.set3dAttributes.assert_called_with(0.0, 300.0, 0.0, 0.0, -100.0, 0.0)
    listener_args = manager.audio_manager.audio3dSetListenerAttributes.call_args[0]
    assert tuple(listener_args[3:6]) == (0.0, 50.0, 0.0)


def _make_sfx() -> SFX:
    sfx = object.__new__(SFX)
    sfx.audio3d = MagicMock()
    sfx.audio3d.getSoundVelocity.return_value = LVector3f(0, 0, 0)
    return sfx


def test_attach_sound_places_the_sound_at_the_node_immediately():
    sfx = _make_sfx()
    sound, node = MagicMock(), MagicMock()
    node.getPos.return_value = LPoint3f(12.0, 270.0, -3.0)

    sfx.attach_sound(sound, node)

    sfx.audio3d.attachSoundToObject.assert_called_once_with(sound, node)
    sfx.audio3d.set_sound_velocity_source.assert_called_once_with(sound, None)
    node.getPos.assert_called_once_with(sfx.audio3d.root)
    sound.set3dAttributes.assert_called_once_with(12.0, 270.0, -3.0, 0.0, 0.0, 0.0)


def test_cannon_fire_places_the_sound_before_playing_it():
    sfx = _make_sfx()
    game = MagicMock(headless=False)
    sound = MagicMock()
    sound_pool = MagicMock()
    sound_pool.get_sound.return_value = sound
    node = MagicMock()
    node.getPos.return_value = LPoint3f(0.0, 250.0, 0.0)

    sfx.cannon_fire(game=game, sound_pool=sound_pool, node=node)

    calls = [name for name, _, _ in sound.method_calls]
    assert calls.index("set3dAttributes") < calls.index("play")


def test_attach_sound_places_the_sound_with_its_source_velocity():
    sfx = _make_sfx()
    sfx.audio3d.getSoundVelocity.return_value = LVector3f(0.0, -120.0, 0.0)
    sound, node, ship = MagicMock(), MagicMock(), MagicMock()
    node.getPos.return_value = LPoint3f(0.0, 250.0, 0.0)

    sfx.attach_sound(sound, node, velocity_source=ship)

    sfx.audio3d.set_sound_velocity_source.assert_called_once_with(sound, ship)
    sound.set3dAttributes.assert_called_once_with(0.0, 250.0, 0.0, 0.0, -120.0, 0.0)


def test_cannon_fire_gives_the_shot_the_firing_actors_velocity():
    sfx = _make_sfx()
    sound, node, shooter = MagicMock(), MagicMock(), MagicMock()
    sound_pool = MagicMock()
    sound_pool.get_sound.return_value = sound
    node.getPos.return_value = LPoint3f(0.0, 0.0, 0.0)

    sfx.cannon_fire(
        game=MagicMock(headless=False),
        sound_pool=sound_pool,
        node=node,
        velocity_source=shooter,
    )

    sfx.audio3d.set_sound_velocity_source.assert_called_once_with(sound, shooter)
