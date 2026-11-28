"""
The glowing orb an ordnance is drawn as: a camera-facing card whose fragment
shader (``ordnance_orb.frag``) paints a white-hot core and a soft halo of the
ordnance's colour, additively. Hidden by the clouds in front of it like the
other effects (WorldBuilder's cloud_cover.glsl).

Every look number is a header constant; the shader gets them as uniforms.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from panda3d.core import (
    BoundingSphere,
    CardMaker,
    ColorBlendAttrib,
    CullFaceAttrib,
    LPoint3,
    NodePath,
    Vec3,
)
from world_builder.clouds.cover import no_cover

from space_flight.fx import load_glsl_shader

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

#: The card's half-size, in core radii: how far the halo reaches
ORB_HALO_FACTOR = 4.0
#: Where the core's edge starts to soften, as a fraction of the core radius
#: (1 = a hard edge)
ORB_CORE_EDGE_START = 0.55
#: How white the core is: 0 = the ordnance's colour, 1 = pure white
ORB_CORE_WHITE_MIX = 0.6
#: Gaussian width of the halo, in core radii
ORB_HALO_SIGMA = 1.6
#: Brightness of the halo relative to the core
ORB_HALO_INTENSITY = 0.8
#: Draw order: after the sorted "transparent" bin, and so after the clouds
ORB_BIN_ORDER = 20
#: A flare's core radius, as a fraction of its collision-sphere radius
FLARE_CORE_FRACTION_OF_COLLISION_RADIUS = 0.2


def orb_core_radius_m(ordnance_conf: dict) -> float:
    """
    :param ordnance_conf: The ordnance's configuration
    :return: The core radius of its orb: its visual radius, except for a flare,
        whose core is a fraction of its collision sphere
    """
    if ordnance_conf["type"] == "flare":
        collision_radius_m = ordnance_conf["collision_radius_m"]
        return FLARE_CORE_FRACTION_OF_COLLISION_RADIUS * collision_radius_m
    return ordnance_conf["visual_radius_m"]


def build_ordnance_orb(
    game: FlightState,
    parent_node: NodePath,
    core_radius_m: float,
    color: tuple[float, float, float, float],
) -> NodePath:
    """
    Build the orb: a card centred on *parent_node*, expanded by its shader.

    :param game: The game/flight state
    :param parent_node: The node to attach the orb to (the ordnance's)
    :param core_radius_m: The white-hot core's radius
    :param color: RGBA; the alpha scales the brightness
    :return: The orb's node path
    """
    cm = CardMaker("ordnance_orb")
    cm.set_frame(-1.0, 1.0, -1.0, 1.0)
    orb = parent_node.attach_new_node(cm.generate())

    half_size_m = core_radius_m * ORB_HALO_FACTOR
    orb.set_shader(load_glsl_shader("ordnance_orb.vert", "ordnance_orb.frag"))
    orb.set_shader_inputs(
        uColor=Vec3(*color[:3]),
        uHalfSize=half_size_m,
        uHaloFactor=ORB_HALO_FACTOR,
        uCoreEdge=ORB_CORE_EDGE_START,
        uCoreWhiteMix=ORB_CORE_WHITE_MIX,
        uHaloSigma=ORB_HALO_SIGMA,
        uHaloIntensity=ORB_HALO_INTENSITY,
        uIntensity=float(color[3]),
    )
    # Hidden by the clouds in front of it: the scene's world sets their inputs,
    # none without one
    no_cover(orb)
    scene = getattr(game, "scene", None)
    if scene is not None:
        scene.track_translucent(orb)

    # Additive glow, seen from any side, self-lit, no depth write
    orb.set_attrib(
        ColorBlendAttrib.make(
            ColorBlendAttrib.MAdd, ColorBlendAttrib.OOne, ColorBlendAttrib.OOne
        )
    )
    orb.set_attrib(CullFaceAttrib.make(CullFaceAttrib.MCullNone))
    orb.set_light_off()
    orb.set_depth_write(False)
    orb.set_bin("fixed", ORB_BIN_ORDER)
    # The shader expands the unit card: give the node matching bounds, or the
    # culler would clip the halo at the screen's edge
    orb.node().set_bounds(BoundingSphere(LPoint3(0, 0, 0), half_size_m * 1.5))
    orb.node().set_final(True)
    return orb


def remove_ordnance_orb(game: FlightState, orb: NodePath) -> None:
    """
    Stop tracking an orb and remove it.

    :param game: The game/flight state
    :param orb: The orb's node path
    """
    scene = getattr(game, "scene", None)
    if scene is not None:
        scene.untrack_translucent(orb)
    orb.removeNode()
