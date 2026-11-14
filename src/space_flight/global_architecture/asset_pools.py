from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from panda3d.core import AudioSound, Texture

    from space_flight.global_architecture.simulator import SpaceFlightSimulator

LOGGER = logging.getLogger()

SOUND_POOL_LENGTH = 1000


class TexturePool:
    """
    One texture file, or every file matching a glob pattern in a directory,
    from which :meth:`get_texture` picks at random
    """

    def __init__(self, app: SpaceFlightSimulator, path: Path, pattern: str):
        if path.is_dir():
            # path is a directory => Find all matching files
            self.pool = build_texture_pool(app=app, directory=path, pattern=pattern)
        else:
            # Path is a single file
            self.pool = [load_texture(app=app, texture_file=path)]

    def get_texture(self) -> Texture:
        """
        Returns a random texture from the pool

        :return: A texture object
        """
        return random.choice(self.pool)


def build_texture_pool(
    app: SpaceFlightSimulator, directory: Path, pattern: str
) -> list:
    """
    Builds a texture pool from a glob pattern, loading every matching file

    :param app: The ShowBase app
    :param directory: The directory to search
    :param pattern: The glob pattern to find the texture files
    :return: a texture list
    """
    texture_files = list(directory.glob(pattern))
    texture_pool = []
    for texture_file in texture_files:
        texture = load_texture(app, texture_file)
        texture_pool.append(texture)
    return texture_pool


def load_texture(app: SpaceFlightSimulator, texture_file: Path) -> Texture:
    """
    Loads a texture from file

    :param app: The ShowBase app
    :param texture_file: The texture file to load
    :return: The texture object
    """
    return app.loader.loadTexture(texture_file)


class SoundPool:
    """
    SOUND_POOL_LENGTH preloaded instances of a sound (for a directory, random
    picks among the matching files), so several copies can play at once
    """

    def __init__(
        self,
        app: SpaceFlightSimulator,
        path: Path,
        pattern: str,
        is_3d: bool,
        interior: bool = False,
    ):
        """
        :param app: The ShowBase app
        :param path: A sound file, or a directory of them
        :param pattern: The glob pattern of the sound files, for a directory
        :param is_3d: Whether to load positional (Audio3DManager) sounds: mono
            files placed in space, rather than plain (e.g. stereo) ones
        :param interior: For a plain sound, whether it is one of the player's
            cockpit sounds, on SFX's interior manager (heard even while
            warping)
        """
        if path.is_dir():
            # path is a directory => Find all matching files
            self.pool = build_sound_pool(
                app=app,
                directory=path,
                pattern=pattern,
                is_3d=is_3d,
                interior=interior,
            )
        else:
            # Path is a single file => load it SOUND_POOL_LENGTH times
            self.pool = []
            for _ in range(SOUND_POOL_LENGTH):
                if is_3d:
                    sound = load_3d_sound(app=app, sound_file=path)
                else:
                    sound = load_generic_sound(
                        app=app, sound_file=path, interior=interior
                    )
                self.pool.append(sound)
        self.in_use = set()

    def get_sound(self, randomize_pitch: bool = False) -> AudioSound:
        """
        Returns the first sound object in the pool that is not in use, ready to
        be played, and marks it in use until :meth:`release_sound`

        :param randomize_pitch: Whether the returned sound must have a randomized pitch
        :return: A sound object, ready to be played
        :raises RuntimeError: If every sound in the pool is in use
        """
        for sound in self.pool:
            # A sound in use would restart. Tracked by `id()`: under the null
            # audio backend (headless runs) every AudioSound compares and
            # hashes equal to every other, so a set of the objects themselves
            # would mark all sounds in use as soon as one was taken.
            if id(sound) not in self.in_use:
                self.in_use.add(id(sound))
                if randomize_pitch:
                    # Randomize the pitch for variety
                    sound.setPlayRate(random.uniform(0.9, 1.1))
                return sound
        LOGGER.error("No sound ready to play in pool: ")
        raise RuntimeError("No sound ready to play")

    def release_sound(self, sound: AudioSound):
        """
        Stops the sound and returns it to the pool

        :param sound: A sound previously returned by :meth:`get_sound`
        """
        sound.stop()
        self.in_use.discard(id(sound))

    def in_use_sounds(self) -> list[AudioSound]:
        """
        :return: The sounds currently handed out by :meth:`get_sound`
        """
        return [sound for sound in self.pool if id(sound) in self.in_use]

    def release_all(self):
        """
        Stops every sound in use and returns them all to the pool (level
        teardown: their scheduled releases are dropped with the level)
        """
        for sound in self.in_use_sounds():
            sound.stop()
        self.in_use.clear()


def build_sound_pool(
    app: SpaceFlightSimulator,
    directory: Path,
    pattern: str,
    is_3d: bool,
    interior: bool = False,
) -> list:
    """
    Builds a pool of SOUND_POOL_LENGTH sounds, each loaded from a random file
    matching the glob pattern

    :param app: The ShowBase app
    :param directory: The directory to search
    :param pattern: The glob pattern to find the sound files
    :param is_3d: Whether to load positional (Audio3DManager) sounds
    :param interior: For plain sounds, whether to load them on SFX's interior
        manager (see SoundPool)
    :return: a sound list
    """
    sound_files = list(directory.glob(pattern))
    sound_pool = []
    for _ in range(SOUND_POOL_LENGTH):
        sound_file = random.choice(sound_files)

        if is_3d:
            sound = load_3d_sound(app, sound_file)
        else:
            sound = load_generic_sound(app, sound_file, interior=interior)
        sound_pool.append(sound)
    return sound_pool


def load_3d_sound(app: SpaceFlightSimulator, sound_file: Path) -> AudioSound:
    """
    Loads a 3D sound from file

    :param app: The ShowBase app
    :param sound_file: The sound file to load
    :return: The 3d sound object
    """
    return app.sfx.audio3d.loadSfx(sound_file)


def load_generic_sound(
    app: SpaceFlightSimulator, sound_file: Path, interior: bool = False
) -> AudioSound:
    """
    Loads a non-3d sound from file

    :param app: The ShowBase app
    :param sound_file: The sound file to load
    :param interior: Whether it is one of the player's cockpit sounds, loaded on
        SFX's interior manager (heard even while warping) rather than the
        sound effects one
    :return: The sound object
    """
    if interior:
        return app.loader.loadSound(app.sfx.interior_manager, sound_file)
    return app.loader.loadSfx(sound_file)
