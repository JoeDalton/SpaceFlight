"""
The sound of a hyperspace jump, shared by the loading screen and the local warp
(as :class:`~space_flight.fx.hyperspace_overlay.HyperspaceOverlay` is for the
picture).

The jump sound starts with the "into" animation and plays on to its end, into
the tunnel. A jump called off while charging (a warp only: the loading screen
never aborts) quickly cross-fades it into the abort sound.

Both are cockpit sounds, on SFX's interior manager: still heard once a warp has
cut every outside sound (see SFX.mute_exterior).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from space_flight import DATAFILES_PATH

if TYPE_CHECKING:
    from panda3d.core import AudioSound

    from space_flight.global_architecture.asset_manager import AssetManager

JUMP_SOUND_PATH = DATAFILES_PATH / "sounds/engines/common/jump_hyperspace.wav"
ABORT_SOUND_PATH = DATAFILES_PATH / "sounds/engines/common/abort_hyperspace.wav"
# Volumes, against the player's interior engine loop at 0.1
JUMP_SOUND_VOLUME = 1.0
ABORT_SOUND_VOLUME = 1.0
# How long an aborted jump takes to cross-fade into the abort sound, seconds
ABORT_CROSS_FADE_S = 0.2


class HyperspaceSound:
    """The jump and abort sounds of a hyperspace jump."""

    def __init__(self, asset_manager: AssetManager):
        """
        :param asset_manager: Where the sounds are drawn from (a sound each,
            held until :meth:`destroy`)
        """
        self._jump_pool = asset_manager.get_asset(
            asset_type="sound", path=JUMP_SOUND_PATH
        )
        self._abort_pool = asset_manager.get_asset(
            asset_type="sound", path=ABORT_SOUND_PATH
        )
        self.jump_sound: AudioSound = self._jump_pool.get_sound()
        self.abort_sound: AudioSound = self._abort_pool.get_sound()
        # Time left in the abort cross-fade, seconds, 0 when none is running
        self._fade_left_s = 0.0

    def jump(self):
        """Start the jump sound, from the top (and cut any abort sound)."""
        self._fade_left_s = 0.0
        self.abort_sound.stop()
        self.jump_sound.setVolume(JUMP_SOUND_VOLUME)
        self.jump_sound.play()

    def abort(self):
        """Cross-fade the jump sound into the abort one, over ABORT_CROSS_FADE_S."""
        self._fade_left_s = ABORT_CROSS_FADE_S
        self.abort_sound.setVolume(0.0)
        self.abort_sound.play()

    def update(self, dt: float):
        """
        Advance the abort cross-fade, if one is running.

        :param dt: Time step, seconds (game time for a warp: frozen by a pause)
        """
        if self._fade_left_s <= 0.0:
            return
        self._fade_left_s = max(0.0, self._fade_left_s - dt)
        progress = 1.0 - self._fade_left_s / ABORT_CROSS_FADE_S
        self.jump_sound.setVolume(JUMP_SOUND_VOLUME * (1.0 - progress))
        self.abort_sound.setVolume(ABORT_SOUND_VOLUME * progress)
        if self._fade_left_s == 0.0:
            self.jump_sound.stop()

    def stop(self):
        """Silence both sounds at once."""
        self._fade_left_s = 0.0
        self.jump_sound.stop()
        self.abort_sound.stop()

    def destroy(self):
        """Silence both sounds and give them back to their pools."""
        self.stop()
        self._jump_pool.release_sound(self.jump_sound)
        self._abort_pool.release_sound(self.abort_sound)
