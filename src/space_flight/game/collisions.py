from __future__ import annotations

import logging
import random
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeAlias

import numpy as np
from panda3d.core import (
    BitMask32,
    CollisionBox,
    CollisionEntry,
    CollisionHandlerEvent,
    CollisionHandlerQueue,
    CollisionNode,
    CollisionPlane,
    CollisionSegment,
    CollisionSolid,
    CollisionSphere,
    CollisionTraverser,
    CollisionTube,
    LPoint3,
    NodePath,
    Plane,
    Vec3,
)

from space_flight import DEBUG_COLLISION
from space_flight.fx import spark_fx
from space_flight.game.kills import DamageSource, credit_hit
from space_flight.global_architecture.gameplay_settings import gameplay_config
from space_flight.utils import magnitude
from space_flight.weapons import ION, PHYSICAL

if TYPE_CHECKING:
    from space_flight.actors.major_ship.shield import Shield
    from space_flight.actors.major_ship.sub_system import SubSystem
    from space_flight.actors.ship import Ship
    from space_flight.ai.collision_sensor import CollisionSensor
    from space_flight.game.flight_state import FlightState
    from space_flight.scenes.asteroid_field import AsteroidField
    from space_flight.scenes.ocean import Ocean
    from space_flight.weapons import Munition

    # Any object that can own a collider (stored as its "owner" python tag).
    ColliderOwner: TypeAlias = (
        Ship | SubSystem | Shield | Ocean | AsteroidField | Munition | CollisionSensor
    )
    # Owners that are part of a vehicle (the share-vehicle / hit-velocity logic
    # only ever sees ships, their subsystems, and their shields).
    VehicleOwner: TypeAlias = Ship | SubSystem | Shield

SOLID_COLLISION_ELASTICITY = 0.3  # 0 = inelastic, 1 = elastic
POSITION_CORRECTION_RATIO = 0.1
PENETRATION_TOLERANCE_M = 0.1
# Collision damage per squared normal relative velocity. The player's is scaled
# by a gameplay setting (see CollisionSystem.collision_damage)
COLLISION_DAMAGE_FACTOR = 0.05

#: Fraction of destructible (hull) hits that also spawn a small secondary
#: explosion on top of the sparks. Knob — set to 0 to disable, 1 for every hit.
HIT_EXPLOSION_CHANCE = 1.0 / 3.0

#: Terrain material → spark preset. Each terrain object declares a material
#: attribute (e.g. Ocean.material == "water", AsteroidField.material ==
#: "rock"); water reads as ice, rock as gray-brown, metal as metal. Terrain
#: with no/unknown material falls back to rock.
_TERRAIN_SPARK_PRESET = {
    "water": spark_fx.ICE,
    "rock": spark_fx.ROCK,
    "metal": spark_fx.METAL,
}

LOGGER = logging.getLogger()

#: Collision event -> the CollisionSystem method handling it. A ship still
#: touching something from a previous frame ("again") is only pushed back.
_EVENT_HANDLERS = {
    # Weapon hit = one time events
    "laser-into-ship": "munition_into_destructible",
    "laser-into-terrain": "munition_into_terrain",
    "laser-into-turret": "munition_into_destructible",
    "laser-into-subsystem": "munition_into_destructible",
    "laser-into-shield": "munition_into_shield",
    # Ordnance hits reuse the laser damage handlers (same projectile
    # interface), and are stopped by flares.
    "ordnance-into-ship": "munition_into_destructible",
    "ordnance-into-terrain": "munition_into_terrain",
    "ordnance-into-turret": "munition_into_destructible",
    "ordnance-into-subsystem": "munition_into_destructible",
    "ordnance-into-shield": "munition_into_shield",
    "ordnance-into-flare": "ordnance_into_flare",
    # Collision physics = detected at each frame
    "ship-into-ship": "ship_into_ship",
    "ship-again-ship": "ship_into_ship_pushback",
    "ship-into-terrain": "ship_into_terrain",
    "ship-again-terrain": "ship_into_terrain_pushback",
    "ship-into-turret": "ship_into_massive_actor",
    "ship-again-turret": "ship_into_massive_actor_pushback",
    "ship-into-subsystem": "ship_into_subsystem",
    "ship-again-subsystem": "ship_into_subsystem_pushback",
}


