import logging
import random
from pathlib import Path

from panda3d.core import AudioSound

LOGGER = logging.getLogger()

SOUND_POOL_LENGTH = 100


class SoundPool:
    """
    A class to hold sounds ready to be played, using a pool to avoid reloading resources
    """

    def __init__(self, app, path: Path, pattern: str, is_3d: bool):
        if path.is_dir():
            # path is a directory => Find all matching files
            self.pool = build_sound_pool(
                app=app, directory=path, pattern=pattern, is_3d=is_3d
            )
        else:
            # Path is a single file => load as many times as necessary
            self.pool = []
            for _ in range(SOUND_POOL_LENGTH):
                if is_3d:
                    sound = load_3d_sound(app=app, sound_file=path)
                else:
                    sound = load_generic_sound(app=app, sound_file=path)
                self.pool.append(sound)

    def get_sound(self, randomize_pitch: bool = False):
        """
        Returns a sound object ready to be played

        :param randomize_pitch: whether the returned sound must have a randomized pitch
        :return: a sound object, ready to be played
        """
        for sound in self.pool:
            # Must use a non-currently-playing sound, otherwise it will restart
            if sound.status() != AudioSound.PLAYING:
                if randomize_pitch:
                    # Randomize the pitch of the sound to get a more realistic feeling
                    sound.setPlayRate(random.uniform(0.9, 1.1))
                return sound
        # If this state is reached, no ready-to-play sound is available
        LOGGER.warning("No sound ready to play")
        raise RuntimeError("No sound ready to play")


def build_sound_pool(app, directory: Path, pattern: str, is_3d: bool) -> list:
    """
    Builds a sound list from a glob pattern and loads a pool

    :param pattern: The glob pattern to find the sound files
    :return: a sound list
    """
    sound_files = list(directory.glob(pattern))
    sound_pool = []
    for _ in range(SOUND_POOL_LENGTH):
        sound_file = random.choice(sound_files)

        if is_3d:
            sound = load_3d_sound(app, sound_file)
        else:
            sound = load_generic_sound(app, sound_file)
        sound_pool.append(sound)
    return sound_pool


def load_3d_sound(app, sound_file: str) -> object:
    """
    Loads a 3D sound

    :param sound_file: The sound file to load
    :return: The 3d sound object
    """
    return app.sfx.audio3d.loadSfx(sound_file)


def load_generic_sound(app, sound_file: str):
    """
    Loads a non-3d sound

    :param sound_file: The sound file to load
    :return: The sound object
    """
    return app.loader.loadSfx(sound_file)
