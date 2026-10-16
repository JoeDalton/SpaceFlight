from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING, Any

import numpy as np
from direct.showbase import Audio3DManager
from direct.task import Task
from panda3d.core import AudioSound, NodePath, VBase3

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.asset_pools import SoundPool
from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.actors.major_ship.sub_system import SubSystem
    from space_flight.actors.pawn import Pawn
    from space_flight.game.flight_state import FlightState
    from space_flight.global_architecture.simulator import SpaceFlightSimulator

LOGGER = logging.getLogger()

SOUND_VOLUME_REFERENCE_DISTANCE_M = 500
MAX_SOUND_DISTANCE_M = 2000

SFX_MAX_SOUND_DURATION_S = 5

# Balance
TERRAIN_HIT_SOUND_MULTIPLIER = 0.01
TARGET_HIT_SOUND_MULTIPLIER = 0.5
PLAYER_HIT_SOUND_MULTIPLIER = 1.0
# Cannon-fire volume for the player's own guns vs everyone else's.
PLAYER_CANNON_FIRE_VOLUME = 1.0
NPC_CANNON_FIRE_VOLUME = 3.0
# Same for distant impacts (a shot landing on a target or on terrain away from
# the player): the player's own shots vs an NPC's.
PLAYER_DISTANT_IMPACT_VOLUME = 1.0
NPC_DISTANT_IMPACT_VOLUME = 0.2

# Distances are in metres (OpenAL's speed of sound is 343.3 * this, in units/s)
DISTANCE_FACTOR = 1.0
# Half the physical Doppler shift (exactly half at low speed): the full
# shift is too strong at fighter speeds
DOPPLER_FACTOR = 0.5


