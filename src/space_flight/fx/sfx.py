import random
from pathlib import Path
from typing import List

import numpy as np
from direct.showbase import Audio3DManager

from space_flight import DATAFILES_PATH

SOUND_VOLUME_REFERENCE_DISTANCE_M = 500
MAX_SOUND_DISTANCE_M = 2000

SFX_MAX_SOUND_DURATION_S = 5

# Balance
TERRAIN_HIT_SOUND_MULTIPLIER = 0.01
TARGET_HIT_SOUND_MULTIPLIER = 1.0
PLAYER_HIT_SOUND_MULTIPLIER = 1.0

SOUND_POOL_LENGTH = 20

# TODO
# Add engine sounds to bot ships. Doppler effect is handled
# https://docs.panda3d.org/1.10/python/programming/audio/3d-audio


class SFX:
    def __init__(self, app):
        self.app = app
        self.audio3d = Audio3DManager.Audio3DManager(
            self.app.sfxManagerList[0], self.app.camera
        )
        self.audio3d.setDopplerFactor(10.0)
        self.audio3d.setDistanceFactor(0.1)
        self.audio3d.attachListener(self.app.camera)
        self.audio3d.setListenerVelocityAuto()
        self.app.taskMgr.add(self.update_task, "AudioUpdate")

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
        self, player_ship_pos: np.ndarray, hit_pos: np.ndarray, impact_type: str
    ):
        """
        Play an impact sound where the impact took place

        TODO: add pitch randmoness for variation ?

        :param player_ship_pos: The location of the player
        :param hit_pos: The location of impact
        :param impact_type: The type of impact (target, terrain, etc.)

        """
        # Set the volume according to the distance fromm the impact to the player
        impact_distance = np.linalg.norm(hit_pos - player_ship_pos)
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

    def laser_impact_hit_on_player(
        self, game, relative_hit_point: np.ndarray, is_shield: bool
    ):
        """
        Play a random impact sound where the impact took place

        :param relative_hit_point: The position of the hit relative to the player node
        :param is_shield: Whether the player's shield is active
        """
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
        self.audio3d.attachSoundToObject(sound, dummy_node)
        sound.setVolume(multiplier)
        sound.play()

    def player_crash(self, game, relative_hit_point: np.ndarray, in_terrain: bool):
        """
        Play a random impact sound where the impact took place
        Blend a random long and a random short crash sound
        If the crash is in terrain, add rock impact sound

        :param relative_hit_point: The position of the hit relative to the player node
        :param in_rock: Whether the player has crashed in terrain shield is active
        """
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
            self.audio3d.attachSoundToObject(sound, dummy_node)
            sound.setVolume(multiplier)
            sound.play()
        # Play short crash sound
        sound_pool = self.player_crash_short_sound_pool
        sound = sound_pool.get_sound(randomize_pitch=True)
        # Attach sound to the dumy node
        self.audio3d.attachSoundToObject(sound, dummy_node)
        sound.setVolume(multiplier)
        sound.play()
        # Play long crash sound
        sound_pool = self.player_crash_long_sound_pool
        sound = sound_pool.get_sound(randomize_pitch=True)
        # Attach sound to the dumy node
        self.audio3d.attachSoundToObject(sound, dummy_node)
        sound.setVolume(multiplier)
        sound.play()

    def cannon_fire(self, sound_pool, node):
        """
        Play the cannon firing sound at the cannon's location

        :param sound_pool: The sound pool from which to draw the sound
        :param node: The node to attach the sound to
        """
        sound = sound_pool.get_sound(randomize_pitch=True)
        self.audio3d.attachSoundToObject(sound, node)
        sound.play()

    def update_task(self, task):
        self.audio3d.update()
        return task.cont
