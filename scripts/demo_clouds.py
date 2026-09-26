"""
Standalone flythrough demo for the in-scene cloud field.

Flies a free camera around a big opaque smiley half-buried in a real
:class:`CloudField`, built with the real shaders, to judge cloud shape up close
and how clouds depth-composite against opaque geometry. Run it from a project
environment where space_flight is importable::

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
    T / Y           sweep the cumulus deck's COVERAGE down / up — the fraction of
                    sky it fills. Low is isolated puffs, high a sheet with holes.
    U / O           the same for the cirrus veil (needs WITH_CIRRUS)
    N / M           sweep the edge SOFTNESS, in standard deviations of the field.

                    Coverage sweeps are exact only up to the coverage the deck was
                    BUILT at, shown as "now/ceiling" (see COVERAGE_HEADROOM).

    C               toggle the cloud field
    V               toggle the high cirrus layer (off at start; needs WITH_CIRRUS)
    G               toggle the ground
    R               reset the camera to its starting pose
    F               print the camera pose, the sun, and the field's tuning
    ESC             quit

The disk in the sky marks the sun's direction and wears the direct light's colour.
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

from space_flight import PLANET_RADIUS_M
from space_flight.actors.player import CAMERA_FAR_M
from space_flight.global_architecture.asset_manager import AssetManager
from space_flight.scenes.cloud import PRESETS, CloudField, CloudLayer, CloudType
from space_flight.scenes.cloud.field import lod_shells

# ── Scene tuning ───────────────────────────────────────────────────────────────
# A second cloud type checks that layers sort against each other, but makes the
# cumulus deck harder to judge, so it is off by default.
WITH_CIRRUS = False
CIRRUS_CELL_SIZE = 2000.0  # cirrus features are larger, so fewer, larger cells

# Distant cloud and ground are fully hazed by here; must stay inside the
# outermost shell's 512 km half-width, since the haze is what hides its edge.
HORIZON_DISTANCE = 400000.0

GROUND_COLOR = (0.30, 0.36, 0.26, 1.0)
# Reaches past the horizon so its own bulge hides what lies beyond, for eye
# heights up to ~24 km.
GROUND_RADIUS = 550000.0
GROUND_RINGS = 96
GROUND_SEGMENTS = 256  # sets how round the horizon looks; 256 is below acuity

# Inside the far plane, and beyond the cloud field so cloud occludes it.
SUN_MARKER_DISTANCE = 60000.0
SUN_MARKER_ANGLE = 0.9  # degrees; a few times the real sun, to be findable
SUN_MARKER_SEGMENTS = 48

# Big enough to be half-buried in a cloud.
SMILEY_RADIUS = 500.0
SMILEY_POS = (0.0, 0.0, 1250.0)

# ── Sun ────────────────────────────────────────────────────────────────────────
SUN_AZIMUTH = 200.0  # degrees, 0 = +Y
SUN_ELEVATION = 35.0  # degrees above the horizon

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
SPEED = 400.0  # metres/second
BOOST = 5.0

# Coverage sweeps only re-derive the drawn threshold and never re-place
# billboards, so each type is BUILT this far above its preset to give the sweep
# room to go up. Pure over-placement: 0.15 costs ~1.6x frame time; set 0 to judge
# the shipped look at full rate.
COVERAGE_HEADROOM = 0.15
SWEEP_PARAM = "forward_gain"


def _with_headroom(cloud_type):
    """:returns: the type's preset field, with coverage raised by COVERAGE_HEADROOM"""
    field = PRESETS[cloud_type].field
    return replace(field, coverage=min(1.0, field.coverage + COVERAGE_HEADROOM))


_CUMULUS_BUILT = _with_headroom(CloudType.CUMULUS)
_CIRRUS_BUILT = _with_headroom(CloudType.CIRRUS)

