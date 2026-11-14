"""
A HyperspaceOverlay without a GPU: its quads are FakeQuads, recording the
shader inputs and visibility, and its shaders are not compiled.

Shared by the hyperspace overlay and loading-state tests (and the warp tests),
through the ``fake_overlay_factory`` fixture of conftest.py.

And a HyperspaceSound without an audio device: its sounds are FakeSounds,
recording their volume and whether they play.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from space_flight.fx import hyperspace_overlay
from space_flight.fx.hyperspace_overlay import (
    LOADING_LOOK,
    HyperspaceLook,
    HyperspaceOverlay,
)
from space_flight.fx.hyperspace_sound import (
    ABORT_SOUND_PATH,
    JUMP_SOUND_PATH,
    HyperspaceSound,
)


class FakeQuad:
    """Stands in for a fullscreen quad NodePath."""

    def __init__(self):
        self.inputs: dict = {}
        self.hidden = False
        self.shader = None
        self.bin = None
        self.removed = False

    def setShaderInput(self, name, value):
        self.inputs[name] = value

    def setShader(self, shader):
        self.shader = shader

    def setBin(self, name, sort):
        self.bin = (name, sort)

    def show(self):
        self.hidden = False

    def hide(self):
        self.hidden = True

    def isHidden(self):
        return self.hidden

    def removeNode(self):
        self.removed = True


def make_win(width: int = 1600, height: int = 900) -> MagicMock:
    """A window (or buffer) of the given size."""
    win = MagicMock(spec=["getXSize", "getYSize"])
    win.getXSize.return_value = width
    win.getYSize.return_value = height
    return win


def patch_overlay_building(monkeypatch):
    """Skip shader compilation and build FakeQuads instead of real quads."""
    monkeypatch.setattr(hyperspace_overlay, "Shader", MagicMock())
    monkeypatch.setattr(
        hyperspace_overlay,
        "make_fullscreen_quad",
        lambda render2d, name, sort: FakeQuad(),
    )


def make_fake_overlay(
    look: HyperspaceLook = LOADING_LOOK, win: MagicMock | None = None
) -> HyperspaceOverlay:
    """A HyperspaceOverlay on FakeQuads (needs patch_overlay_building)."""
    return HyperspaceOverlay(MagicMock(), win or make_win(), look=look)


class FakeSound:
    """Stands in for an AudioSound."""

    def __init__(self):
        self.volume = 1.0
        self.playing = False
        self.plays = 0

    def setVolume(self, volume):
        self.volume = volume

    def play(self):
        self.playing = True
        self.plays += 1

    def stop(self):
        self.playing = False


class FakeSoundPool:
    """Stands in for a SoundPool of one FakeSound."""

    def __init__(self):
        self.sound = FakeSound()
        self.in_use = False

    def get_sound(self):
        self.in_use = True
        return self.sound

    def release_sound(self, sound):
        sound.stop()
        self.in_use = False


def make_fake_sound() -> HyperspaceSound:
    """A HyperspaceSound on FakeSounds."""
    pools = {JUMP_SOUND_PATH: FakeSoundPool(), ABORT_SOUND_PATH: FakeSoundPool()}
    manager = SimpleNamespace(get_asset=lambda asset_type, path: pools[path])
    return HyperspaceSound(manager)