class CollisionLayers:
    MUNITION = BitMask32.bit(0)
    SENSOR = BitMask32.bit(0)
    SHIELD = BitMask32.bit(1)
    DESTRUCTIBLE = BitMask32.bit(2)
    ENVIRONMENT = BitMask32.bit(3)
    DECOY = BitMask32.bit(4)

    # Munitions hit environment, destructibles and shields
    # Nothing hits them
    MUNITION_FROM = DESTRUCTIBLE | ENVIRONMENT | SHIELD
    MUNITION_INTO = BitMask32.allOff()

    # Ordnance (bombs, rockets, missiles) are munitions that decoys (flares) also
    # stop. Nothing hits them.
    ORDNANCE_FROM = MUNITION_FROM | DECOY
    ORDNANCE_INTO = BitMask32.allOff()

    # A decoy (flare) never initiates collisions: only ordnance hits it, so two
    # flares never collide, and lasers, sensors and ships pass through.
    DECOY_FROM = BitMask32.allOff()
    DECOY_INTO = DECOY

    # Same for sensors
    SENSOR_FROM = DESTRUCTIBLE | ENVIRONMENT
    SENSOR_INTO = BitMask32.allOff()

    # Destructibles hit environment and other destructibles.
    # They are only hit by munitions, sensors and other destructibles
    DESTRUCTIBLE_FROM = DESTRUCTIBLE | ENVIRONMENT
    DESTRUCTIBLE_INTO = MUNITION | SENSOR | DESTRUCTIBLE

    # Terrain cannot hit anything
    # It is hit by munitions, sensors and destructibles
    TERRAIN_FROM = BitMask32.allOff()
    TERRAIN_INTO = MUNITION | SENSOR | DESTRUCTIBLE

    # Subsystems are chunks bolted onto a ship (shield generators, turrets...).
    # Like terrain they never initiate collisions (they are rigid parts of their
    # parent ship), they are only hit. They carry their own name so that ship
    # collisions push the *parent* ship rather than the subsystem itself.
    SUBSYSTEM_FROM = BitMask32.allOff()
    SUBSYSTEM_INTO = MUNITION | SENSOR | DESTRUCTIBLE

    # A shield bubble is a barrier only munitions interact with: ships, sensors and
    # other destructibles fly straight through it (their from-masks lack SHIELD),
    # and it never initiates collisions itself. Whether a munition is blocked or
    # passes is decided in munition_into_shield, from its launch point.
    SHIELD_FROM = BitMask32.allOff()
    SHIELD_INTO = SHIELD

    @staticmethod
    def define_collision_masks(collider_type: str) -> tuple[BitMask32, BitMask32, bool]:
        """
        Defines the from and into values of collider given its type

        :param collider_type: The type of collider
        :return: Its from and into mask bits, and whether to add said collider to
            the collision handler
        """
        try:
            return _COLLIDER_MASKS[collider_type]
        except KeyError:
            raise ValueError(f"Unknown collider type {collider_type}") from None


#: Collider type -> its from and into mask bits, and whether to add it to the
#: collision handler (see CollisionLayers.define_collision_masks)
_COLLIDER_MASKS = {
    "laser": (CollisionLayers.MUNITION_FROM, CollisionLayers.MUNITION_INTO, True),
    "ordnance": (CollisionLayers.ORDNANCE_FROM, CollisionLayers.ORDNANCE_INTO, True),
    "flare": (CollisionLayers.DECOY_FROM, CollisionLayers.DECOY_INTO, False),
    "sensor": (CollisionLayers.SENSOR_FROM, CollisionLayers.SENSOR_INTO, True),
    "destructible": (
        CollisionLayers.DESTRUCTIBLE_FROM,
        CollisionLayers.DESTRUCTIBLE_INTO,
        True,
    ),
    "terrain": (CollisionLayers.TERRAIN_FROM, CollisionLayers.TERRAIN_INTO, False),
    "subsystem": (
        CollisionLayers.SUBSYSTEM_FROM,
        CollisionLayers.SUBSYSTEM_INTO,
        False,
    ),
    "shield": (CollisionLayers.SHIELD_FROM, CollisionLayers.SHIELD_INTO, False),
}


def owners_share_vehicle(
    owner_a: VehicleOwner | None, owner_b: VehicleOwner | None
) -> bool:
    """
    Whether two collision owners belong to the same vehicle and, therefore,
    should not collide with one another.

    This is the "owner" mechanic that spares a ship from colliding with the
    subsystems (shield generators, ship-mounted turrets, etc.) bolted onto it.
    A mountable exposes mounted_on: the ship it is attached to (None when
    it stands alone). Reading the owner python-tags off a collision entry,
    two owners share a vehicle when:

    - both owners are the same object,
    - one is mounted on the other (its mounted_on is the other owner),
    - both are mounted on the same ship (siblings, e.g. two subsystems).

    :param owner_a: The owner python-tag of one collider
    :param owner_b: The owner python-tag of the other collider
    :return: True if both owners belong to the same vehicle
    """
    if owner_a is None or owner_b is None:
        return False
    if owner_a is owner_b:
        return True
    host_a = getattr(owner_a, "mounted_on", None)
    host_b = getattr(owner_b, "mounted_on", None)
    # One collider is bolted onto the other
    if host_a is owner_b or host_b is owner_a:
        return True
    # Both colliders are bolted onto the same ship (siblings)
    if host_a is not None and host_a is host_b:
        return True
    return False


def _hit_velocity(obj: VehicleOwner | None) -> np.ndarray:
    """
    World velocity of a hit object, for sparks to inherit its motion.

    Ships expose their own speed; a subsystem or shield rides its mount's
    speed (mounted_on.speed); static terrain has neither, giving zero.

    :param obj: The hit object (destructible, shield, or None for terrain)
    :return: A 3-vector world velocity (zeros when the object has none)
    """
    speed = getattr(obj, "speed", None)
    if speed is None:
        mount = getattr(obj, "mounted_on", None)
        speed = getattr(mount, "speed", None) if mount is not None else None
    return np.asarray(speed, dtype=float) if speed is not None else np.zeros(3)