# Held keys. Rotations and translations are about the camera's OWN axes, so they
# compose the way a cockpit expects: (plus key, minus key, setter, rate, HUD).
_ROTATIONS = (
    ("s", "z", "set_p", 40.0, "Z/S pitch"),
    ("d", "q", "set_r", 60.0, "Q/D roll"),
    ("a", "e", "set_h", 40.0, "A/E yaw"),
)
_TRANSLATIONS = (
    ("arrow_up", "arrow_down", "set_y", SPEED, "UP/DOWN fly"),
    ("arrow_right", "arrow_left", "set_x", SPEED, "LEFT/RIGHT slide"),
    ("w", "x", "set_z", SPEED, "W/X up-down"),
)
# Live sweeps. Each re-packs uniforms with no rebuild. forward_gain stops at 15:
# well into saturation, and clear of the ~20 where the phase solve goes
# infeasible. Elevation stops short of the pole.
# fmt: off
_SWEEPS = (
    # (plus key, minus key, attribute, rate/s, low, high,
    #  apply method, wraps, HUD)
    ("j", "l", "_sun_azimuth", 45.0, 0.0, 360.0,
     "_apply_sun", True, "J/L sun azimuth"),
    ("i", "k", "_sun_elevation", 25.0, -12.0, 89.0,
     "_apply_sun", False, "I/K sun height"),
    ("*", "$", "_sweep_value", 1.5, 1.0, 15.0,
     "_apply_optics", False, "*/$ forward_gain"),
    ("y", "t", "_coverage", 0.12, 0.0, _CUMULUS_BUILT.coverage,
     "_apply_coverage", False, "T/Y coverage"),
    ("o", "u", "_cirrus_coverage", 0.12, 0.0, _CIRRUS_BUILT.coverage,
     "_apply_cirrus_coverage", False, "U/O cirrus cov"),
    ("m", "n", "_softness", 0.5, 0.05, 3.0,
     "_apply_coverage", False, "N/M edge"),
)
# fmt: on
_CONTROLS = (
    "shift",
    *(key for row in (*_ROTATIONS, *_TRANSLATIONS, *_SWEEPS) for key in row[:2]),
)


