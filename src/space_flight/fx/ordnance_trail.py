"""
The engine trail of a missile or rocket: a long, translucent ribbon of the
ordnance's colour through its past positions, tapering and fading with age.
The shaders (``ordnance_trail.vert/.frag``) expand it across its direction and
hide it behind the clouds in front of it (WorldBuilder's cloud_cover.glsl).

The trail outlives its ordnance: once the ordnance is gone (:meth:`detach`),
the ribbon keeps fading and removes itself when its last point has expired.

Its node is a direct child of the game's root node, placed at the launch
position, and its points are kept in float64 world coordinates, written
relative to that anchor: a render-origin re-base shifts direct children, so the
trail stays where it is in the world.

Every look number is a header constant.
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import (
    BitMask32,
    ColorBlendAttrib,
    CullFaceAttrib,
    Geom,
    GeomNode,
    GeomTristrips,
    GeomVertexArrayFormat,
    GeomVertexData,
    GeomVertexFormat,
    InternalName,
    OmniBoundingVolume,
    Vec3,
)
from world_builder.clouds.cover import no_cover

from space_flight.fx import load_glsl_shader

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

#: The ordnance types that leave a trail
TRAIL_CATEGORIES = ("missile", "rocket")
#: How long a point of the trail lasts, seconds: the trail's length is this
#: times the ordnance's speed
TRAIL_DURATION_S = 2.0
#: Time between two recorded points, seconds (the live head point is added on
#: top, every frame)
TRAIL_SAMPLE_INTERVAL_S = 1 / 30
#: The ribbon's half-width at the head, in the ordnance's visual radii
TRAIL_HALF_WIDTH_FACTOR = 1.0
#: How the width shrinks along the trail: width * (1 - age / duration) ** power
TRAIL_TAPER_POWER = 1.0
#: The trail's brightness at the head (times the ordnance colour's alpha)
TRAIL_ALPHA = 0.8
#: How the brightness drops along the trail: (1 - age / duration) ** power
TRAIL_FADE_POWER = 1.5
#: Where the ribbon's soft edge starts, as a fraction of its half-width
#: (1 = a hard edge)
TRAIL_EDGE_START = 0.0
#: Draw order in the "fixed" bin (the orbs', the lasers')
TRAIL_BIN_ORDER = 20

#: Most points a trail ever holds: the recorded ones, the head, a spare
_MAX_POINTS = math.ceil(TRAIL_DURATION_S / TRAIL_SAMPLE_INTERVAL_S) + 3
#: Floats per vertex: position, neighbour position, (side, half-width, alpha)
_FLOATS_PER_VERTEX = 9


def _trail_format() -> GeomVertexFormat:
    array = GeomVertexArrayFormat()
    array.addColumn("vertex", 3, Geom.NTFloat32, Geom.CPoint)
    array.addColumn(InternalName.make("other"), 3, Geom.NTFloat32, Geom.COther)
    array.addColumn(InternalName.make("ribbon"), 3, Geom.NTFloat32, Geom.COther)
    fmt = GeomVertexFormat()
    fmt.addArray(array)
    return GeomVertexFormat.registerFormat(fmt)


class OrdnanceTrail:
    """
    The trail of one ordnance. It updates itself every frame through
    ``game.method_lists``, following the ordnance until :meth:`detach`.
    """

    def __init__(
        self,
        game: FlightState,
        ordnance,
        color: tuple[float, float, float, float],
        half_width_m: float,
    ):
        """
        :param game: The game/flight state
        :param ordnance: The ordnance it follows (its float64 ``position``)
        :param color: RGBA of the ordnance; the alpha scales the brightness
        :param half_width_m: The ordnance's visual radius
        """
        self.game = game
        self.ordnance = ordnance
        self.id = uuid.uuid4()
        self.half_width_m = half_width_m * TRAIL_HALF_WIDTH_FACTOR
        self.brightness = TRAIL_ALPHA * float(color[3])
        # (time, world position) of the recorded points, oldest first
        self.points: deque[tuple[float, np.ndarray]] = deque()
        self.last_sample_s = -math.inf
        self.head = np.array(ordnance.position, dtype=float)
        self.anchor = self.head.copy()
        self.following = True
        self.is_done = False

        vdata = GeomVertexData("ordnance_trail", _trail_format(), Geom.UHDynamic)
        vdata.setNumRows(_MAX_POINTS * 2)
        self.vdata = vdata
        strip = GeomTristrips(Geom.UHStatic)
        strip.addConsecutiveVertices(0, _MAX_POINTS * 2)
        strip.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(strip)
        geom_node = GeomNode("ordnance_trail")
        geom_node.addGeom(geom)
        # Nothing to draw until the first update
        self._write(np.zeros((_MAX_POINTS * 2, _FLOATS_PER_VERTEX), dtype=np.float32))

        node = self.game.root_node.attachNewNode(geom_node)
        node.setPos(*self.game.render_origin.to_local(self.anchor))
        node.setShader(load_glsl_shader("ordnance_trail.vert", "ordnance_trail.frag"))
        node.setShaderInputs(
            uColor=Vec3(*color[:3]),
            uEdgeStart=TRAIL_EDGE_START,
        )
        # Hidden by the clouds in front of it: the scene's world sets their
        # inputs, none without one
        no_cover(node)
        scene = getattr(game, "scene", None)
        if scene is not None:
            scene.track_translucent(node)
        node.setAttrib(
            ColorBlendAttrib.make(
                ColorBlendAttrib.MAdd, ColorBlendAttrib.OOne, ColorBlendAttrib.OOne
            )
        )
        node.setAttrib(CullFaceAttrib.make(CullFaceAttrib.MCullNone))
        node.setLightOff()
        node.setDepthWrite(False)
        node.setBin("fixed", TRAIL_BIN_ORDER)
        # The points move every frame: never culled by a stale extent
        node.node().setBounds(OmniBoundingVolume())
        node.node().setFinal(True)
        node.node().setIntoCollideMask(BitMask32.allOff())
        self.node = node

        self.game.method_lists[self.id] = [self.update]

    def detach(self) -> None:
        """
        The ordnance is gone: record where it ended and let the trail fade out.
        """
        if not self.following:
            return
        self.following = False
        now = self.game.game_time.get_current_time()
        self.points.append((now, self.head.copy()))
        self.ordnance = None

    def update(self) -> None:
        """
        Record the ordnance's position, drop the expired points and rewrite the
        ribbon. Removes the trail once it has faded out.
        """
        now = self.game.game_time.get_current_time()
        if self.following:
            self.head = np.array(self.ordnance.position, dtype=float)
            if now - self.last_sample_s >= TRAIL_SAMPLE_INTERVAL_S:
                self.points.append((now, self.head.copy()))
                self.last_sample_s = now
        while self.points and now - self.points[0][0] >= TRAIL_DURATION_S:
            self.points.popleft()
        if not self.following and not self.points:
            self.clean()
            return

        points = list(self.points)
        if self.following:
            points.append((now, self.head))
        self._write(self._build_vertices(points, now))

    def _build_vertices(self, points: list, now: float) -> np.ndarray:
        """
        :param points: (time, world position) of the trail's points, oldest first
        :param now: The current time
        :return: The ribbon's vertices, (2 * _MAX_POINTS, _FLOATS_PER_VERTEX):
            two per point, the unused ones collapsed on the head with no alpha
        """
        count = len(points)
        positions = np.array([p for _, p in points]) - self.anchor
        ages = np.array([now - t for t, _ in points])
        life_left = np.clip(1.0 - ages / TRAIL_DURATION_S, 0.0, 1.0)
        # The neighbour gives the direction: the next point, the previous for
        # the last
        neighbours = np.empty_like(positions)
        if count > 1:
            neighbours[:-1] = positions[1:]
            neighbours[-1] = positions[-2]
        else:
            neighbours[:] = positions
        half_widths = self.half_width_m * life_left**TRAIL_TAPER_POWER
        alphas = self.brightness * life_left**TRAIL_FADE_POWER

        out = np.zeros((_MAX_POINTS * 2, _FLOATS_PER_VERTEX), dtype=np.float32)
        count = min(count, _MAX_POINTS)
        # Unused points: on the last one, invisible
        out[:, 0:3] = positions[-1]
        out[:, 3:6] = positions[-1]
        for side, offset in ((-1.0, 0), (1.0, 1)):
            rows = slice(offset, 2 * count, 2)
            out[rows, 0:3] = positions[-count:]
            out[rows, 3:6] = neighbours[-count:]
            out[rows, 6] = side
            out[rows, 7] = half_widths[-count:]
            out[rows, 8] = alphas[-count:]
        return out

    def _write(self, vertices: np.ndarray) -> None:
        """
        :param vertices: The whole vertex array, as floats
        """
        handle = self.vdata.modifyArray(0).modifyHandle()
        handle.copyDataFrom(vertices.tobytes())

    def clean(self) -> None:
        """
        Remove the trail.
        """
        if self.is_done:
            return
        self.is_done = True
        self.game.method_lists.pop(self.id, None)
        scene = getattr(self.game, "scene", None)
        if scene is not None:
            scene.untrack_translucent(self.node)
        self.node.removeNode()
        self.ordnance = None
        self.game = None
