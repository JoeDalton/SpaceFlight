"""
Standalone flythrough demo for the in-scene cloud field.

Drops a big opaque smiley into the middle of a :class:`CloudField` and lets you
fly around and through it, so the two things that are hard to judge from a static
screenshot are easy to see:

  * the cloud SHAPE — silhouette, carving, and how it holds up as you approach,
    pass through, and look back at the same cloud;
  * how clouds compose against OPAQUE geometry — the smiley is deliberately large
    enough to be half-buried in a cloud, so you can watch the depth test cut the
    billboards against it from every angle.

It builds the real :class:`CloudField` and loads the real shaders from
space_flight/datafiles/shaders (not local copies), so it doubles as a quick
visual check of those files — including whether they compile at all, which the
headless unit tests cannot tell you. Run it from a project environment where
space_flight is importable::

    python scripts/demo_clouds.py

Controls (AZERTY):
    Z / S           pitch down / up
    Q / D           roll left / right
    A / E           yaw left / right
    UP / DOWN       fly forward / backward
    LEFT / RIGHT    slide left / right
    W / X           slide up / down
    SHIFT           hold to move 5x faster

    J / L           swing the sun around the sky (azimuth)
    I / K           raise / lower the sun (elevation)
    P               cycle the time-of-day palette (noon / golden / dusk / night)
    * / $           sweep forward_gain up / down — how much brighter cloud is
                    looking straight into the sun than side-on. Much above ~10 and
                    everything toward the sun saturates to one flat colour.
                    Independent of backward_gain, which the readout shows so you
                    can see it stay put.
    T / Y           sweep the cumulus deck's COVERAGE down / up — the fraction of
                    sky it fills, measured zenith-projected. Not a smooth "more of
                    the same": it is a percolation transition, so the low end is
                    isolated puffs and the high end a connected sheet with holes.
    U / O           the same for the cirrus veil, independently — coverage is per
                    type, against that type's own slab.
    N / M           sweep the edge SOFTNESS, in standard deviations of the field.
                    A narrow window is the whole source of the crisp cauliflower
                    edge. Independent of coverage, which the readout shows.

                    Both sweeps re-derive the drawn threshold and re-pack, with no
                    rebuild — but they do not re-place billboards, so they are
                    exact only up to the coverage the deck was BUILT at. The
                    readout shows that ceiling as "now/ceiling", and the demo
                    deliberately over-places to provide it (see COVERAGE_HEADROOM).

    C               toggle the cloud field
    V               toggle the high cirrus layer (off at start)
    G               toggle the ground
    R               reset the camera to its starting pose
    F               print the camera pose, the sun, and the field's tuning
    ESC             quit

A disk marks where the sun is, so the lighting can be read against its actual
direction rather than guessed at: it rides with the camera at a fixed distance
along the sun vector and takes the direct light's own colour, so it reddens and
dims with the clouds. Being ordinary opaque geometry, it is also correctly
occluded by cloud that happens to be in front of it.

The sun's direct and ambient colours are derived from its elevation the way the
reference shader's atmosphere does it: as the sun drops toward the horizon the
direct light reddens and dims while the sky fill cools and darkens, so the clouds
relight coherently. Nothing is baked, so this is a few uniform writes per frame.
"""

import math
import sys
from dataclasses import replace
from types import SimpleNamespace

from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    ClockObject,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomTrifans,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    GraphicsWindow,
    Point3,
    TextNode,
    Vec3,
    loadPrcFileData,
)

from space_flight.actors.player import CAMERA_FAR_M
from space_flight.global_architecture.asset_manager import AssetManager
from space_flight.scenes.cloud import PRESETS, CloudField, CloudType
from space_flight.scenes.cloud.field import lod_shells

# ── Scene tuning ───────────────────────────────────────────────────────────────
# ONE cumulus deck, taken straight from cloud.PRESETS. There is no cloud count to
# set: the deck is a density field over a slab of sky, the clouds are its
# features, and how many billboards get placed follows from how much of the sky it
# covers.
#
# The innermost shell's domain is one whole period of the field's noise, which is
# what makes the toroidal recycle seamless — a cell teleporting by that width lands
# where the field is bit-identical, so nothing has to be faded to hide the jump.
# Every outer shell is a power-of-two multiple, so they all stay seamless too.
CLOUD_DOMAIN = 32000.0
CELL_SIZE = 1000.0
# Six nested shells: boxes from 32 km out to 1024 km, so cloud reaches 512 km. Each
# shell doubles its billboard radius and so needs an eighth the count per unit
# volume, which makes each successive shell cost HALF its predecessor -- and because
# that series converges, ~100 k billboards buys 512 km where 97 k bought 128.
# (The demo builds above that, because it over-places for the coverage sweep --
# see COVERAGE_HEADROOM.)
#
# It needs to reach that far: clouds are elevated, so they peek over the horizon and
# the deck stays visible to ~498 km from 9 km up. Stopping short leaves bare ground
# above the farthest cloud.
CLOUD_SHELLS = 6
# Cirrus spans far larger features, so it needs fewer, larger sort cells.
CIRRUS_CELL_SIZE = 2000.0
WIND = (20.0, 0.0, 0.0)

