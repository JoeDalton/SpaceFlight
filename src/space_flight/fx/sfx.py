import random

import numpy as np
from direct.showbase import Audio3DManager
from panda3d.core import AudioSound

from space_flight import DATAFILES_PATH

SOUND_VOLUME_REFERENCE_DISTANCE_M = 500
MAX_SOUND_DISTANCE_M = 2000

# Balance
TERRAIN_HIT_SOUND_MULTIPLIER = 0.1
TARGET_HIT_SOUND_MULTIPLIER = 1.0


random.seed(1)


class SFX:
    def __init__(self, app):
        self.app = app
        self.audio3d = Audio3DManager.Audio3DManager(
            self.app.sfxManagerList[0], self.app.camera
        )

        # Load sounds

        # Hitting targets in the distance
        sound_files = [
            DATAFILES_PATH / "sounds/impacts/exp_distant_small01.wav",
            DATAFILES_PATH / "sounds/impacts/exp_distant_small02.wav",
        ]
        self.distant_target_hit_sound_pool = []
        for _ in range(20):
            sound_file = random.choice(sound_files)
            sound = self.app.loader.loadSfx(sound_file)
            self.distant_target_hit_sound_pool.append(sound)

        # Hitting terrain
        sound_files = [
            DATAFILES_PATH / "sounds/impacts/cs_st_rockfall01.wav",
            DATAFILES_PATH / "sounds/impacts/cs_st_rockfall02.wav",
        ]
        self.terrain_hit_sound_pool = []
        for _ in range(20):
            sound_file = random.choice(sound_files)
            sound = self.app.loader.loadSfx(sound_file)
            self.terrain_hit_sound_pool.append(sound)

    def distant_impact_hit(self, hit_pos: np.ndarray, impact_type: str):
        """
        Play an impact sound where the impact took place

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

        # Add sound to laser shot (empty list if no sound)
        for sound in sound_pool:
            # Using a pool to avoid reloading resources
            # Must use a non-currently-playing sound, otherwise it will restart
            if sound.status() != AudioSound.PLAYING:
                sound.setVolume(volume * multiplier)
                sound.play()
                break