def _velocity_of(source_ref: weakref.ref[Pawn | SubSystem] | None) -> VBase3:
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
    update. Velocities stay world-frame although positions are relative to
    render, which only translates with the player: OpenAL's Doppler needs
    velocities relative to the medium.

    Sources are weak references, so a destroyed ship's sound falls back to zero
    velocity instead of keeping the ship alive. This supersedes the stock
    setSoundVelocity / setSoundVelocityAuto / setListenerVelocity(Auto).
    """

    def __init__(self, *args: Any, **kwargs: Any):
        # Keyed by id(): the null audio backend's sounds all compare equal
        self._sound_velocity_sources = {}
        self._listener_velocity_source = None
        super().__init__(*args, **kwargs)

    def set_sound_velocity_source(
        self, sound: AudioSound, source: Pawn | SubSystem | None
    ):
        """
        :param sound: A 3D sound
        :param source: Object whose ``speed`` is the sound's velocity, or None
            for a static sound
        """
        if source is None:
            self._sound_velocity_sources.pop(id(sound), None)
        else:
            self._sound_velocity_sources[id(sound)] = weakref.ref(source)

    def set_listener_velocity_source(self, source: Pawn | SubSystem | None):
        """
        :param source: Object whose ``speed`` is the listener's velocity, or
            None for a static listener
        """
        self._listener_velocity_source = (
            weakref.ref(source) if source is not None else None
        )

    def getSoundVelocity(self, sound: AudioSound) -> VBase3:
        return _velocity_of(self._sound_velocity_sources.get(id(sound)))

    def getListenerVelocity(self) -> VBase3:
        return _velocity_of(self._listener_velocity_source)

    def detachSound(self, sound: AudioSound) -> int:
        self._sound_velocity_sources.pop(id(sound), None)
        return super().detachSound(sound)


class SFX:
    def __init__(self, app: SpaceFlightSimulator):
        self.app = app
        self.audio3d = PhysicsAudio3DManager(
            self.app.sfxManagerList[0], self.app.camera
        )
        self.audio3d.setDopplerFactor(DOPPLER_FACTOR)
        self.audio3d.setDistanceFactor(DISTANCE_FACTOR)
        self.audio3d.attachListener(self.app.camera)
        self.app.taskMgr.add(self.update_task, "AudioUpdate")

    def attach_sound(
        self,
        sound: AudioSound,
        node: NodePath,
        velocity_source: Pawn | SubSystem | None = None,
    ):
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

    def set_listener_velocity_source(self, source: Pawn | SubSystem | None):
        """
        :param source: Object whose world-frame ``speed`` is the listener's
            (camera's) velocity, i.e. the player's pawn, or None
        """
        self.audio3d.set_listener_velocity_source(source)

    def pause(self):
        """
        Silence the sound effects while the game is frozen behind a menu:
        looping sounds are suspended until :meth:`resume`, one-shots stop.
        Menus play no sound of their own (they would need their own manager).
        """
        self.app.sfxManagerList[0].setActive(False)

    def resume(self):
        """Restart the looping sounds suspended by :meth:`pause`."""
        self.app.sfxManagerList[0].setActive(True)

    def stop_level_sounds(self):
        """
        Stop and release every pooled sound still in use, and remove the
        ad-hoc sound nodes left under the camera. Run on level exit: the
        scheduled releases (delayed methods) are dropped with the level, and
        the pools and the camera outlive it.
        """
        for asset in self.app.asset_manager.assets.values():
            if isinstance(asset, SoundPool):
                for sound in asset.in_use_sounds():
                    self.audio3d.detachSound(sound)
                asset.release_all()
        # No camera headless (nor any sound node under it)
        if self.app.camera is not None:
            for node in self.app.camera.findAllMatches("player_hit_sound_node"):
                node.removeNode()

    def _play_pooled(
        self,
        game: FlightState,
        sound_pool: SoundPool,
        volume: float,
        release_name: str,
        randomize_pitch: bool,
        node: NodePath | None = None,
        velocity_source: Pawn | SubSystem | None = None,
    ):
        """
        Draw a sound from a pool, play it, and schedule its release back to the
        pool once it is surely over.

        :param game: The game object (its delayed methods release the sound)
        :param sound_pool: The pool to draw the sound from
        :param volume: The sound volume
        :param release_name: Name of the scheduled release
        :param randomize_pitch: Whether to draw the sound at a random pitch
        :param node: The node to attach the 3D sound to, or None to play it as is
        :param velocity_source: Object whose ``speed`` drives the Doppler shift
            of an attached sound (see :meth:`attach_sound`), or None
        """
        sound = sound_pool.get_sound(randomize_pitch=randomize_pitch)
        if node is not None:
            self.attach_sound(sound, node, velocity_source=velocity_source)
        sound.setVolume(volume)
        sound.play()
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name=release_name,
            method=sound_pool.release_sound,
            extra_args=[sound],
        )

    def _temp_sound_node(
        self, game: FlightState, relative_hit_point: np.ndarray
    ) -> NodePath:
        """
        Create an ad-hoc dummy node to place a sound, removed in the near future

        :param game: The game object (its delayed methods remove the node)
        :param relative_hit_point: The node position relative to the player,
            applied in the camera's frame (the node is parented to it)
        :return: The dummy node
        """
        dummy_node = self.app.camera.attachNewNode("player_hit_sound_node")
        dummy_node.setPos(*relative_hit_point)
        game.delayed_methods.do_method_later(
            delay_s=SFX_MAX_SOUND_DURATION_S,
            name="remove_player_hit_sound_node",
            method=dummy_node.remove_node,
        )
        return dummy_node

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
        self,
        game: FlightState,
        player_ship_pos: np.ndarray,
        hit_pos: np.ndarray,
        impact_type: str,
        is_player: bool = False,
    ):
        """
        Play an impact sound where the impact took place

        TODO: add pitch randomness for variation ?

        :param game: The game object
        :param player_ship_pos: The location of the player
        :param hit_pos: The location of impact
        :param impact_type: The type of impact (target, terrain, etc.)
        :param is_player: Whether the player's own shot caused this impact
            (PLAYER_DISTANT_IMPACT_VOLUME, else NPC_DISTANT_IMPACT_VOLUME)

        """
        # No one to hear it, and no camera to hang a 3D sound off of, headless.
        if game.headless:
            return
        # Set the volume according to the distance from the impact to the player
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
        shooter_multiplier = (
            PLAYER_DISTANT_IMPACT_VOLUME if is_player else NPC_DISTANT_IMPACT_VOLUME
        )

        self._play_pooled(
            game,
            sound_pool,
            volume=volume * multiplier * shooter_multiplier,
            release_name="Release distant impact sound",
            randomize_pitch=False,
        )

    def tractor_beam_grab(self, game: FlightState):
        """
        Placeholder cue for a tractor beam locking onto the player (only logs).

        TODO: play a looping tractor-beam hum for the duration of the grab.

        :param game: The game object
        """
        LOGGER.info("Tractor beam locked onto the player (placeholder SFX)")

    def tractor_beam_release(self, game: FlightState):
        """
        Placeholder cue for a tractor beam releasing the player (only logs).

        TODO: play a release sound and stop the grab hum of tractor_beam_grab.

        :param game: The game object
        """
        LOGGER.info("Tractor beam released the player (placeholder SFX)")

    def laser_impact_hit_on_player(
        self, game: FlightState, relative_hit_point: np.ndarray, is_shield: bool
    ):
        """
        Play a random impact sound where the impact took place

        :param game: The game object
        :param relative_hit_point: The hit position relative to the player,
            applied in the camera's frame (the dummy node is parented to it)
        :param is_shield: Whether the player's shield is active
        """
        # No one to hear it, and no camera to hang a 3D sound off of, headless.
        if game.headless:
            return
        if is_shield:
            sound_pool = self.player_shield_laser_hit_sound_pool
        else:
            sound_pool = self.player_hull_laser_hit_sound_pool
        dummy_node = self._temp_sound_node(game, relative_hit_point)
        self._play_pooled(
            game,
            sound_pool,
            volume=PLAYER_HIT_SOUND_MULTIPLIER,
            release_name="Release Laser impact on player sound",
            randomize_pitch=True,
            node=dummy_node,
            velocity_source=game.player.pawn,
        )

    def player_crash(
        self, game: FlightState, relative_hit_point: np.ndarray, in_terrain: bool
    ):
        """
        Play a random impact sound where the impact took place
        Blend a random long and a random short crash sound
        If the crash is in terrain, add rock impact sound

        :param game: The game object
        :param relative_hit_point: The hit position relative to the player,
            applied in the camera's frame (the dummy node is parented to it)
        :param in_terrain: Whether the player has crashed into terrain
        """
        # No one to hear it, and no camera to hang a 3D sound off of, headless.
        if game.headless:
            return
        dummy_node = self._temp_sound_node(game, relative_hit_point)
        # Terrain hit sound if crash in terrain, then the short and long crash
        # sounds, in this order
        pools = [
            (self.player_crash_short_sound_pool, "Release player crash short sound"),
            (self.player_crash_long_sound_pool, "Release player crash long sound"),
        ]
        if in_terrain:
            pools.insert(
                0, (self.terrain_hit_sound_pool, "Release player crash terrain sound")
            )
        for sound_pool, release_name in pools:
            self._play_pooled(
                game,
                sound_pool,
                volume=PLAYER_HIT_SOUND_MULTIPLIER,
                release_name=release_name,
                randomize_pitch=True,
                node=dummy_node,
                velocity_source=game.player.pawn,
            )

    def cannon_fire(
        self,
        game: FlightState,
        sound_pool: SoundPool,
        node: NodePath,
        velocity_source: Pawn | SubSystem | None = None,
        is_player: bool = False,
    ):
        """
        Play the cannon firing sound at the cannon's location

        :param game: The game object
        :param sound_pool: The sound pool from which to draw the sound
        :param node: The node to attach the sound to
        :param velocity_source: The firing actor (its ``speed`` drives the
            Doppler shift), or None
        :param is_player: Whether the player's own cannon fired the shot
            (PLAYER_CANNON_FIRE_VOLUME, else NPC_CANNON_FIRE_VOLUME)
        """
        # No one to hear it, headless.
        if game.headless:
            return
        self._play_pooled(
            game,
            sound_pool,
            volume=PLAYER_CANNON_FIRE_VOLUME if is_player else NPC_CANNON_FIRE_VOLUME,
            release_name="Release player crash sound",
            randomize_pitch=True,
            node=node,
            velocity_source=velocity_source,
        )

    def update_task(self, task: Task) -> int:
        self.audio3d.update()
        return task.cont