def _normalize(vector: Vec3) -> Vec3:
    """
    Normalise a collision normal in place: it can have a non-unit length if a
    parent object was scaled. It's dumb, but it is what it is... A null vector
    is left null.

    :param vector: The vector to normalise
    :return: The same vector
    """
    if not vector.almostEqual(Vec3(0, 0, 0)):
        vector.normalize()
    return vector


def _immovable_bounce(normal: Vec3, normal_relative_velocity: float) -> np.ndarray:
    """
    Velocity correction bouncing a ship off something that does not move in
    response (terrain, a massive actor), if the two are still approaching.

    :param normal: The unit contact normal, pointing towards the ship
    :param normal_relative_velocity: The relative velocity along the normal
    :return: The ship's velocity correction (zeros when separating)
    """
    if normal_relative_velocity < 0:
        return np.array(
            -normal * (1 + SOLID_COLLISION_ELASTICITY) * normal_relative_velocity
        )
    return np.zeros(3)


class CollisionSystem:
    def __init__(self, game: FlightState):
        """
        Set up the collision traverser and register the collision-event handlers.

        :param game: The game whose render tree is traversed for collisions.
        """
        self.game = game
        # Read once per level, like every gameplay setting
        self.player_collision_damage_multiplier = gameplay_config(game)["player"][
            "collision_damage_multiplier"
        ]
        self.traverser = CollisionTraverser()
        if DEBUG_COLLISION:
            self.traverser.showCollisions(self.game.app.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern("%fn-into-%in")
        self.handler.addAgainPattern("%fn-again-%in")
        # Collision sensors report ~100 contacts per frame: read them straight
        # from a queue after each traverse (see update_collisions), rather than
        # routing each one through Panda3D's event messenger
        self.sensor_queue = CollisionHandlerQueue()

        for event, method_name in _EVENT_HANDLERS.items():
            self.game.app.accept(event, getattr(self, method_name))

    def collision_damage(self, ship: Ship, normal_relative_velocity: float) -> float:
        """
        :param ship: The ship taking the damage
        :param normal_relative_velocity: The impact's relative velocity along the
            contact normal
        :return: The collision damage the ship takes: scaled by the player's
            collision damage multiplier if it is the player's ship
        """
        damage = COLLISION_DAMAGE_FACTOR * normal_relative_velocity**2
        if self.game.player is not None and ship is self.game.player.pawn:
            damage *= self.player_collision_damage_multiplier
        return damage

    def update_collisions(self):
        """
        Computes collisions via panda3d internal methods: it triggers the
        "%fn-into-%in" / "%fn-again-%in" events, and fills the sensor queue,
        whose contacts are handled right away.
        """
        self.traverser.traverse(self.game.app.render)
        for entry in self.sensor_queue.entries:
            self.sensor_into_obstacle(entry)

    def _world_normal(self, entry: CollisionEntry) -> Vec3:
        """
        :param entry: Panda3d's description of a collision
        :return: The unit (or null) surface normal, in world space
        """
        return _normalize(entry.getSurfaceNormal(self.game.root_node))

    def _distant_impact(
        self, entry: CollisionEntry, munition: Munition, impact_type: str
    ):
        """
        Play the impact sound of a munition landing away from the player.

        :param entry: Panda3d's description of the collision
        :param munition: The munition that hit
        :param impact_type: "target" or "terrain"
        """
        self.game.app.sfx.distant_impact_hit(
            game=self.game,
            player_ship_pos=self.game.player.pawn.position,
            hit_pos=entry.into_node_path.parent.getPos(),
            impact_type=impact_type,
            is_player=munition.origin_ship_id == self.game.player.pawn.id,
        )

    def munition_into_destructible(self, entry: CollisionEntry):
        """
        Handles the case where a munition hits a destructible object:
        Damages the destructible object and remove the munition.

        :param entry: Panda3d's description of the collision
        """
        munition = entry.from_node_path.python_tags["owner"]
        destructible = entry.into_node_path.python_tags["owner"]

        if munition is None:
            if DEBUG_COLLISION:
                LOGGER.info(
                    "munition juuuuust out of range and being removed while it hits. "
                    "Ignoring."
                )
            return
        if destructible is None:
            if DEBUG_COLLISION:
                LOGGER.info("destructible being removed while it hits. Ignoring.")
            return

        # The munition has met its own emitter => no "real" collision
        try:
            destructible_id = destructible.id
        except AttributeError:
            destructible_id = ""
        if munition.origin_ship_id == destructible_id:
            return
        # A munition never hits the vehicle it was fired from: not the emitter's
        # ship, nor a sibling subsystem (so a ship-mounted turret cannot shoot its
        # own hull, generators or other turrets).
        if owners_share_vehicle(munition.origin_ship, destructible):
            return

        if DEBUG_COLLISION:
            LOGGER.info("munition into destructible")

        # Apply damage to the destructible object
        normal = entry.getSurfaceNormal(self.game.root_node)
        if normal.almostEqual(Vec3(0, 0, 0)) and isinstance(
            entry.getInto(), CollisionBox
        ):
            normal = self._box_face_normal(entry)
        _normalize(normal)

        # Was the target's shield still up when the shot landed? Fighters carry a
        # scalar shield. Read it BEFORE take_hit spends the shield, so a shielded
        # hit sparks blue (ICE) rather than the hull's metal sparks. A major ship's
        # shield is its bubble instead (its shield_level is the bubble's strength),
        # stopping hits in munition_into_shield: a shot reaching its hull got past
        # the bubble (fired from inside, or the bubble is down), so it strikes
        # bare metal.
        target_shield_up = (
            getattr(destructible, "category", None) != "capital_ship"
            and getattr(destructible, "shield_level", 0.0) > 0.0
        )

        credit_hit(destructible, munition.source)
        destructible.take_hit(
            damage=munition.power,
            normal_world_vector=normal,
            damage_type=munition.damage_type,
        )

        # Spend the munition
        munition.on_impact()

        # Apply hit effect depending on player or bot
        if destructible_id == self.game.player.pawn.id:
            relative_hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            self.game.player.play_impact_sound(
                relative_hit_point=relative_hit_point, kind="laser"
            )
            # Directional, laser-coloured cockpit hit flash (display-only; no-op
            # headless). The shot's velocity is its incoming direction; bombs
            # carry no colour, so on_laser_hit falls back to a default tint.
            self.game.player.on_laser_hit(
                incoming_world_dir=munition.speed,
                color=getattr(munition, "color", None),
            )
        else:
            # TODO: Mute bots shooting on bots ?
            self._distant_impact(entry, munition, "target")
            hit_point = entry.getSurfacePoint(self.game.root_node)
            hit_velocity = _hit_velocity(destructible)
            # Electric sparks for an ion hit; else blue ice sparks off a
            # still-raised shield, metal sparks off bare hull. All inherit the
            # target's motion.
            is_ion = munition.damage_type == ION
            if is_ion:
                preset = spark_fx.ION
            elif target_shield_up:
                preset = spark_fx.ICE
            else:
                preset = spark_fx.METAL
            self.game.spark_fx_pool.spawn(
                position=hit_point,
                normal=normal,
                base_velocity=hit_velocity,
                preset=preset,
            )
            # Occasionally add a small secondary explosion for extra punch (not
            # for ion hits, which harm no hull).
            if not is_ion and random.random() < HIT_EXPLOSION_CHANCE:
                self.game.fire_smoke_pool.hit_burst(
                    position=hit_point,
                    normal=normal,
                    base_velocity=hit_velocity,
                )

    def munition_into_terrain(self, entry: CollisionEntry):
        """
        Handles the case where a munition hits a terrain object:
        Removes the munition and throws sparks at the impact point, picking the
        spark preset from the terrain's material (defaulting to ROCK).

        :param entry: Panda3d's description of the collision
        """
        if DEBUG_COLLISION:
            LOGGER.info("munition into terrain")
        munition = entry.from_node_path.python_tags["owner"]

        if munition is None:
            if DEBUG_COLLISION:
                LOGGER.info(
                    "munition juuuuust out of range and being removed while it hits. "
                    "Ignoring."
                )
            return

        self._distant_impact(entry, munition, "terrain")

        # Sparks coloured by the terrain type (water → ice, rock → gray-brown).
        # Terrain is static, so no inherited velocity. An infinite-plane terrain
        # collider reports a surface normal but not always a surface point, so
        # fall back to the munition's own position/direction when either is missing.
        if entry.hasSurfaceNormal():
            normal = entry.getSurfaceNormal(self.game.root_node)
        else:
            normal = Vec3(-munition.speed[0], -munition.speed[1], -munition.speed[2])
        _normalize(normal)
        if entry.hasSurfacePoint():
            hit_point = entry.getSurfacePoint(self.game.root_node)
        else:
            hit_point = munition.impact_position()
        terrain = entry.into_node_path.python_tags["owner"]
        material = getattr(terrain, "material", None)
        preset = _TERRAIN_SPARK_PRESET.get(material, spark_fx.ROCK)
        self.game.spark_fx_pool.spawn(
            position=hit_point,
            normal=normal,
            base_velocity=np.zeros(3),
            preset=preset,
        )

        # Spend the munition
        munition.on_impact()

    def ordnance_into_flare(self, entry: CollisionEntry):
        """
        Handles the case where an ordnance hits a flare: both are spent, unless
        the flare was dropped by the ordnance's own team.

        :param entry: Panda3d's description of the collision
        """
        ordnance = entry.from_node_path.python_tags["owner"]
        flare = entry.into_node_path.python_tags["owner"]
        if ordnance is None or flare is None:
            # One of them was already spent this frame
            return
        if ordnance.team == flare.team:
            return

        if DEBUG_COLLISION:
            LOGGER.info("ordnance into flare")
        ordnance.on_impact()
        flare.on_impact()

    def _box_face_normal(self, entry: CollisionEntry) -> Vec3:
        """
        The outward normal of the box face a collision point lies on, in world
        space. Panda3d reports a zero normal for a segment (a laser) struck on
        some faces of a box, its hit point lying a float rounding off the face.

        :param entry: Panda3d's description of a collision into a CollisionBox
        :return: The world-space face normal
        """
        box = entry.getInto()
        into_np = entry.getIntoNodePath()
        # The hit point in box units: the face it lies on is the axis where it
        # reaches out furthest (|coordinate| close to 1)
        offset = entry.getSurfacePoint(into_np) - box.getCenter()
        half_extents = (box.getMax() - box.getMin()) * 0.5
        scaled = [
            offset[i] / half_extents[i] if half_extents[i] > 0 else 0.0
            for i in range(3)
        ]
        axis = max(range(3), key=lambda i: abs(scaled[i]))
        local_normal = Vec3(0, 0, 0)
        local_normal[axis] = 1.0 if scaled[axis] >= 0.0 else -1.0
        return self.game.root_node.getRelativeVector(into_np, local_normal)

    def munition_into_shield(self, entry: CollisionEntry):
        """
        Handle a munition crossing a shield bubble.

        A munition fired from *outside* the shield impacts it (and is absorbed); a
        munition fired from *inside* passes straight through, so a ship sheltering
        in the bubble can still shoot out (and at the hull).

        The two are told apart by the munition's launch point: inside the bubble
        (as it is now) -> it passes through. Panda3d also reports a munition
        lying wholly inside the bubble, every frame, with a normal that tells
        nothing about where it came from, and the event is handled a frame
        late, once the munition has moved on: the launch point is the one thing
        that does not move. The bubble's ship is slow next to a munition, so it
        has barely moved since the launch.

        :param entry: Panda3d's description of the collision
        """
        munition = entry.from_node_path.python_tags["owner"]
        shield = entry.into_node_path.python_tags["owner"]

        if munition is None:
            if DEBUG_COLLISION:
                LOGGER.info(
                    "munition juuuuust out of range and being removed while it hits. "
                    "Ignoring."
                )
            return
        if shield is None:
            if DEBUG_COLLISION:
                LOGGER.info("shield being removed while it is hit. Ignoring.")
            return

        # A turret sitting inside its ship's bubble must not hit that bubble: the
        # launch-point rule below already lets a shot fired from inside pass,
        # but skip the emitter's own vehicle outright to be unambiguous.
        if owners_share_vehicle(munition.origin_ship, shield):
            return

        # A downed (disabled) shield stops nothing
        if not shield.is_enabled:
            return

        # A munition fired from inside the bubble passes through (see docstring)
        if shield.contains(munition.launch_position):
            return

        normal = self._world_normal(entry)

        if DEBUG_COLLISION:
            LOGGER.info("munition into shield")

        # The shield absorbs the hit. Pass the world-space impact point so the
        # bubble can flash where the munition struck.
        hit_point = entry.getSurfacePoint(self.game.root_node)
        shield.take_hit(
            damage=munition.power,
            normal_world_vector=normal,
            hit_world_point=hit_point,
            damage_type=munition.damage_type,
        )

        # Ice sparks (electric ones for an ion hit) where the munition struck
        # the bubble, on top of the shield's own impact flash (driven from
        # take_hit). They ride the ship's motion.
        self.game.spark_fx_pool.spawn(
            position=hit_point,
            normal=normal,
            base_velocity=_hit_velocity(shield),
            preset=spark_fx.ION if munition.damage_type == ION else spark_fx.ICE,
        )

        # Spend the munition
        munition.on_impact()

        # Impact feedback
        self._distant_impact(entry, munition, "target")

    def _ship_contact(
        self,
        entry: CollisionEntry,
        pushback: Callable[[CollisionEntry], None],
        into_label: str,
        *,
        in_terrain: bool = False,
        check_same_vehicle: bool = True,
    ):
        """
        Handle a ship's first contact with something solid: push it back and, if
        it is the player's, play a crash sfx. Terrain pushes back before the
        sound, everything else after it.

        :param entry: Panda3d's description of the collision
        :param pushback: The pushback method for this kind of contact (also the
            handler of the "again" events that follow)
        :param into_label: What the ship hits, for debug logs
        :param in_terrain: Whether the ship hits terrain (picks the crash sfx)
        :param check_same_vehicle: Skip contacts with the ship's own vehicle (a
            ship never collides with its own subsystems, nor they with each
            other: see owners_share_vehicle)
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_from being removed while it hits. Ignoring.")
            return
        if into is None:
            if DEBUG_COLLISION:
                LOGGER.info(f"{into_label} being removed while it hits. Ignoring.")
            return
        if check_same_vehicle and owners_share_vehicle(ship_from, into):
            return

        if DEBUG_COLLISION:
            LOGGER.info(f"ship into {into_label}")
            LOGGER.info(f"ship from : {ship_from.id}")

        def crash_sound():
            # Play SFX for player only
            if ship_from.id == self.game.player.pawn.id:
                relative_hit_point = entry.getSurfacePoint(entry.getFromNodePath())
                self.game.app.sfx.player_crash(
                    game=self.game,
                    relative_hit_point=relative_hit_point,
                    in_terrain=in_terrain,
                )

        if in_terrain:
            pushback(entry)
            crash_sound()
        else:
            crash_sound()
            pushback(entry)

    def ship_into_terrain(self, entry: CollisionEntry):
        """
        Handles the case where a ship hits immobile terrain for the first time

        :param entry: Panda3d's description of the collision
        """
        self._ship_contact(
            entry,
            self.ship_into_terrain_pushback,
            "terrain",
            in_terrain=True,
            check_same_vehicle=False,
        )

    def ship_into_terrain_pushback(self, entry: CollisionEntry):
        """
        Handle the case where a ship hits immobile terrain.
        We don't use collision forces because they are too stiff.
        Instead, we use impulse correction

        TODO use new collision spheres the real size of the ships ? Maybe not necessary
        if we use auto-aim and can reduce the hitboxes

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        terrain_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            return
        if terrain_into is None:
            return

        # Get impact parameters
        normal = self._world_normal(entry)
        normal_relative_velocity = np.dot(normal, ship_from.speed)

        # Compute impulse correction
        velocity_correction = _immovable_bounce(normal, normal_relative_velocity)
        # Position correction is too complicated to compute with arbitrary mesh
        # => Rely only on elastic impact to push back

        # Apply damage to the ship. A damaging crash is no one's hit: it is
        # stamped as such, so neither a crash death nor a mere scrape is put down
        # to whoever last shot the ship (a wreck keeps its killer, see
        # credit_hit).
        damage = self.collision_damage(ship_from, normal_relative_velocity)
        if damage > 0.0:
            credit_hit(ship_from, source=None, cause="crash")
        ship_from.push(
            damage=damage,
            velocity_correction=velocity_correction,
            position_correction=np.zeros(3),
        )

    def ship_into_ship(self, entry: CollisionEntry):
        """
        Handle the case where a ship hits another ship for the first time

        :param entry: Panda3d's description of the collision
        """
        self._ship_contact(entry, self.ship_into_ship_pushback, "ship")

    def ship_into_ship_pushback(self, entry: CollisionEntry):
        """
        Handle the case where a ship hits another ship:
        The collision is registered on both sides.
        So: hit only the "into" node. The other side of the collision
        will receive its damage when the inverse collision is handled.

        We don't use collision forces because they are too stiff.
        Instead, we use impulse and position correction

        TODO use new collision spheres the real size of the ships ? Maybe not necessary
        if we use auto-aim and can reduce the hitboxes

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        ship_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            return
        if ship_into is None:
            return

        # Get impact parameters
        # Normal and penetration depth from ship positions directly (assumed spherical)
        relative_position = ship_from.position - ship_into.position
        distance_m = magnitude(relative_position)
        if distance_m < 1e-4:
            # Objects are so close that we are better off waiting for a more favorable
            # situation
            return
        normal = relative_position / distance_m
        penetration_depth_m = max(  # Sometimes small numerical errors cause < 0
            -(distance_m - ship_from.hit_box_radius_m - ship_into.hit_box_radius_m), 0.0
        )
        relative_velocity = ship_from.speed - ship_into.speed
        normal_relative_velocity = np.dot(normal, relative_velocity)
        mass_from_kg = ship_from.mass_kg
        mass_into_kg = ship_into.mass_kg
        denominator = 1 + mass_into_kg / mass_from_kg
        # Compute impulse correction
        # Push back if objects are still approaching
        if normal_relative_velocity < 0:
            velocity_correction = (  # correction impulse / self mass
                normal
                * (1 + SOLID_COLLISION_ELASTICITY)
                * normal_relative_velocity
                / denominator
            )
        else:
            velocity_correction = np.zeros(3)
        # Compute position correction.
        # Not a big correction in most cases, but limits penetration.
        position_correction = (
            -normal
            * POSITION_CORRECTION_RATIO
            * max(penetration_depth_m - PENETRATION_TOLERANCE_M, 0)
            / denominator
        )

        # Apply damage to the destructible objects
        credit_hit(ship_into, DamageSource.of(ship_from, self.game), cause="ram")
        ship_into.push(
            damage=self.collision_damage(ship_into, normal_relative_velocity),
            velocity_correction=velocity_correction,
            position_correction=position_correction,
        )

    def ship_into_massive_actor(self, entry: CollisionEntry):
        """
        Handle the case where a ship hits a massive actor for the first time

        :param entry: Panda3d's description of the collision
        """
        self._ship_contact(
            entry,
            self.ship_into_massive_actor_pushback,
            "massive actor",
            check_same_vehicle=False,
        )

    def ship_into_massive_actor_pushback(self, entry: CollisionEntry):
        """
        Handle the case where a ship hits massive actor.
        We don't use collision forces because they are too stiff.
        Instead, we use impulse correction

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        massive_actor_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            return
        if massive_actor_into is None:
            return

        # Get impact parameters
        normal = self._world_normal(entry)
        relative_velocity = ship_from.speed - massive_actor_into.speed
        normal_relative_velocity = np.dot(normal, relative_velocity)

        # Compute impulse correction
        velocity_correction = _immovable_bounce(normal, normal_relative_velocity)
        # Position correction is too complicated to compute with arbitrary mesh
        # => Rely only on elastic impact to push back

        # Apply damage to the ship
        ship_from.push(
            damage=self.collision_damage(ship_from, normal_relative_velocity),
            velocity_correction=velocity_correction,
            position_correction=np.zeros(3),
        )
        # Apply damage to the massive actor (never the player's, so unscaled)
        massive_actor_into.apply_damage(
            damage=COLLISION_DAMAGE_FACTOR * normal_relative_velocity**2,
            damage_type=PHYSICAL,
        )

    def ship_into_subsystem(self, entry: CollisionEntry):
        """
        Handle a ship hitting a subsystem for the first time

        :param entry: Panda3d's description of the collision
        """
        self._ship_contact(entry, self.ship_into_subsystem_pushback, "subsystem")

    def ship_into_subsystem_pushback(self, entry: CollisionEntry):
        """
        Resolve a ship hitting a subsystem bolted onto another ship.

        The subsystem is rigid, so it is never pushed: the momentum exchange
        happens between the incoming ship and the subsystem's *parent* ship, whose
        speed and mass the subsystem stands in for. Both are pushed apart, split by
        mass, so a heavy parent barely moves while the incoming ship takes the
        recoil. The collision damage, however, is dealt to the subsystem itself,
        never to its parent ship.

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        subsystem_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None or subsystem_into is None:
            return
        if owners_share_vehicle(ship_from, subsystem_into):
            return

        # The ship the subsystem is bolted onto: it carries the kinematics
        host = subsystem_into.mounted_on
        if host is None:
            return

        # Impact normal from the actual geometry (robust to the subsystem's own
        # position lagging its moving hull). It points out of the subsystem,
        # i.e. roughly towards the incoming ship.
        normal = self._world_normal(entry)

        # The subsystem is rigid, so its kinematics are its host ship's
        relative_velocity = ship_from.speed - host.speed
        normal_relative_velocity = np.dot(normal, relative_velocity)
        mass_from_kg = ship_from.mass_kg
        mass_host_kg = host.mass_kg

        # Push apart only if still approaching. Impulse is split by mass (a heavy
        # host barely moves; the incoming ship takes most of the recoil).
        if normal_relative_velocity < 0:
            impulse = (1 + SOLID_COLLISION_ELASTICITY) * normal_relative_velocity
            # -normal pushes the incoming ship away; +normal recoils the host.
            ship_velocity_correction = np.array(
                -normal * impulse / (1 + mass_from_kg / mass_host_kg)
            )
            host_velocity_correction = np.array(
                normal * impulse / (1 + mass_host_kg / mass_from_kg)
            )
        else:
            ship_velocity_correction = np.zeros(3)
            host_velocity_correction = np.zeros(3)

        # Push the incoming ship back (and damage it)...
        ship_from.push(
            damage=self.collision_damage(ship_from, normal_relative_velocity),
            velocity_correction=ship_velocity_correction,
            position_correction=np.zeros(3),
        )
        # ...and recoil the host ship it rammed, but deal it no damage: the
        # subsystem absorbs the hit instead.
        host.push(
            damage=0.0,
            velocity_correction=host_velocity_correction,
            position_correction=np.zeros(3),
        )
        # The subsystem itself takes the collision damage (never the player's,
        # so unscaled)
        credit_hit(subsystem_into, DamageSource.of(ship_from, self.game), cause="ram")
        subsystem_into.apply_damage(
            damage=COLLISION_DAMAGE_FACTOR * normal_relative_velocity**2,
            damage_type=PHYSICAL,
        )

    def sensor_into_obstacle(self, entry: CollisionEntry):
        """
        Handles the case where a sensor hits an obstacle
        Register the hit in the sensor

        :param entry: Panda3d's description of the collision
        """
        # Identify sensor and obstacle
        sensor = entry.from_node_path.python_tags["owner"]
        obstacle = entry.into_node_path.python_tags["owner"]
        if sensor is None:
            if DEBUG_COLLISION:
                LOGGER.info("Sensor is being removed while it hits")
            return

        if obstacle is None:
            if DEBUG_COLLISION:
                LOGGER.info("Obstacle is being removed while it is hit by a sensor")
            return
        try:
            if sensor.ship.id == obstacle.id:
                return  # It's the sensor's parent => Ignore collision
            # A subsystem mounted on the sensor's own ship is not an obstacle
            if owners_share_vehicle(sensor.ship, obstacle):
                return
        except AttributeError:
            pass  # When the obstacle does not have an id, it's not the sensor parent

        if DEBUG_COLLISION:
            LOGGER.info(f"sensor into obstacle: {obstacle} with id: {obstacle.id}")

        # Register collision in sensor, tagged with which look-ahead sphere saw it
        # (so the sensor can ignore the outer sphere when its reach is shortened).
        normal = entry.getSurfaceNormal(self.game.root_node)
        hit_point = entry.getSurfacePoint(self.game.root_node)
        sensor_range = entry.from_node_path.python_tags.get("sensor_range", 1)
        sensor.record_obstacle(
            {"normal": normal, "hit_point": hit_point, "range": sensor_range}
        )

    def clean(self):
        """
        Cleans the CollisionSystem object
        """
        # Clean traverser
        self.traverser.clearColliders()
        self.traverser = None
        # Clean handler
        self.handler.clearInPatterns()
        self.handler.clearOutPatterns()
        for event in _EVENT_HANDLERS:
            self.game.app.ignore(event)
        self.handler = None
        self.sensor_queue = None
        self.game = None


def _attach_solid(
    game: FlightState,
    name: str,
    solid: CollisionSolid,
    collider_type: str,
    parent_node: NodePath,
    parent_object: ColliderOwner,
) -> NodePath:
    """
    Attach a collision node holding one solid to an existing node, and register
    it in the collision handler (the sensor queue for a sensor) if its type
    initiates collisions.

    :param game: The game stage
    :param name: The name of the collision node
    :param solid: The collision solid, in the parent node's frame
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :return: The node path to the collision node
    """
    (
        from_mask_bit,
        into_mask_bit,
        add_to_collision_handler,
    ) = CollisionLayers.define_collision_masks(collider_type=collider_type)

    cnode = CollisionNode(name)
    cnode.addSolid(solid)
    # Define masks
    cnode.setFromCollideMask(from_mask_bit)
    cnode.setIntoCollideMask(into_mask_bit)
    # Attach to parent node and object
    node_path = parent_node.attachNewNode(cnode)
    node_path.setPythonTag("owner", parent_object)
    # Register in collision handler
    if add_to_collision_handler:
        handler = (
            game.collision_system.sensor_queue
            if collider_type == "sensor"
            else game.collision_system.handler
        )
        game.collision_system.traverser.addCollider(node_path, handler)

    if DEBUG_COLLISION:
        node_path.show()
    return node_path


def attach_collision_sphere(
    game: FlightState,
    name: str,
    radius: float,
    collider_type: str,
    parent_node: NodePath,
    parent_object: ColliderOwner,
    relative_position: list[float] = [0, 0, 0],
) -> NodePath:
    """
    Attach a collision sphere to an existing node.

    :param game: The game stage
    :param name: The name of the collision sphere
    :param radius: Its radius
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :param relative_position: Its position relative to the origin of its parent node
    :return: The node path to the collision sphere
    """
    solid = CollisionSphere(
        relative_position[0], relative_position[1], relative_position[2], radius
    )
    return _attach_solid(game, name, solid, collider_type, parent_node, parent_object)


def attach_collision_tube(
    game: FlightState,
    name: str,
    point_a: list[float],
    point_b: list[float],
    radius: float,
    collider_type: str,
    parent_node: NodePath,
    parent_object: ColliderOwner,
) -> NodePath:
    """
    Attach a collision tube (a capsule: a cylinder capped by two hemispheres) to
    an existing node. point_a and point_b are the centres of the two end
    hemispheres, in the parent node's frame.

    :param game: The game stage
    :param name: The name of the collision tube
    :param point_a: Centre of the first end hemisphere (x, y, z)
    :param point_b: Centre of the second end hemisphere (x, y, z)
    :param radius: The tube radius
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :return: The node path to the collision tube
    """
    solid = CollisionTube(
        point_a[0], point_a[1], point_a[2], point_b[0], point_b[1], point_b[2], radius
    )
    return _attach_solid(game, name, solid, collider_type, parent_node, parent_object)


def attach_collision_box(
    game: FlightState,
    name: str,
    center: list[float],
    half_extents: list[float],
    collider_type: str,
    parent_node: NodePath,
    parent_object: ColliderOwner,
) -> NodePath:
    """
    Attach an axis-aligned collision box (in the parent node's frame) to an
    existing node.

    :param game: The game stage
    :param name: The name of the collision box
    :param center: The box centre (x, y, z), in the parent node's frame
    :param half_extents: The box half-sizes along x, y and z
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :return: The node path to the collision box
    """
    solid = CollisionBox(
        LPoint3(center[0], center[1], center[2]),
        half_extents[0],
        half_extents[1],
        half_extents[2],
    )
    return _attach_solid(game, name, solid, collider_type, parent_node, parent_object)


def attach_collision_segment(
    game: FlightState,
    name: str,
    collider_type: str,
    parent_node: NodePath,
    parent_object: ColliderOwner,
    relative_start_position: LPoint3,
    relative_end_position: LPoint3,
) -> NodePath:
    """
    Attach a collision segment to an existing node. Great for lasers

    :param game: The game stage
    :param name: The name of the collision segment
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :param relative_start_position: Its relative start position
    :param relative_end_position: Its relative end position
    :return: The node path to the collision segment
    """
    solid = CollisionSegment(relative_start_position, relative_end_position)
    return _attach_solid(game, name, solid, collider_type, parent_node, parent_object)


def attach_collision_plane(
    game: FlightState,
    name: str,
    collider_type: str,
    parent_node: NodePath,
    parent_object: ColliderOwner,
) -> NodePath:
    """
    Attach a collision plane to an existing node facing this node's z-up

    :param game: The game stage
    :param name: The name of the collision plane
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :return: The node path to the collision plane
    """
    # Define a plane: normal + point
    plane = Plane(Vec3(0, 0, 1), Vec3(0, 0, 0))  # Z-up plane at Z=0
    return _attach_solid(
        game, name, CollisionPlane(plane), collider_type, parent_node, parent_object
    )