# Aerial perspective completes by here: distant cloud is fully haze-coloured, which
# is also what hides the outermost shell's box edge, so keep it INSIDE that shell's
# 512 km half-width. The ground fades over the same distance to the same colour --
# without that, hazed cloud would sit against fully saturated green land.
HORIZON_DISTANCE = 400000.0

# The planet the ground and the cloud deck both curve over. ONE constant, passed
# to CloudField explicitly, because if the two disagreed the ground would clip the
# clouds (or fail to) at the wrong distance.
PLANET_RADIUS = 6371000.0

GROUND_COLOR = (0.30, 0.36, 0.26, 1.0)
# The ground reaches past the horizon so its own bulge occludes what lies beyond:
# the visible horizon is then where the surface turns away, at sqrt(2*R*h) -- 126 km
# at 1.25 km up, 339 km at 9 km -- with the correct dip of sqrt(2h/R) below eye
# level. Sized to cover eye heights to ~24 km; higher and sky appears below the
# horizon where the mesh runs out.
GROUND_RADIUS = 550000.0
# A polar mesh, because the horizon is a circle. Two independent error terms:
# radial sag between rings is spacing^2/(8R) regardless of radius (0.65 m here,
# 0.4 arcmin -- invisible), while the segment count sets how ROUND the horizon line
# looks. Its flat-spot is a constant 1.0 arcmin at 128 segments whatever the eye
# height, which is right at visual acuity, so 256 takes it to a safe 0.26.
GROUND_RINGS = 96
GROUND_SEGMENTS = 256

# The disk that marks the sun. Kept well inside the far plane, and deliberately
# further out than the cloud field so cloud in front of it occludes it.
SUN_MARKER_DISTANCE = 60000.0
# Degrees of angular radius. The real sun is about 0.27, but a marker that small
# is hard to find in a 70-degree field of view, so this is a few times over.
SUN_MARKER_ANGLE = 0.9
SUN_MARKER_SEGMENTS = 48

# Big enough to be half-buried in a cloud, so the depth test against opaque
# geometry is obvious from any angle.
SMILEY_RADIUS = 500.0
SMILEY_POS = (0.0, 0.0, 1250.0)

# ── Sun ────────────────────────────────────────────────────────────────────────
# Palettes keyed by name, each a (direct, ambient) pair at high sun. The demo
# interpolates toward the horizon values below as the sun drops.
SUN_AZIMUTH = 200.0  # degrees, 0 = +Y
SUN_ELEVATION = 35.0  # degrees above the horizon
SUN_AZIMUTH_RATE = 45.0  # degrees/second while an arrow is held
SUN_ELEVATION_RATE = 25.0

# (name, high-sun direct, high-sun ambient, horizon direct, horizon ambient)
SUN_PALETTES = (
    (
        "noon",
        (1.00, 0.98, 0.92),
        (0.45, 0.60, 0.88),
        (1.00, 0.80, 0.55),
        (0.42, 0.50, 0.68),
    ),
    (
        "golden",
        (1.00, 0.88, 0.66),
        (0.44, 0.52, 0.74),
        (1.00, 0.55, 0.26),
        (0.40, 0.38, 0.48),
    ),
    (
        "dusk",
        (1.00, 0.62, 0.34),
        (0.30, 0.32, 0.52),
        (0.90, 0.30, 0.20),
        (0.20, 0.20, 0.36),
    ),
    (
        "night",
        (0.30, 0.38, 0.60),
        (0.08, 0.11, 0.22),
        (0.22, 0.26, 0.44),
        (0.05, 0.07, 0.15),
    ),
)

# ── Camera ─────────────────────────────────────────────────────────────────────
START_POS = (0.0, -1900.0, 1250.0)
START_HPR = (0.0, 0.0, 0.0)
SPEED = 400.0  # metres/second — crosses the domain in about 15 s
BOOST = 5.0
PITCH_RATE = 40.0  # degrees/second
YAW_RATE = 40.0
ROLL_RATE = 60.0

# Panda key names for the held-down controls, mapped to a readable action name.
_CONTROLS = {
    "z": "pitch_down",
    "s": "pitch_up",
    "q": "roll_left",
    "d": "roll_right",
    "a": "yaw_left",
    "e": "yaw_right",
    "arrow_up": "forward",
    "arrow_down": "backward",
    "arrow_left": "left",
    "arrow_right": "right",
    "w": "up",
    "x": "down",
    "shift": "boost",
    "j": "sun_ccw",
    "l": "sun_cw",
    "i": "sun_higher",
    "k": "sun_lower",
    "*": "shadow_up",
    "$": "shadow_down",
    "t": "coverage_down",
    "y": "coverage_up",
    "n": "softness_down",
    "m": "softness_up",
    "u": "cirrus_coverage_down",
    "o": "cirrus_coverage_up",
}

