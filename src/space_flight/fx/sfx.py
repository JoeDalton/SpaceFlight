import glob
import random
from typing import List

import numpy as np
from direct.showbase import Audio3DManager
from panda3d.core import AudioSound

from space_flight import DATAFILES_PATH

SOUND_VOLUME_REFERENCE_DISTANCE_M = 500
MAX_SOUND_DISTANCE_M = 2000

SFX_MAX_SOUND_DURATION_S = 5

# Balance
TERRAIN_HIT_SOUND_MULTIPLIER = 0.1
TARGET_HIT_SOUND_MULTIPLIER = 1.0
PLAYER_HIT_SOUND_MULTIPLIER = 1.0

SOUND_POOL_LENGTH = 20

random.seed(1)

# TODO
# Add engine sounds to bot ships. Doppler effect is handled
# https://docs.panda3d.org/1.10/python/programming/audio/3d-audio


class SFX:
    def __init__(self, app):
        self.app = app
        self.audio3d = Audio3DManager.Audio3DManager(
            self.app.sfxManagerList[0], self.app.camera
        )

        # Load sounds

        # Lasers hitting player
        self.player_hit_sound_pool = self.build_sound_pool(
            pattern=str(DATAFILES_PATH / "sounds/impacts/laser_on_player/*.wav"),
            is_3d=True,
        )

        # Lasers hitting targets in the distance
        self.distant_target_hit_sound_pool = self.build_sound_pool(
            str(DATAFILES_PATH / "sounds/impacts/laser_distant_on_target/*.wav"),
            is_3d=False,
        )

        # Lasers hitting terrain
        self.terrain_hit_sound_pool = self.build_sound_pool(
            str(DATAFILES_PATH / "sounds/impacts/laser_distant_on_rock/*.wav"),
            is_3d=False,
        )

    def build_sound_pool(self, pattern: str, is_3d: bool) -> List[str]:
        """
        Builds a sound pool from a glob pattern

        :param pattern: The glob pattern to find the sound files
        :return: a sound pool
        """
        sound_files = glob.glob(pattern)
        sound_pool = []
        for _ in range(SOUND_POOL_LENGTH):
            sound_file = random.choice(sound_files)
            if is_3d:
                sound = self.audio3d.loadSfx(sound_file)
            else:
                sound = self.app.loader.loadSfx(sound_file)
            sound_pool.append(sound)
        return sound_pool

    def distant_impact_hit(self, hit_pos: np.ndarray, impact_type: str):
        """
        Play an impact sound where the impact took place

        TODO: add pitch randmoness for variation ?

        :param hit_pos: The location of impact
        :param impact_type: The type of impact (target, terrain, etc.)

        """
        # Set the volume according to the distance fromm the impact to the player
        impact_distance = np.linalg.norm(hit_pos - self.app.player.ship.position)
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

        # Add sound to laser hit (empty list if no sound)
        for _ in range(SOUND_POOL_LENGTH):
            sound = random.choice(sound_pool)
            # Using a pool to avoid reloading resources
            # Must use a non-currently-playing sound, otherwise it will restart
            if sound.status() != AudioSound.PLAYING:
                sound.setVolume(volume * multiplier)
                sound.play()
                break

    def impact_hit_on_player(self, relative_hit_point: np.ndarray):
        """
        Play a random impact sound where the impact took place

        :param relative_hit_point: The position of the hit relative to the player node
        """
        sound_pool = self.player_hit_sound_pool
        multiplier = PLAYER_HIT_SOUND_MULTIPLIER

        # Create ad-hoc dummy node to place the sound
        dummy_node = self.app.camera.attachNewNode("player_hit_sound_node")
        dummy_node.setPos(*relative_hit_point)  # slightly to the right
        # Delete it in the near future
        self.app.doMethodLater(
            SFX_MAX_SOUND_DURATION_S,
            lambda t: dummy_node.remove_node(),
            "remove_player_hit_sound_node",
        )

        # Add sound to laser hit (empty list if no sound)
        for _ in range(SOUND_POOL_LENGTH):
            sound = random.choice(sound_pool)
            # Using a pool to avoid reloading resources
            # Must use a non-currently-playing sound, otherwise it will restart
            if sound.status() != AudioSound.PLAYING:
                # Randomize the pitch of the sound to get a more realistic feeling
                sound.setPlayRate(random.uniform(0.9, 1.1))
                # Attach sound to the camera
                self.app.sfx.audio3d.attachSoundToObject(sound, dummy_node)
                sound.setVolume(multiplier)
                sound.play()
                break
