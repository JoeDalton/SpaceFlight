import logging
import random
import weakref
from pathlib import Path
from typing import List

import numpy as np
from direct.showbase import Audio3DManager
from panda3d.core import VBase3

from space_flight import DATAFILES_PATH
from space_flight.utils import magnitude

LOGGER = logging.getLogger()

SOUND_VOLUME_REFERENCE_DISTANCE_M = 500
MAX_SOUND_DISTANCE_M = 2000

SFX_MAX_SOUND_DURATION_S = 5

# Balance
TERRAIN_HIT_SOUND_MULTIPLIER = 0.01
TARGET_HIT_SOUND_MULTIPLIER = 1.0
PLAYER_HIT_SOUND_MULTIPLIER = 1.0

SOUND_POOL_LENGTH = 20

# Distances are in metres (OpenAL's speed of sound is 343.3 * this, in units/s)
DISTANCE_FACTOR = 1.0
# Half the physical Doppler shift (exactly half at low speed): the full
# shift is too strong at fighter speeds
DOPPLER_FACTOR = 0.5


def _velocity_of(source_ref) -> VBase3:
    """
    :param source_ref: A weak reference to an object with a ``speed`` attribute
        (world-frame velocity, m/s), or None
    :return: Its current velocity, or zero if there is none or it is gone
    """
    source = source_ref() if source_ref is not None else None
    speed = getattr(source, "speed", None)
    if speed is None:
        return VBase3(0, 0, 0)
    return VBase3(*(float(v) for v in speed))


class PhysicsAudio3DManager(Audio3DManager.Audio3DManager):
    """
    Audio3DManager whose Doppler velocities come from physics.

    The stock "auto" velocities are node position deltas (getPosDelta), which
    are zero for nodes moved with plain setPos, i.e. every node in the game.
    Instead, each sound (and the listener) can be given a velocity source: any
    object with a world-frame ``speed`` (a ship, a subsystem...), read at every
    update. Velocities are world-frame even though positions are relative to
    render, which only translates with the player: OpenAL's Doppler needs
    velocities relative to the medium, and directions are unaffected.

    Sources are held by weak reference, so a destroyed ship's sound falls back
    to zero velocity instead of keeping the ship alive. The stock
    setSoundVelocity / setSoundVelocityAuto / setListenerVelocity(Auto) are
    superseded.
    """

    def __init__(self, *args, **kwargs):
        # Keyed by id(): the null audio backend's sounds all compare equal
        self._sound_velocity_sources = {}
        self._listener_velocity_source = None
        super().__init__(*args, **kwargs)

    def set_sound_velocity_source(self, sound, source) -> None:
        """
        :param sound: A 3D sound
        :param source: Object whose ``speed`` is the sound's velocity, or None
            for a static sound
        """
        if source is None:
            self._sound_velocity_sources.pop(id(sound), None)
        else:
            self._sound_velocity_sources[id(sound)] = weakref.ref(source)

    def set_listener_velocity_source(self, source) -> None:
        """
        :param source: Object whose ``speed`` is the listener's velocity, or
            None for a static listener
        """
        self._listener_velocity_source = (
            weakref.ref(source) if source is not None else None
        )

    def getSoundVelocity(self, sound) -> VBase3:
        return _velocity_of(self._sound_velocity_sources.get(id(sound)))

    def getListenerVelocity(self) -> VBase3:
        return _velocity_of(self._listener_velocity_source)

    def detachSound(self, sound):
        self._sound_velocity_sources.pop(id(sound), None)
        return super().detachSound(sound)