# The live coverage sweep, in fraction of sky per second while a key is held.
#
# The ceiling is NOT arbitrary, and it is the one thing to understand about this
# control: set_coverage re-derives the drawn threshold but does not re-place
# billboards, and placement was rejection-sampled at the coverage the deck was
# BUILT with. Sweeping down is therefore exact -- the surplus billboards simply
# fall below the higher bar and discard -- while sweeping up past the built value
# has no billboards to draw the new cloud with, so the deck grows holes instead of
# growing. So the demo builds each type with headroom (see COVERAGE_HEADROOM) and
# clamps the sweep to it.
COVERAGE_RATE = 0.12
# How much above its preset each type is BUILT at, to give the sweep somewhere to
# go UP. Sweeping down needs none of this and is always exact.
#
# It is pure over-placement, so it is not free: measured on the six-shell deck at
# 1280x720, sitting at the shipped 0.29 coverage either way --
#
#   headroom 0.00   100 k billboards    9.6 ms/frame
#   headroom 0.15   170 k billboards   15.3 ms/frame
#   headroom 0.25   221 k billboards   17.6 ms/frame
#
# 0.15 buys a 0.29 -> 0.44 upward range, which spans the plausible authoring range
# for scattered cumulus (much past that stops being cumulus at all -- see
# DensityField.coverage on the percolation transition) without paying the ~2x
# frame time that 0.25 costs. Lower it to 0 to judge the shipped look at full rate.
COVERAGE_HEADROOM = 0.15
SOFTNESS_RATE = 0.5  # sigma per second
SOFTNESS_RANGE = (0.05, 3.0)


def _with_headroom(cloud_type):
    """The type's shipped field, built at a higher coverage so it can be swept.

    :param cloud_type: which preset to lift
    :returns: a :class:`DensityField` with coverage raised by COVERAGE_HEADROOM
    """
    field = PRESETS[cloud_type].field
    return replace(field, coverage=min(1.0, field.coverage + COVERAGE_HEADROOM))


# The live-swept optic. forward_gain is how much brighter cloud is looking
# straight into the sun than side-on -- the silver lining, and the number that
# decides how blinding a view into the sun is. It IS the observable, so no
# conversion is needed to read it: 1 is no forward scattering at all, and much
# above ~10 puts everything toward the sun into the tonemap's saturating region
# where it clips to one flat colour.
#
# Independent of backward_gain by construction, so sweeping it does not disturb
# how the deck looks with the sun behind you (see noise.phase_weights).
# The ceiling is real rather than arbitrary: a broad forward lobe already lifts the
# mid-angles, so past about 20x (at the default 0.4 anisotropy) the solve would need
# a negative isotropic weight and the phase would dip below zero somewhere. 15 stays
# clear of that with room for a lower backward_gain, and is already deep enough into
# saturation that going further shows nothing.
SWEEP_PARAM = "forward_gain"
SWEEP_RATE = 1.5  # units per second while a key is held
SWEEP_RANGE = (1.0, 15.0)

# Translation is applied about the camera's OWN axes (Panda's camera looks down
# +Y, with +X right and +Z up), so sliding composes with roll the way a cockpit
# expects rather than drifting along world axes.
_TRANSLATIONS = (
    ("forward", "backward", "set_y"),
    ("right", "left", "set_x"),
    ("up", "down", "set_z"),
)


def sun_palette(elevation, palette_index):
    """Direct and ambient light for a sun at *elevation*, and the matching sky.

    Mirrors what the reference shader's atmosphere does with an analytic
    Rayleigh/Mie model, but as a hand-authored ramp: the lower the sun, the longer
    its light's path through the air, so the direct beam reddens and dims while
    the ambient fill cools and darkens. Driving both from one number is what makes
    the clouds relight coherently instead of looking recoloured.

    :param elevation: sun elevation in degrees (negative = below the horizon)
    :param palette_index: index into SUN_PALETTES
    :returns: (name, sun_color, sky_color, background_color)
    """
    name, high_sun, high_sky, low_sun, low_sky = SUN_PALETTES[
        palette_index % len(SUN_PALETTES)
    ]
    # 1 at high sun, 0 at the horizon and below.
    height = max(0.0, min(1.0, elevation / 40.0))
    ramp = height * height * (3.0 - 2.0 * height)  # smoothstep
    blend = [low + (high - low) * ramp for low, high in zip(low_sun, high_sun)]
    sky = [low + (high - low) * ramp for low, high in zip(low_sky, high_sky)]
    # Below the horizon everything keeps dimming, so night reads as night.
    if elevation < 0.0:
        dim = max(0.05, 1.0 + elevation / 12.0)
        blend = [c * dim for c in blend]
        sky = [c * dim for c in sky]
    # The window's clear colour is the sky fill lifted a little, so the horizon
    # and the clouds' haze fade agree.
    background = [min(1.0, c * 1.15 + 0.02) for c in sky]
    return name, tuple(blend), tuple(sky), (*background, 1.0)


