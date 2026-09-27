"""
Unit tests for SFX 3D sound placement (space_flight.fx.sfx).

SFX.__init__ needs a live ShowBase (audio managers, camera), so these tests
bypass it via object.__new__() and mock the Audio3DManager.
"""

from unittest.mock import MagicMock

from panda3d.core import LPoint3f, LVector3f

from space_flight.fx.sfx import SFX


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
