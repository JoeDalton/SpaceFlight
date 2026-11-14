from __future__ import annotations

import functools
import random
import uuid
from collections.abc import Generator
from typing import TYPE_CHECKING, List

from panda3d.core import (
    BitMask32,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexWriter,
    NodePath,
    OmniBoundingVolume,
    PTA_float,
    Shader,
    TextureStage,
    TransparencyAttrib,
)

from space_flight import DATAFILES_PATH
from space_flight.fx import CORNERS, TRIS, make_particle_format
from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

MIN_DUST_ALPHA = 0.2
MAX_DUST_ALPHA = 0.8
#: A mote's half-size at scale 1, metres (its sprite's card)
MOTE_HALF_SIZE_M = 0.02
#: The distance flown is kept modulo this many depths: a float stays precise,
#: and the motes' pattern only jumps once in that many laps
TRAVEL_WRAP_DEPTHS = 4096

_SHADERS = DATAFILES_PATH / "shaders"


@functools.cache
def _dust_shader() -> Shader:
    return Shader.load(
        Shader.SL_GLSL,
        vertex=_SHADERS / "speed_dust.vert",
        fragment=_SHADERS / "speed_dust.frag",
    )


class SpeedDustCloud:
    """
    A cloud of dust sprites zooming past the player's ship, to convey its
    speed.

    The motes are animated on the GPU (speed_dust.vert): one geometry per
    colour, its quads placed from the distance flown, which is the only thing
    the CPU updates each frame.
    """

    def __init__(
        self,
        game: FlightState,
        num_particles: int = 100,
        spread: float = 30,
        depth: float = 100.0,
        colors: List = ["white"],
        *,
        defer_build: bool = False,
    ):
        self.game = game
        self.spread = spread
        self.depth = depth
        self.id = uuid.uuid4()
        self.num_particles = num_particles
        self.travel = 0.0

        # Under the player's ship: the dust moves with it
        self.root = NodePath("speedDust")
        self.root.reparentTo(self.game.player.pawn.node)
        self.root.setTransparency(TransparencyAttrib.MAlpha)
        # Make that dust independent from scene lighting
        self.root.setLightOff()
        self.root.setShader(_dust_shader())
        # Bound once, written in place each frame: no new render state
        self._travel_input = PTA_float.empty_array(1)
        self.root.setShaderInputs(
            uTravel=self._travel_input, uDepth=depth, uSpread=spread
        )
        # Dust is no obstacle
        self.root.node().setIntoCollideMask(BitMask32.allOff())

        # Get the dust's colors
        self.colors = colors
        self.particles: list[NodePath] = []

        # Build now unless the caller wants to drive build() incrementally.
        if not defer_build:
            for _ in self.build():
                pass

    def build(self, chunk: int = 25) -> Generator[None, None, None]:
        """
        Create the dust's geometry, one colour at a time, yielding after each,
        then register the per-frame update. Use with defer_build=True to spread
        the work across frames::

            self.speed_dust = SpeedDustCloud(game, defer_build=True, ...)
            yield from self.speed_dust.build()

        :param chunk: unused, kept for the callers (the motes are made in one
            geometry per colour)
        """
        motes: dict[str, list[tuple]] = {color: [] for color in self.colors}
        for _ in range(self.num_particles):
            motes[random.choice(self.colors)].append(self._random_mote())
        for color, color_motes in motes.items():
            if color_motes:
                self.particles.append(self._make_geometry(color, color_motes))
            yield

        self.max_speed = self.game.player.pawn.max_speed_mps

        # Add the update task to the game's methods
        self.game.method_lists[self.id] = [self.dust_update]

    def _random_mote(self) -> tuple:
        """:return: (x, y, z, half-size, seed) of a mote at a random place"""
        return (
            random.uniform(-self.spread, self.spread),
            random.uniform(0, self.depth),
            random.uniform(-self.spread, self.spread),
            random.uniform(0.5, 2.0) * MOTE_HALF_SIZE_M,
            random.uniform(0.0, 1000.0),
        )

    def _make_geometry(self, color: str, motes: list[tuple]) -> NodePath:
        """:return: the node of one colour's motes, a billboard quad each"""
        vdata = GeomVertexData(
            f"dust_{color}",
            make_particle_format([("size", 1), ("seed", 1)]),
            Geom.UHStatic,
        )
        vdata.setNumRows(len(motes) * 4)
        vertex = GeomVertexWriter(vdata, "vertex")
        corner = GeomVertexWriter(vdata, "corner")
        spawn = GeomVertexWriter(vdata, "spawn_time")
        size = GeomVertexWriter(vdata, "size")
        seed = GeomVertexWriter(vdata, "seed")
        triangles = GeomTriangles(Geom.UHStatic)
        for index, (x, y, z, half_size, mote_seed) in enumerate(motes):
            for cx, cy in CORNERS:
                vertex.addData3(x, y, z)
                corner.addData2(cx, cy)
                spawn.addData1(0.0)
                size.addData1(half_size)
                seed.addData1(mote_seed)
            for vertex_index in TRIS:
                triangles.addVertex(index * 4 + vertex_index)
            triangles.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(triangles)
        node = GeomNode(f"dust_{color}")
        node.addGeom(geom)
        # The shader moves the motes: never culled (they are around the ship)
        node.setBounds(OmniBoundingVolume())
        node.setFinal(True)
        path = self.root.attachNewNode(node)
        path.setTexture(
            TextureStage.getDefault(),
            self.game.app.asset_manager.get_asset(
                asset_type="texture",
                path=DATAFILES_PATH / f"sprites/dust/dust_{color}.png",
            ).get_texture(),
        )
        path.setTwoSided(True)
        return path

    def dust_update(self):
        """
        Move the dust back at the player's speed (the motes behind the ship
        start again ahead of it, in the shader). Its opacity increases with
        speed.
        """
        dt = self.game.game_time.get_time_step()
        speed = magnitude(self.game.player.pawn.speed)
        alpha = (
            MIN_DUST_ALPHA + speed * (MAX_DUST_ALPHA - MIN_DUST_ALPHA) / self.max_speed
        )
        self.root.setAlphaScale(alpha)
        self.travel = (self.travel + speed * dt) % (self.depth * TRAVEL_WRAP_DEPTHS)
        self._travel_input[0] = self.travel

    def clean(self):
        """
        Cleans the SpeedDustCloud object
        """
        if self.game.method_lists:
            self.game.method_lists.pop(self.id, None)
        self.game = None
        for particle in self.particles:
            particle.removeNode()
        self.particles = None
        self.root.removeNode()
        self.root = None