def sun_vector(azimuth, elevation):
    """Unit vector FROM the scene TOWARD the sun, from azimuth/elevation degrees.

    Z-up, azimuth 0 along +Y and increasing toward +X.

    :param azimuth: degrees around the horizon
    :param elevation: degrees above the horizon
    :returns: a Vec3 pointing at the sun
    """
    az, el = math.radians(azimuth), math.radians(elevation)
    horizontal = math.cos(el)
    return Vec3(
        horizontal * math.sin(az),
        horizontal * math.cos(az),
        math.sin(el),
    )


class CloudDemo(ShowBase):
    """A free-flying camera, one cloud field, and one large opaque smiley."""

    def __init__(self):
        super().__init__()
        self.setFrameRateMeter(True)
        self.disable_mouse()  # or the default trackball fights the keyboard
        self._clock = ClockObject.get_global_clock()

        # CloudField takes a game object by convention; the demo stands in.
        self.asset_manager = AssetManager(self)
        game = SimpleNamespace(app=self)

        # The far plane must clear the OUTERMOST shell, or those shells are built
        # and then thrown away by the clip. The same constant the game uses, so the
        # demo cannot flatter itself with a reach the real camera does not have.
        self.camLens.set_near_far(1.0, CAMERA_FAR_M)
        self.camLens.set_fov(70)
        self._reset_camera()

        self._sun_azimuth = SUN_AZIMUTH
        self._sun_elevation = SUN_ELEVATION
        self._palette = 0

        self.ground = self._make_ground()
        self.sun_marker = self._make_sun_marker()
        self.smiley = self.loader.load_model("models/smiley")
        self.smiley.set_scale(SMILEY_RADIUS)  # the model is a unit sphere
        self.smiley.set_pos(Point3(*SMILEY_POS))
        self.smiley.reparent_to(self.render)

        # Built with coverage headroom so the live sweep has somewhere to go: it
        # re-derives the drawn threshold but never re-places billboards, so it can
        # only be trusted at or below the coverage the deck was built at. The demo
        # therefore over-places deliberately and starts the sweep back down at the
        # shipped value -- see COVERAGE_HEADROOM.
        cumulus_built = _with_headroom(CloudType.CUMULUS)
        cirrus_built = _with_headroom(CloudType.CIRRUS)

        # Assembled as a list first so the cirrus layer's INDEX can be looked up
        # rather than assumed. It used to be a module constant equal to
        # CLOUD_SHELLS, which silently encoded "cirrus is the layer after the
        # shells" -- so commenting the cirrus entry out below turned every
        # cirrus-related call into an IndexError.
        layers = [
            *lod_shells(
                CloudType.CUMULUS,
                count=CLOUD_SHELLS,
                domain=CLOUD_DOMAIN,
                cell_size=CELL_SIZE,
                field=cumulus_built,
            ),
            # Built always, shown on demand (see _toggle_cirrus): a second type is
            # useful for checking that the layers sort against each other and that
            # each gets its OWN field and optics, but it makes the cumulus deck
            # harder to judge while tuning. Comment it out to drop it entirely --
            # every cirrus control then disables itself.
            # CloudLayer(
            #     CloudType.CIRRUS,
            #     cell_size=CIRRUS_CELL_SIZE,
            #     field=cirrus_built,
            # ),
        ]
        self._cirrus_layer = next(
            (
                index
                for index, layer in enumerate(layers)
                if layer.cloud_type is CloudType.CIRRUS
            ),
            None,
        )

        print("building the cloud field ...")
        self.field = CloudField(
            parent=self.render,
            game=game,
            layers=layers,
            domain=CLOUD_DOMAIN,
            wind=WIND,
            sun_direction=sun_vector(self._sun_azimuth, self._sun_elevation),
            horizon_distance=HORIZON_DISTANCE,
            # The same planet the ground curves over -- see _make_ground.
            planet_radius=PLANET_RADIUS,
        )
        for report in self.field._layer_report:
            print(
                f"  {report['type'].value}: {report['particles']:>6d} billboards in "
                f"{report['cells']:>5d} cells over {report['domain']:>7.0f} m"
                f"{'  seamless' if report['seamless'] else ''}"
            )
        print(f"  {self.field._n} billboards total")

        self._keys = dict.fromkeys(_CONTROLS.values(), False)
        for key, action in _CONTROLS.items():
            self.accept(key, self._set_key, [action, True])
            self.accept(f"{key}-up", self._set_key, [action, False])
        self.accept("c", self._toggle_clouds)
        self.accept("v", self._toggle_cirrus)
        self.accept("g", self._toggle_ground)
        self.accept("p", self._cycle_palette)
        self.accept("r", self._reset_camera)
        self.accept("f", self._print_pose)
        self.accept("escape", sys.exit)
        # Only a real window can be closed; offscreen (see the smoke test) the
        # buffer has no close event.
        if isinstance(self.win, GraphicsWindow):
            self.win.set_close_request_event("window-close")
            self.accept("window-close", sys.exit)

        self._hud = OnscreenText(
            text="Z/S pitch   Q/D roll   A/E yaw   SHIFT boost\n"
            "UP/DOWN fly   LEFT/RIGHT slide   W/X up-down\n"
            "J/L sun azimuth   I/K sun height   P palette\n"
            "*/$ forward_gain   T/Y coverage   U/O cirrus cov   N/M edge\n"
            "C clouds   V cirrus   G ground   R reset   F pose   ESC",
            pos=(-1.3, -0.92),
            scale=0.042,
            fg=(1, 1, 1, 0.85),
            shadow=(0, 0, 0, 0.6),
            align=TextNode.ALeft,
            mayChange=False,
        )
        self._sun_readout = OnscreenText(
            text="",
            pos=(-1.3, 0.90),
            scale=0.045,
            fg=(1, 1, 1, 0.85),
            shadow=(0, 0, 0, 0.6),
            align=TextNode.ALeft,
            mayChange=True,
        )
        # Start the sweep from whatever the cumulus preset actually ships, so the
        # first keypress nudges the shipped value rather than jumping to a default.
        self._sweep_value = float(
            getattr(self.field._layer_specs[0].optics, SWEEP_PARAM)
        )
        # Start the coverage sweep back down at the SHIPPED value, not the built
        # one: the headroom exists to be swept into, not to be looked at.
        self._coverage = PRESETS[CloudType.CUMULUS].field.coverage
        self._cirrus_coverage = PRESETS[CloudType.CIRRUS].field.coverage
        self._softness = PRESETS[CloudType.CUMULUS].field.edge_softness
        self._coverage_ceiling = cumulus_built.coverage
        self._cirrus_ceiling = cirrus_built.coverage
        for shell in range(CLOUD_SHELLS):
            self.field.set_coverage(
                layer=shell, coverage=self._coverage, edge_softness=self._softness
            )
        self._palette_name = ""
        self._cirrus_max_optical_depth = None
        self._cirrus_on = False
        if self._cirrus_layer is not None:
            self.field.set_coverage(
                layer=self._cirrus_layer, coverage=self._cirrus_coverage
            )
            # Cirrus starts hidden: it is built so the two-layer paths get
            # exercised, but a second deck overhead makes the cumulus harder to
            # judge.
            self._cirrus_max_optical_depth = self.field._layer_specs[
                self._cirrus_layer
            ].optics.max_optical_depth
            self._cirrus_on = True
            self._toggle_cirrus()
        # After the readout exists: _apply_sun drives the field, the sky, the
        # ground tint and the readout from one place.
        self._apply_sun()

        self.taskMgr.add(self._update, "cloud_demo_update")
        print(__doc__)

    # ── internals ──────────────────────────────────────────────────────────────

    def _set_key(self, action, pressed):
        """Record a held key. :param action: control name :param pressed: state"""
        self._keys[action] = pressed

    def _reset_camera(self):
        """Put the camera back at its starting pose."""
        self.camera.set_pos(Point3(*START_POS))
        self.camera.set_hpr(Vec3(*START_HPR))

    def _make_ground(self):
        """A ground surface that curves over the planet, to put a real horizon
        under the clouds.

        A flat plane will not do once the cloud deck reaches the horizon. The deck
        droops by ``d^2 / (2R)`` — 1.3 km at 128 km, comparable to its whole
        thickness — so beyond about 113 km it sinks below z=0, where a flat plane
        (opaque, depth-writing, and drawn before the clouds) simply clips it. The
        result was a bare strip above the farthest cloud. Curving the ground by the
        SAME law fixes it, and it is not just a fix: the drooped surface's own bulge
        is what hides whatever lies beyond the horizon, and the horizon lands at
        ``sqrt(2*R*h)`` with the correct dip of ``sqrt(2h/R)`` below eye level.

        Baked rather than shaded, which works because the mesh is recentred on the
        camera every frame (see _update): the droop is always measured from the
        mesh centre, and the mesh centre is always the camera — the same origin the
        cloud shader measures from, so the two agree by construction.

        A polar mesh, since the horizon is a circle and a square grid's corners
        would reach much further than its edges.

        :returns: the ground NodePath, parented under render
        """
        curvature = 1.0 / (2.0 * PLANET_RADIUS)
        vdata = GeomVertexData("ground", GeomVertexFormat.get_v3c4(), Geom.UH_static)
        vdata.set_num_rows(1 + GROUND_RINGS * GROUND_SEGMENTS)
        writer = GeomVertexWriter(vdata, "vertex")
        writer.add_data3(0.0, 0.0, 0.0)  # directly under the camera
        # Per-vertex haze, so the ground recedes into the same colour the clouds do.
        # A static bake works because the factor depends only on the radius, and the
        # mesh centre is always the camera; only the COLOUR changes with the sun, and
        # _recolour_ground rewrites it then.
        self._ground_haze = [0.0]
        for ring in range(1, GROUND_RINGS + 1):
            radius = GROUND_RADIUS * ring / GROUND_RINGS
            drop = radius * radius * curvature
            haze = min(1.0, radius / HORIZON_DISTANCE)
            for step in range(GROUND_SEGMENTS):
                angle = 2.0 * math.pi * step / GROUND_SEGMENTS
                writer.add_data3(
                    radius * math.cos(angle), radius * math.sin(angle), -drop
                )
                self._ground_haze.append(haze)

        def index(ring, step):
            """:returns: the vertex row for a ring (1-based) and angular step."""
            return 1 + (ring - 1) * GROUND_SEGMENTS + step % GROUND_SEGMENTS

        tris = GeomTriangles(Geom.UH_static)
        for step in range(GROUND_SEGMENTS):  # fan filling the innermost ring
            tris.add_vertices(0, index(1, step), index(1, step + 1))
        for ring in range(1, GROUND_RINGS):  # quads between successive rings
            for step in range(GROUND_SEGMENTS):
                inner, inner_next = index(ring, step), index(ring, step + 1)
                outer, outer_next = index(ring + 1, step), index(ring + 1, step + 1)
                tris.add_vertices(inner, outer, outer_next)
                tris.add_vertices(inner, outer_next, inner_next)
        tris.close_primitive()

        geom = Geom(vdata)
        geom.add_primitive(tris)
        node = GeomNode("ground")
        node.add_geom(geom)
        ground = self.render.attach_new_node(node)
        ground.set_light_off()
        return ground

    def _recolour_ground(self, lit_ground, haze):
        """Rewrite the ground's vertex colours for the current light.

        Per-vertex rather than a shader because the haze factor is baked into the
        mesh and only the two colours change, and those change on a keypress rather
        than per frame.

        :param lit_ground: RGB of the ground under the current sun
        :param haze: RGB the ground recedes into — the same colour the clouds do
        """
        writer = GeomVertexWriter(
            self.ground.node().modify_geom(0).modify_vertex_data(), "color"
        )
        for factor in self._ground_haze:
            writer.set_data4(
                *[base + (far - base) * factor for base, far in zip(lit_ground, haze)],
                1.0,
            )

    def _make_sun_marker(self):
        """A camera-facing disk standing in for the sun.

        Built as a triangle fan in the XZ plane and given Panda's own
        point-eye billboard effect, so it faces the camera with no shader and no
        per-frame orientation maths — only its position has to be updated.

        Opaque and depth-writing like any other solid geometry, which is what
        makes it draw in the "opaque" bin BEFORE the clouds and therefore be
        composited over by any cloud in front of it (see field.py's bin table).

        :returns: the marker NodePath, parented under render
        """
        radius = SUN_MARKER_DISTANCE * math.tan(math.radians(SUN_MARKER_ANGLE))
        vdata = GeomVertexData("sun_marker", GeomVertexFormat.get_v3(), Geom.UH_static)
        vdata.set_num_rows(SUN_MARKER_SEGMENTS + 2)
        writer = GeomVertexWriter(vdata, "vertex")
        writer.add_data3(0.0, 0.0, 0.0)  # fan centre
        for step in range(SUN_MARKER_SEGMENTS + 1):
            angle = 2.0 * math.pi * step / SUN_MARKER_SEGMENTS
            writer.add_data3(radius * math.cos(angle), 0.0, radius * math.sin(angle))
        fan = GeomTrifans(Geom.UH_static)
        fan.add_next_vertices(SUN_MARKER_SEGMENTS + 2)
        fan.close_primitive()
        geom = Geom(vdata)
        geom.add_primitive(fan)
        node = GeomNode("sun_marker")
        node.add_geom(geom)

        marker = self.render.attach_new_node(node)
        marker.set_billboard_point_eye()
        marker.set_light_off()
        return marker

    def _toggle_clouds(self):
        """Hide/show the cloud field, to compare the scene with and without."""
        if self.field.node.is_hidden():
            self.field.node.show()
        else:
            self.field.node.hide()

    def _toggle_cirrus(self):
        """Show/hide the high cirrus layer.

        Both layers share one Geom — that is the whole reason a field takes a list
        of layers, so every type sorts against every other — so a layer cannot be
        hidden with a NodePath. Zeroing its optical-depth cap is the live
        equivalent: every cirrus fragment then computes zero alpha and discards.

        A LOOK toggle, not a performance one: the billboards still rasterise and
        still evaluate their density field before discarding. Turning the layer off
        properly means leaving it out of the layer list and rebuilding -- which the
        layer list supports, and which is why this is a no-op when there is no
        cirrus layer to toggle.
        """
        if self._cirrus_layer is None:
            print("  no cirrus layer was built")
            return
        optics = self.field._layer_specs[self._cirrus_layer].optics
        self._cirrus_on = not self._cirrus_on
        self.field.set_optics(
            layer=self._cirrus_layer,
            max_optical_depth=(
                self._cirrus_max_optical_depth if self._cirrus_on else 0.0
            ),
        )
        print(
            f"  cirrus {'on' if self._cirrus_on else 'off'} "
            f"({self.field._layer_report[self._cirrus_layer]['particles']} "
            f"billboards, "
            f"forward_gain {optics.forward_gain:.1f}x)"
        )

    def _toggle_ground(self):
        """Hide/show the ground."""
        if self.ground.is_hidden():
            self.ground.show()
        else:
            self.ground.hide()

    def _cycle_palette(self):
        """Step to the next time-of-day palette."""
        self._palette = (self._palette + 1) % len(SUN_PALETTES)
        self._apply_sun()

    def _apply_sun(self):
        """Push the current sun to the cloud field, the sky and the readout.

        One place, so the direct light, the ambient fill and the background can
        never disagree about where the sun is.
        """
        name, sun_color, sky_color, background = sun_palette(
            self._sun_elevation, self._palette
        )
        sun_dir = sun_vector(self._sun_azimuth, self._sun_elevation)
        # The horizon haze is the BACKGROUND colour, not the ambient sky fill: the
        # deck has to recede into whatever is actually painted at the horizon, or it
        # stops short of it in a different colour.
        self.field.set_sun(sun_dir, sun_color, sky_color, haze_color=background[:3])
        self.set_background_color(*background)
        # The marker wears the direct light's own colour, so it reddens and dims
        # with the clouds instead of following a ramp of its own. Lifted toward
        # white, because the sun's disk is the brightest thing in the frame even
        # when the light it casts has gone orange.
        self.sun_marker.set_color(
            *[min(1.0, 0.35 + 0.65 * channel) for channel in sun_color], 1.0
        )
        self._place_sun_marker()
        # Light the ground the same way the clouds are lit -- direct sun by its
        # elevation, plus a share of the sky fill -- so it dims and warms WITH
        # them instead of following an independent ramp that disagrees.
        incidence = max(0.0, math.sin(math.radians(self._sun_elevation)))
        self._recolour_ground(
            [
                min(1.0, base * (0.15 + direct * incidence + 0.45 * ambient))
                for base, direct, ambient in zip(GROUND_COLOR[:3], sun_color, sky_color)
            ],
            background[:3],
        )
        self._palette_name = name
        self._update_readout()

    def _update_readout(self):
        """Refresh the on-screen sun and swept-parameter line.

        Shows backward_gain alongside, so the independence is visible: sweeping the
        forward gain must leave the backward one untouched.
        """
        optics = self.field._layer_specs[0].optics
        cirrus = (
            f"   cirrus {self._cirrus_coverage:.2f}/{self._cirrus_ceiling:.2f} (U/O)"
            if self._cirrus_layer is not None
            else "   cirrus --"
        )
        self._sun_readout.setText(
            f"sun  az {self._sun_azimuth:6.1f}   el {self._sun_elevation:+6.1f}   "
            f"[{self._palette_name}]\n"
            f"{SWEEP_PARAM}  {self._sweep_value:5.2f}x   (* / $)"
            f"    backward_gain {optics.backward_gain:.2f}x"
            f"    anisotropy {optics.forward_anisotropy:.2f}\n"
            f"coverage  cumulus {self._coverage:.2f}/{self._coverage_ceiling:.2f}"
            f" (T/Y){cirrus}"
            f"    edge {self._softness:.2f}s (N/M)"
        )

    def _place_sun_marker(self):
        """Put the marker along the sun vector, at a fixed distance from the eye.

        Riding with the camera is what makes it read as a direction rather than a
        place: it stays put in the sky however far you fly, exactly as the sun
        does, and the same vector is what lights the clouds.
        """
        cam_pos = self.camera.get_pos(self.render)
        offset = sun_vector(self._sun_azimuth, self._sun_elevation)
        self.sun_marker.set_pos(cam_pos + offset * SUN_MARKER_DISTANCE)

    def _print_pose(self):
        """Dump the camera pose, the sun, and each layer's field, for tweaking."""
        pos = self.camera.get_pos(self.render)
        hpr = self.camera.get_hpr(self.render)
        name, sun_color, sky_color, _ = sun_palette(self._sun_elevation, self._palette)
        print(
            f"camera pos=({pos.x:.0f}, {pos.y:.0f}, {pos.z:.0f}) "
            f"hpr=({hpr.x:.0f}, {hpr.y:.0f}, {hpr.z:.0f})\n"
            f"  sun az={self._sun_azimuth:.1f} el={self._sun_elevation:.1f} "
            f"palette={name}\n"
            f"    direct={tuple(round(c, 3) for c in sun_color)} "
            f"ambient={tuple(round(c, 3) for c in sky_color)}\n"
            f"  exposure={self.field._exposure} "
            f"sun_brightness={self.field._sun_brightness} "
            f"sky_strength={self.field._sky_strength} "
            f"sky_occlusion={self.field._sky_occlusion}"
        )
        for report, layer_spec in zip(
            self.field._layer_report, self.field._layer_specs
        ):
            spec, optics = layer_spec.field, layer_spec.optics
            print(
                f"  {report['type'].value}: slab={spec.slab} "
                f"feature={tuple(round(f) for f in spec.feature_size)} m "
                f"coverage={spec.coverage:.3f} edge={spec.edge_softness:.2f}s "
                f"window=({spec.threshold[0]:.4f},{spec.threshold[1]:.4f}) "
                f"density={spec.density}\n"
                f"    base_ramp={spec.base_ramp} "
                f"top_erosion={spec.top_erosion}^{spec.top_exponent} "
                f"phi={report['phi']:.2f} extinction={report['extinction']:.5f} "
                f"{report['particles']} billboards\n"
                f"    optics: {optics}"
            )

    def _update(self, task):
        dt = self._clock.get_dt()
        keys = self._keys

        # Rotations are applied about the camera's OWN axes: setP/setH/setR with
        # the node itself as the reference frame is Panda's idiom for a relative
        # rotation, which is what makes roll compose the way a cockpit expects.
        pitch = keys["pitch_up"] - keys["pitch_down"]
        yaw = keys["yaw_left"] - keys["yaw_right"]
        roll = keys["roll_right"] - keys["roll_left"]
        if pitch:
            self.camera.set_p(self.camera, pitch * PITCH_RATE * dt)
        if yaw:
            self.camera.set_h(self.camera, yaw * YAW_RATE * dt)
        if roll:
            self.camera.set_r(self.camera, roll * ROLL_RATE * dt)

        speed = SPEED * (BOOST if keys["boost"] else 1.0) * dt
        for positive, negative, setter in _TRANSLATIONS:
            throttle = keys[positive] - keys[negative]
            if throttle:
                getattr(self.camera, setter)(self.camera, throttle * speed)

        # The swept optic. Applied to every layer, and re-packed into the
        # layerParams uniform array -- no rebuild, because optics only ever affect
        # shading (see CloudField.set_optics).
        sweep = keys["shadow_up"] - keys["shadow_down"]
        if sweep:
            low, high = SWEEP_RANGE
            wanted = max(low, min(high, self._sweep_value + sweep * SWEEP_RATE * dt))
            try:
                self.field.set_optics(**{SWEEP_PARAM: wanted})
            except ValueError as refused:
                # The gains have a feasible region (see noise.phase_weights), and
                # a sweep is exactly the way to wander out of it. Hold the last
                # good value rather than letting the demo die mid-drag.
                print(f"  {SWEEP_PARAM} {wanted:.2f} refused: {refused}")
            else:
                self._sweep_value = wanted
            self._update_readout()

        # Coverage and edge softness. Both re-derive the drawn threshold from the
        # peaks measured at build time and re-pack -- no rebuild, no re-placement
        # (see CloudField.set_coverage, and COVERAGE_HEADROOM for why the ceiling).
        cover = keys["coverage_up"] - keys["coverage_down"]
        soften = keys["softness_up"] - keys["softness_down"]
        if cover or soften:
            if cover:
                self._coverage = max(
                    0.0,
                    min(
                        self._coverage_ceiling,
                        self._coverage + cover * COVERAGE_RATE * dt,
                    ),
                )
            if soften:
                low, high = SOFTNESS_RANGE
                self._softness = max(
                    low, min(high, self._softness + soften * SOFTNESS_RATE * dt)
                )
            # Every cumulus shell, since they share one field and must agree.
            for shell in range(CLOUD_SHELLS):
                self.field.set_coverage(
                    layer=shell,
                    coverage=self._coverage,
                    edge_softness=self._softness,
                )
            self._update_readout()

        cirrus = keys["cirrus_coverage_up"] - keys["cirrus_coverage_down"]
        if cirrus and self._cirrus_layer is not None:
            self._cirrus_coverage = max(
                0.0,
                min(
                    self._cirrus_ceiling,
                    self._cirrus_coverage + cirrus * COVERAGE_RATE * dt,
                ),
            )
            self.field.set_coverage(
                layer=self._cirrus_layer, coverage=self._cirrus_coverage
            )
            self._update_readout()

        # Sun: azimuth wraps, elevation clamps a little below the horizon so the
        # night side is reachable without the maths going through the pole.
        swing = keys["sun_ccw"] - keys["sun_cw"]
        climb = keys["sun_higher"] - keys["sun_lower"]
        if swing or climb:
            self._sun_azimuth = (
                self._sun_azimuth + swing * SUN_AZIMUTH_RATE * dt
            ) % 360
            self._sun_elevation = max(
                -12.0,
                min(89.0, self._sun_elevation + climb * SUN_ELEVATION_RATE * dt),
            )
            self._apply_sun()

        cam_pos = self.camera.get_pos(self.render)
        # Keep the ground centred under the camera. Not just so its edge stays out
        # of view: the droop is baked relative to the mesh centre, so centring it
        # on the camera is what makes the ground curve away from the SAME origin
        # the cloud shader measures its own droop from.
        self.ground.set_pos(cam_pos.x, cam_pos.y, 0.0)
        # Likewise the sun marker: a fixed distance along the sun vector, so it
        # stays put in the sky however far the camera flies.
        self._place_sun_marker()

        # The field re-faces its billboards, drifts, recycles and re-sorts against
        # the camera; without this the clouds are drawn but never update.
        self.field.update(cam_pos, dt)
        return task.cont


if __name__ == "__main__":
    # Before ShowBase: a roomy window, and no audio device for a graphics demo.
    loadPrcFileData("", "win-size 1280 800")
    loadPrcFileData("", "window-title SpaceFlight - cloud field demo")
    loadPrcFileData("", "audio-library-name null")
    CloudDemo().run()