class SFX:
    def __init__(self, app):
        self.app = app
        self.audio3d = PhysicsAudio3DManager(
            self.app.sfxManagerList[0], self.app.camera
        )
        self.audio3d.setDopplerFactor(DOPPLER_FACTOR)
        self.audio3d.setDistanceFactor(DISTANCE_FACTOR)
        self.audio3d.attachListener(self.app.camera)
        self.app.taskMgr.add(self.update_task, "AudioUpdate")

    def attach_sound(self, sound, node, velocity_source=None) -> None:
        """
        Attach a 3D sound to a node and place it there right away.

        Audio3DManager only moves attached sounds on its next update, so a
        sound played in between would start from its previous position, or
        from the render origin if it was never placed. The render origin is
        kept on the player (see FlightState.recenter_render_origin), i.e. on
        the listener: every such shot would open with a loud blip.

        :param sound: The 3D sound to attach
        :param node: The node the sound follows
        :param velocity_source: Object whose world-frame ``speed`` drives the
            sound's Doppler shift (the ship carrying the node), or None for a
            static sound
        """
        self.audio3d.attachSoundToObject(sound, node)
        self.audio3d.set_sound_velocity_source(sound, velocity_source)
        pos = node.getPos(self.audio3d.root)
        vel = self.audio3d.getSoundVelocity(sound)
        sound.set3dAttributes(pos[0], pos[1], pos[2], vel[0], vel[1], vel[2])

    def set_listener_velocity_source(self, source) -> None:
        """
        :param source: Object whose world-frame ``speed`` is the listener's
            (camera's) velocity, i.e. the player's pawn, or None
        """
        self.audio3d.set_listener_velocity_source(source)

    def build_sound_pool(self, directory: Path, pattern: str, is_3d: bool) -> List[str]:
        """
        Builds a sound pool from a glob pattern

        :param pattern: The glob pattern to find the sound files
        :return: a sound pool
        """
        sound_files = list(directory.glob(pattern))
        sound_pool = []
        for _ in range(SOUND_POOL_LENGTH):
            sound_file = random.choice(sound_files)
            if is_3d:
                sound = self.get_3d_sound(sound_file)
            else:
                sound = self.app.loader.loadSfx(sound_file)
            sound_pool.append(sound)
        return sound_pool

    def get_3d_sound(self, sound_file: str) -> object:
        """
        Loads a 3D sound

        :param sound_file: The sound file to load
        :return: the 3d sound object
        """
        return self.audio3d.loadSfx(sound_file)

    def get_sounds_from_asset_manager(self):
        self.player_crash_short_sound_pool = self.app.asset_manager.get_asset(
            asset_type="3d_sound",
            path=DATAFILES_PATH / "sounds/impacts/player_crash/short",
            pattern="*.wav",
        )
        self.player_crash_long_sound_pool = self.app.asset_manager.get_asset(
            asset_type="3d_sound",
            path=DATAFILES_PATH / "sounds/impacts/player_crash/long",
            pattern="*.wav",
        )
        self.player_hull_laser_hit_sound_pool = self.app.asset_manager.get_asset(
            asset_type="3d_sound",
            path=DATAFILES_PATH / "sounds/impacts/laser_on_player_hull",
            pattern="*.wav",
        )
        self.player_shield_laser_hit_sound_pool = self.app.asset_manager.get_asset(
            asset_type="3d_sound",
            path=DATAFILES_PATH / "sounds/impacts/laser_on_player_shield",
            pattern="*.ogg",
        )
        self.distant_target_hit_sound_pool = self.app.asset_manager.get_asset(
            asset_type="sound",
            path=DATAFILES_PATH / "sounds/impacts/laser_distant_on_target",
            pattern="*.wav",
        )
        self.terrain_hit_sound_pool = self.app.asset_manager.get_asset(
            asset_type="sound",
            path=DATAFILES_PATH / "sounds/impacts/laser_distant_on_rock",
            pattern="*.wav",
        )

    def distant_impact_hit(
        self, game, player_ship_pos: np.ndarray, hit_pos: np.ndarray, impact_type: str
    ):
        """
        Play an impact sound where the impact took place

        TODO: add pitch randmoness for variation ?

        :param game: The game object
        :param player_ship_pos: The location of the player
        :param hit_pos: The location of impact
        :param impact_type: The type of impact (target, terrain, etc.)

        """
        # No one to hear it, and no camera to hang a 3D sound off of, headless.
        if game.headless:
            return
        # Set the volume according to the distance fromm the impact to the player
        impact_distance = magnitude(hit_pos - player_ship_pos)

        # Ignore distant events
        if impact_distance > MAX_SOUND_DISTANCE_M:
            return
        volume = (SOUND_VOLUME_REFERENCE_DISTANCE_M / impact_distance) ** 2

        # Choose the right pool of sounds
        if impact_type == "target":
            sound_pool = self.distant_target_hit_sound_pool
            multiplier = TARGET_HIT_SOUND_MULTIPLIER
        elif impact_type == "terrain":
            sound_pool = self.terrain_hit_sound_pool
            multiplier = TERRAIN_HIT_SOUND_MULTIPLIER
        else:
            raise NotImplementedError(f"No sound for impact type {impact_type}")

        # Add sound to laser hit
        sound = sound_pool.get_sound(randomize_pitch=False)
        sound.setVolume(volume * multiplier)
        sound.play()

        # Schedule sound release
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="Release distant impact sound",
            method=sound_pool.release_sound,
            extra_args=[sound],
        )

    def tractor_beam_grab(self, game):
        """
        Placeholder cue for a tractor beam locking onto the player.

        TODO: play a looping tractor-beam hum for the duration of the grab. For
        now this only logs, so the grab mechanic can be wired and exercised
        without a dedicated audio asset.

        :param game: The game object
        """
        LOGGER.info("Tractor beam locked onto the player (placeholder SFX)")

    def tractor_beam_release(self, game):
        """
        Placeholder cue for a tractor beam releasing the player.

        TODO: play a release/power-down sound (and stop the grab hum started by
        tractor_beam_grab). For now this only logs.

        :param game: The game object
        """
        LOGGER.info("Tractor beam released the player (placeholder SFX)")

    def laser_impact_hit_on_player(
        self, game, relative_hit_point: np.ndarray, is_shield: bool
    ):
        """
        Play a random impact sound where the impact took place

        :param game: The game object
        :param relative_hit_point: The position of the hit relative to the player node
        :param is_shield: Whether the player's shield is active
        """
        # No one to hear it, and no camera to hang a 3D sound off of, headless.
        if game.headless:
            return
        if is_shield:
            sound_pool = self.player_shield_laser_hit_sound_pool
        else:
            sound_pool = self.player_hull_laser_hit_sound_pool
        multiplier = PLAYER_HIT_SOUND_MULTIPLIER

        # Create ad-hoc dummy node to place the sound
        dummy_node = self.app.camera.attachNewNode("player_hit_sound_node")
        dummy_node.setPos(*relative_hit_point)

        # Delete it in the near future
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="remove_player_hit_sound_node",
            method=dummy_node.remove_node,
        )
        # Add sound to laser hit
        sound = sound_pool.get_sound(randomize_pitch=True)

        # Attach sound to the dummy node
        self.attach_sound(sound, dummy_node, velocity_source=game.player.pawn)
        sound.setVolume(multiplier)
        sound.play()

        # Schedule sound release
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="Release Laser impact on player sound",
            method=sound_pool.release_sound,
            extra_args=[sound],
        )

    def player_crash(self, game, relative_hit_point: np.ndarray, in_terrain: bool):
        """
        Play a random impact sound where the impact took place
        Blend a random long and a random short crash sound
        If the crash is in terrain, add rock impact sound

        :param game: The game object
        :param relative_hit_point: The position of the hit relative to the player node
        :param in_rock: Whether the player has crashed in terrain shield is active
        """
        # No one to hear it, and no camera to hang a 3D sound off of, headless.
        if game.headless:
            return
        # Create ad-hoc dummy node to place the sound
        dummy_node = self.app.camera.attachNewNode("player_hit_sound_node")
        dummy_node.setPos(*relative_hit_point)  # slightly to the right
        # Delete it in the near future
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="remove_player_hit_sound_node",
            method=dummy_node.remove_node,
        )
        multiplier = PLAYER_HIT_SOUND_MULTIPLIER

        # Play terrain hit sound if crash in terrain
        if in_terrain:
            sound_pool = self.terrain_hit_sound_pool
            sound = sound_pool.get_sound(randomize_pitch=True)
            # Attach sound to the cdumy node
            self.attach_sound(sound, dummy_node, velocity_source=game.player.pawn)
            sound.setVolume(multiplier)
            sound.play()
            game.delayed_methods.do_method_later(
                delay_s=SFX_MAX_SOUND_DURATION_S,
                name="Release player crash terrain sound",
                method=sound_pool.release_sound,
                extra_args=[sound],
            )

        # Play short crash sound
        sound_pool = self.player_crash_short_sound_pool
        sound = sound_pool.get_sound(randomize_pitch=True)

        # Attach sound to the dumy node
        self.attach_sound(sound, dummy_node, velocity_source=game.player.pawn)
        sound.setVolume(multiplier)
        sound.play()
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="Release player crash short sound",
            method=sound_pool.release_sound,
            extra_args=[sound],
        )

        # Play long crash sound
        sound_pool = self.player_crash_long_sound_pool
        sound = sound_pool.get_sound(randomize_pitch=True)

        # Attach sound to the dumy node
        self.attach_sound(sound, dummy_node, velocity_source=game.player.pawn)
        sound.setVolume(multiplier)
        sound.play()
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="Release player crash long sound",
            method=sound_pool.release_sound,
            extra_args=[sound],
        )

    def cannon_fire(self, game, sound_pool, node, velocity_source=None):
        """
        Play the cannon firing sound at the cannon's location

        :param game: The game object
        :param sound_pool: The sound pool from which to draw the sound
        :param node: The node to attach the sound to
        :param velocity_source: The firing actor (its ``speed`` drives the
            Doppler shift), or None
        """
        # No one to hear it, headless.
        if game.headless:
            return
        sound = sound_pool.get_sound(randomize_pitch=True)
        self.attach_sound(sound, node, velocity_source=velocity_source)
        sound.play()
        # Schedule sound release
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="Release player crash sound",
            method=sound_pool.release_sound,
            extra_args=[sound],
        )

    def update_task(self, task):
        self.audio3d.update()
        return task.cont