def sun_palette(elevation, palette_index):
    """Direct and ambient light for a sun at *elevation*, and the matching sky.

    A hand-authored ramp standing in for Rayleigh/Mie: driving both lights from
    one number is what makes the clouds relight coherently.

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
    # The clear colour is the sky fill lifted a little, so horizon and haze agree.
    background = [min(1.0, c * 1.15 + 0.02) for c in sky]
    return name, tuple(blend), tuple(sky), (*background, 1.0)


def sun_vector(azimuth, elevation):
    """Unit vector toward the sun; Z-up, azimuth 0 along +Y increasing toward +X.

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

        # The game's own far plane, so the demo cannot flatter itself.
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

        layers = lod_shells(CloudType.CUMULUS, field=_CUMULUS_BUILT)
        self._cumulus_layers = range(len(layers))
        self._cirrus_layer = None
        if WITH_CIRRUS:
            self._cirrus_layer = len(layers)
            layers.append(
                CloudLayer(
                    CloudType.CIRRUS, cell_size=CIRRUS_CELL_SIZE, field=_CIRRUS_BUILT
                )
            )
        self._sweeps = tuple(
            row for row in _SWEEPS if WITH_CIRRUS or row[2] != "_cirrus_coverage"
        )

        print("building the cloud field ...")
        self.field = CloudField(
            parent=self.render,
            game=game,
            layers=layers,
            sun_direction=sun_vector(self._sun_azimuth, self._sun_elevation),
            horizon_distance=HORIZON_DISTANCE,
            planet_radius=PLANET_RADIUS_M,  # the same planet the ground curves over
        )
        for report in self.field._layer_report:
            print(
                f"  {report['type'].value}: {report['particles']:>6d} billboards in "
                f"{report['cells']:>5d} cells over {report['domain']:>7.0f} m"
                f"{'  seamless' if report['seamless'] else ''}"
            )
        print(f"  {self.field._n} billboards total")

        self._keys = dict.fromkeys(_CONTROLS, False)
        for key in _CONTROLS:
            self.accept(key, self._set_key, [key, True])
            self.accept(f"{key}-up", self._set_key, [key, False])
        presses = (
            ("c", "C clouds", self._toggle, [self.field.node]),
            ("v", "V cirrus", self._toggle_cirrus, []),
            ("g", "G ground", self._toggle, [self.ground]),
            ("p", "P palette", self._cycle_palette, []),
            ("r", "R reset", self._reset_camera, []),
            ("f", "F pose", self._print_pose, []),
            ("escape", "ESC", sys.exit, []),
        )
        for key, _label, method, args in presses:
            self.accept(key, method, extraArgs=args)
        # Only a real window can be closed; an offscreen buffer has no close event.
        if isinstance(self.win, GraphicsWindow):
            self.win.set_close_request_event("window-close")
            self.accept("window-close", sys.exit)

        hud = (
            [row[-1] for row in _ROTATIONS] + ["SHIFT boost"],
            [row[-1] for row in _TRANSLATIONS],
            [row[-1] for row in _SWEEPS],
            [label for _key, label, _method, _args in presses],
        )
        self._hud = OnscreenText(
            text="\n".join("   ".join(line) for line in hud),
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
        self._sweep_value = float(
            getattr(self.field._layer_specs[0].optics, SWEEP_PARAM)
        )
        # Start at the SHIPPED coverage: the headroom is there to sweep into.
        self._coverage = PRESETS[CloudType.CUMULUS].field.coverage
        self._cirrus_coverage = PRESETS[CloudType.CIRRUS].field.coverage
        self._softness = PRESETS[CloudType.CUMULUS].field.edge_softness
        self._apply_coverage()
        self._palette_name = ""
        self._cirrus_max_optical_depth = None
        self._cirrus_on = False
        if self._cirrus_layer is not None:
            self._apply_cirrus_coverage()
            self._cirrus_max_optical_depth = self.field._layer_specs[
                self._cirrus_layer
            ].optics.max_optical_depth
            self._cirrus_on = True
            self._toggle_cirrus()  # cirrus starts hidden
        # After the readout exists, which _apply_sun refreshes.
        self._apply_sun()

        self.taskMgr.add(self._update, "cloud_demo_update")
        print(__doc__)

    # ── internals ──────────────────────────────────────────────────────────────

    def _set_key(self, key, pressed):
        """Record a held key. :param key: Panda key name :param pressed: state"""
        self._keys[key] = pressed

    def _reset_camera(self):
        """Put the camera back at its starting pose."""
        self.camera.set_pos(Point3(*START_POS))
        self.camera.set_hpr(Vec3(*START_HPR))

    def _make_ground(self):
        """A polar ground mesh drooping by ``d^2 / (2R)``, like the cloud deck.

        A flat plane would clip the drooped far deck. The droop is baked relative
        to the mesh centre, which _update keeps under the camera: the same origin
        the cloud shader measures from.

        :returns: the ground NodePath, parented under render
        """
        curvature = 1.0 / (2.0 * PLANET_RADIUS_M)
        vdata = GeomVertexData("ground", GeomVertexFormat.get_v3c4(), Geom.UH_static)
        vdata.set_num_rows(1 + GROUND_RINGS * GROUND_SEGMENTS)
        writer = GeomVertexWriter(vdata, "vertex")
        writer.add_data3(0.0, 0.0, 0.0)  # directly under the camera
        # Per-vertex haze factor, baked since it depends only on the radius;
        # _recolour_ground rewrites the colour when the sun changes.
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
        """A camera-facing opaque disk standing in for the sun.

        Opaque, so it draws before the clouds and is occluded by any in front.

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

    def _toggle(self, nodepath):
        """Hide/show *nodepath*."""
        if nodepath.is_hidden():
            nodepath.show()
        else:
            nodepath.hide()

    def _toggle_cirrus(self):
        """Show/hide the cirrus layer by zeroing its optical-depth cap.

        Layers share one Geom (so they sort against each other), so a NodePath
        cannot hide one. A look toggle only: the billboards still rasterise.
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

    def _cycle_palette(self):
        """Step to the next time-of-day palette."""
        self._palette = (self._palette + 1) % len(SUN_PALETTES)
        self._apply_sun()

    def _apply_optics(self):
        """Push the swept optic to every layer (shading only, no rebuild)."""
        self.field.set_optics(**{SWEEP_PARAM: self._sweep_value})

    def _apply_coverage(self):
        """Push coverage and edge softness to every cumulus shell, which share one
        field and must agree."""
        for layer in self._cumulus_layers:
            self.field.set_coverage(
                layer=layer, coverage=self._coverage, edge_softness=self._softness
            )

    def _apply_cirrus_coverage(self):
        """Push the cirrus coverage to its layer."""
        self.field.set_coverage(
            layer=self._cirrus_layer, coverage=self._cirrus_coverage
        )

    def _apply_sun(self):
        """Push the current sun to the cloud field, the sky, the ground and the
        readout, so they can never disagree."""
        name, sun_color, sky_color, background = sun_palette(
            self._sun_elevation, self._palette
        )
        sun_dir = sun_vector(self._sun_azimuth, self._sun_elevation)
        # Haze to the BACKGROUND colour, not the ambient fill: the deck has to
        # recede into whatever is actually painted at the horizon.
        self.field.set_sun(sun_dir, sun_color, sky_color, haze_color=background[:3])
        self.set_background_color(*background)
        # Lifted toward white: the disk is the brightest thing in the frame even
        # when the light it casts has gone orange.
        self.sun_marker.set_color(
            *[min(1.0, 0.35 + 0.65 * channel) for channel in sun_color], 1.0
        )
        self._place_sun_marker()
        # Lit like the clouds (direct by elevation plus a share of sky fill), so
        # the ground dims and warms with them.
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
        """Refresh the on-screen sun and swept-parameter lines.

        backward_gain is shown so its independence from forward_gain is visible.
        """
        optics = self.field._layer_specs[0].optics
        cirrus = (
            f"   cirrus {self._cirrus_coverage:.2f}/{_CIRRUS_BUILT.coverage:.2f} (U/O)"
            if self._cirrus_layer is not None
            else "   cirrus --"
        )
        self._sun_readout.setText(
            f"sun  az {self._sun_azimuth:6.1f}   el {self._sun_elevation:+6.1f}   "
            f"[{self._palette_name}]\n"
            f"{SWEEP_PARAM}  {self._sweep_value:5.2f}x   (* / $)"
            f"    backward_gain {optics.backward_gain:.2f}x"
            f"    anisotropy {optics.forward_anisotropy:.2f}\n"
            f"coverage  cumulus {self._coverage:.2f}/{_CUMULUS_BUILT.coverage:.2f}"
            f" (T/Y){cirrus}"
            f"    edge {self._softness:.2f}s (N/M)"
        )

    def _place_sun_marker(self):
        """Put the marker a fixed distance along the sun vector from the eye, so it
        reads as a direction and stays put in the sky however far you fly."""
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

        # Relative to the camera itself, Panda's idiom for a local-axis move.
        for plus, minus, setter, rate, _label in _ROTATIONS:
            if turn := keys[plus] - keys[minus]:
                getattr(self.camera, setter)(self.camera, turn * rate * dt)
        boost = BOOST if keys["shift"] else 1.0
        for plus, minus, setter, rate, _label in _TRANSLATIONS:
            if throttle := keys[plus] - keys[minus]:
                getattr(self.camera, setter)(self.camera, throttle * rate * boost * dt)

        swept = False
        for plus, minus, attr, rate, low, high, apply, wraps, label in self._sweeps:
            if not (direction := keys[plus] - keys[minus]):
                continue
            swept = True
            previous = getattr(self, attr)
            wanted = previous + direction * rate * dt
            if wraps:
                wanted = low + (wanted - low) % (high - low)
            else:
                wanted = max(low, min(high, wanted))
            setattr(self, attr, wanted)
            try:
                getattr(self, apply)()
            except ValueError as refused:
                # The phase gains have a feasible region a sweep can wander out
                # of; hold the last good value rather than die mid-drag.
                setattr(self, attr, previous)
                print(f"  {label} {wanted:.2f} refused: {refused}")
        if swept:
            self._update_readout()

        cam_pos = self.camera.get_pos(self.render)
        # The droop is baked relative to the mesh centre, so the ground must stay
        # centred on the camera to curve from the same origin as the clouds.
        self.ground.set_pos(cam_pos.x, cam_pos.y, 0.0)
        self._place_sun_marker()
        self.field.update(cam_pos, dt)
        return task.cont


if __name__ == "__main__":
    # Before ShowBase: a roomy window, and no audio device for a graphics demo.
    loadPrcFileData("", "win-size 1280 800")
    loadPrcFileData("", "window-title SpaceFlight - cloud field demo")
    loadPrcFileData("", "audio-library-name null")
    CloudDemo().run()
