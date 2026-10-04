from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import numpy as np
from direct.gui.DirectGui import DirectLabel
from direct.showbase.ShowBaseGlobal import aspect2d, render2d
from panda3d.core import (
    CardMaker,
    Lens,
    NodePath,
    Point2,
    Point3,
    TextNode,
    Texture,
    TransparencyAttrib,
    Vec3,
)

from space_flight import DATAFILES_PATH, DEBUG_HUD, EPSILON_TOLERANCE
from space_flight.actors.energy import ENGINES, LASERS, SHIELDS
from space_flight.ui.utils import (
    ArcGauge,
    ColumnGauge,
    RollingDrum,
    make_text_line,
)
from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.actors.energy import EnergySystem
    from space_flight.game.flight_state import FlightState

EDGE_HORIZONTAL = 0.94
EDGE_VERTICAL = 0.88

# Smallest camera-space depth (forward distance) we let the projection see.
# When the target sits in the camera's XZ plane the true depth is ~0 and the
# perspective divide explodes, making the card jitter; clamping the depth to
# this non-zero magnitude keeps the projection finite and stable.
MIN_PROJECTION_DEPTH = 1e-3

# Target box half-extents, shared by the box and the scan bar filling it.
TARGET_BOX_HALF_WIDTH = 0.038
TARGET_BOX_HALF_HEIGHT = 0.03

# Ordnance HUD (see OrdnanceHUD), in the bottom-right corner's coordinates
ORDNANCE_HUD_RIGHT_X = -0.05
ORDNANCE_TEXT_SCALE = 0.05
DRUM_CENTER_Z = 0.25
FLARE_LINE_Z = 0.08

# Chatter text height: at the top of the screen, above the rear-view mirror
CHATTER_Z = 0.88

# Energy HUD (see EnergyHUD), in the bottom-left corner's coordinates: the HP,
# laser, engine and shield gauges, left to right
ENERGY_HUD_LEFT_X = 0.06
ENERGY_HUD_BOTTOM_Z = 0.06
GAUGE_SPACING = 0.04
ARC_GAUGE_RADIUS = 0.13
ARC_GAUGE_THICKNESS = 0.03
ARC_GAUGE_SEGMENTS = 60
GAUGE_TEXT_SCALE = 0.055
COLUMN_GAUGE_WIDTH = 0.04
COLUMN_GAUGE_HEIGHT = ARC_GAUGE_RADIUS
HP_GAUGE_COLOR = (1.0, 0.45, 0.75)
LASER_GAUGE_COLOR = (1.0, 0.15, 0.1)
ENGINE_GAUGE_COLOR = (0.15, 1.0, 0.25)
SHIELD_GAUGE_COLOR = (0.2, 0.55, 1.0)
# Gauge brightness, raised for the system power is redirected to
GAUGE_BRIGHTNESS = 0.6
FAVOURED_GAUGE_BRIGHTNESS = 1.0

# Target box tint, by missile lock: locked (a missile launched now would be
# guided to the target) or not.
TARGET_BOX_COLOR = (1.0, 1.0, 1.0, 1.0)
TARGET_BOX_MISSILE_LOCKED_COLOR = (1.0, 0.0, 0.0, 1.0)

# Crosshair (where the lasers go) and lead indicator (where to aim to hit the
# target), see AimHUD. Half-sizes keep their textures' (square) proportions.
CROSSHAIR_HALF_SIZE = 0.03
LEAD_INDICATOR_HALF_SIZE = 0.027
# Crosshair tint, by auto-aim state: locked (shots lead the target) or not.
CROSSHAIR_COLOR = (1.0, 1.0, 1.0, 1.0)
CROSSHAIR_LOCKED_COLOR = (1.0, 0.0, 0.0, 1.0)

# Transparent fill of the scan bar: while scanning, then by scan result.
SCAN_BAR_COLORS = {
    None: (1.0, 0.85, 0.0, 0.35),
    "clear": (0.0, 1.0, 0.0, 0.35),
    "contraband": (1.0, 0.0, 0.0, 0.35),
}


def project_to_screen(lens: Lens, cam_space_pos: Point3) -> tuple[float, float, bool]:
    """
    Project a camera-space point onto the screen.

    :param lens: The camera's lens
    :param cam_space_pos: The point, in camera space (modified: its depth is
        clamped away from zero, see MIN_PROJECTION_DEPTH)
    :return: Its screen coordinates (x, z), in [-1, 1] when on screen, and
        whether it is behind the camera. Behind the camera, the projection is
        mirrored through the screen centre (perspective divide by a negative
        depth).
    """
    # Clamp the depth (see MIN_PROJECTION_DEPTH), preserving its sign so
    # the behind-camera handling still triggers correctly.
    if abs(cam_space_pos.y) < MIN_PROJECTION_DEPTH:
        cam_space_pos.y = (
            MIN_PROJECTION_DEPTH if cam_space_pos.y >= 0 else -MIN_PROJECTION_DEPTH
        )

    screen_pos = Point2()
    lens.project(cam_space_pos, screen_pos)
    return screen_pos.x, screen_pos.y, cam_space_pos.y <= 0


def is_on_screen(x: float, z: float, behind: bool) -> bool:
    """
    :param x: Projected screen x coordinate
    :param z: Projected screen z coordinate
    :param behind: Whether the point is behind the camera
    :return: Whether the projected point is ahead and inside the screen
    """
    return not behind and abs(x) <= 1.0 and abs(z) <= 1.0


def make_hud_card(
    name: str, half_width: float, half_height: float, texture: Texture | None = None
) -> NodePath:
    """
    :param name: The card's node name
    :param half_width: The card's half-width
    :param half_height: The card's half-height
    :param texture: The card's texture, if any (with alpha transparency)
    :return: A card centred on its origin, drawn over the scene and the other UI
    """
    cm = CardMaker(name)
    cm.setFrame(-half_width, half_width, -half_height, half_height)
    card = NodePath(cm.generate())
    if texture is not None:
        card.setTexture(texture)
    card.setTransparency(TransparencyAttrib.MAlpha)
    card.setDepthTest(False)
    card.setDepthWrite(False)
    card.setBin("fixed", 10)
    return card


class HUD:
    """
    Creates an overlay of text displaying important
    simulation parameters on screen.
    """

    def __init__(self, game: FlightState) -> None:
        self.game = game
        self.id = uuid.uuid4()
        self.fps_counter_enabled = game.app.graphics_settings.config["hud"][
            "fps_counter"
        ]

        # Debug info
        if DEBUG_HUD:
            self.debug = TextNode("Debug")
            self.debug.setSmallCaps(True)
            self.debug.setShadow(0.05, 0.05)
            self.debug.setShadowColor(0, 0, 0, 1)
            self.debug_textNodePath = aspect2d.attachNewNode(self.debug)
            self.debug_textNodePath.setScale(0.07)
            self.debug_textNodePath.reparentTo(self.game.app.a2dTopLeft)
            self.debug_textNodePath.setPos(0.05, 0, -0.1)

        # Performance info
        if self.fps_counter_enabled:
            self.fps_counter = TextNode("FPS")
            self.fps_counter.setSmallCaps(True)
            self.fps_counter.setShadow(0.05, 0.05)
            self.fps_counter.setShadowColor(0, 0, 0, 1)
            self.fps_textNodePath = aspect2d.attachNewNode(self.fps_counter)
            self.fps_textNodePath.setScale(0.07)
            self.fps_textNodePath.reparentTo(self.game.app.a2dTopRight)
            self.fps_textNodePath.setPos(-0.4, 0, -0.1)

        # Event text
        self.event_text_endtime = 0.0
        self.events = TextNode("Events")
        self.events.setSmallCaps(True)
        self.events.setShadow(0.05, 0.05)
        self.events.setShadowColor(0, 0, 0, 1)
        self.events_textNodePath = aspect2d.attachNewNode(self.events)
        self.events_textNodePath.setScale(0.1)
        self.events_textNodePath.setPos(0.0, 0.0, 0.2)

        # Chatter text
        self.chatter_text_endtime = 0.0
        self.chatter = TextNode("Chatter")
        self.chatter.setSmallCaps(True)
        self.chatter.setTextColor(252 / 255, 212 / 255, 10 / 255, 1)
        self.chatter.setShadow(0.05, 0.05)
        self.chatter.setShadowColor(0, 0, 0, 1)
        self.chatter_textNodePath = aspect2d.attachNewNode(self.chatter)
        self.chatter_textNodePath.setScale(0.075)
        self.chatter_textNodePath.setPos(0.0, 0, CHATTER_Z)

        # Ordnance: secondary weapons and flares left
        self.ordnance_hud = OrdnanceHUD(
            game=self.game, parent_node=self.game.app.a2dBottomRight
        )

        # HP and energy gauges
        self.energy_hud = EnergyHUD(
            game=self.game, parent_node=self.game.app.a2dBottomLeft
        )

        # Wrap long lines before they run off the edges of the screen.
        text_wrap_width = 3.5 * EDGE_HORIZONTAL / self.events_textNodePath.getScale()[0]
        self.events.setWordwrap(text_wrap_width)
        self.chatter.setWordwrap(text_wrap_width)

        self.game.method_lists[self.id] = [self.hud_update_task]

    def hud_update_task(self) -> None:
        """
        A method that gets the relevant informations from the sim
        and updates the text displayed in the HUD.
        """
        self.update_debug_hud()
        self.ordnance_hud.update()
        self.energy_hud.update()
        self.clear_scenario_hud()

    def set_event_text(self, text: str, display_time_s: float = 2.5) -> None:
        """
        Sets an event text and its display time
        """
        self.events.set_text(text)
        self.event_text_endtime = (
            self.game.game_time.get_current_time() + display_time_s
        )
        self.events.setAlign(TextNode.ACenter)

    def set_chatter_text(self, text: str, display_time_s: float = 2.5) -> None:
        """
        Sets a chatter text and its display time
        """
        self.chatter.set_text(text)
        self.chatter_text_endtime = (
            self.game.game_time.get_current_time() + display_time_s
        )
        self.chatter.setAlign(TextNode.ACenter)

    def clear_scenario_hud(self) -> None:
        """
        A method to clear the scenario text on screen if the display time is spent
        """
        current_time = self.game.game_time.get_current_time()
        if current_time > self.event_text_endtime:
            self.events.set_text("")
        if current_time > self.chatter_text_endtime:
            self.chatter.set_text("")

    def update_debug_hud(self) -> None:
        """
        A method to update debug info on screen
        """
        if self.fps_counter_enabled:
            frame_rate = self.game.game_time.get_average_frame_rate()
            self.fps_counter.setText(f"FPS = {frame_rate:.0f}")

        if DEBUG_HUD:
            # Count team members
            n_team_1 = 0
            n_team_2 = 0
            for actor in self.game.interactions.live_actors:
                if actor.team == 1:
                    n_team_1 += 1
                elif actor.team == 2:
                    n_team_2 += 1

            player_text = (
                ""
                "Player Speed = "
                f"{magnitude(self.game.player.pawn.state[7:10]):.1f}m/s\n"
                f"Player health = {self.game.player.pawn.health:.1f}\n"
                f"Player shield = {self.game.player.pawn.shield:.1f}\n"
                f"Player lift = {magnitude(self.game.player.pawn.lift_n):.1f}N\n"
                f"Player drag = {magnitude(self.game.player.pawn.drag_n):.1f}N\n"
                f"Time = {self.game.game_time.get_current_time():.0f}\n"
                f"Team 1 strength = {n_team_1}\n"
                f"Team 2 strength = {n_team_2}\n"
                "\n"
                "Player has target lock = "
                f"{self.game.player.pawn.auto_aim.is_target_acquired}\n"
                "\n"
            )
            try:
                bot_text = (
                    "Lead Bot angle to target = "
                    f"{self.game.lead_bot.pilot.angle_to_target_deg:.1f}°\n"
                    "Lead Bot distance to target = "
                    f"{self.game.lead_bot.navigator.distance_to_waypoint_m:.1f}m\n"
                    "Lead Bot next waypoint = "
                    f"{self.game.lead_bot.navigator.next_waypoint_idx:.1f}\n"
                    "Lead Bot health = "
                    f"{self.game.lead_bot.pawn.health:.1f}\n"
                    # "Lead Bot shield = "
                    # f"{self.game.lead_bot.pawn.shield:.1f}\n"
                    "Lead Bot throttle = "
                    f"{self.game.lead_bot.pilot.throttle:.4f}\n"
                    "Lead Bot Speed = "
                    f"{magnitude(self.game.lead_bot.pawn.state[7:10]):.1f}m/s\n"
                    "\n"
                    # "Lead Bot has target lock = "
                    # f"{self.game.lead_bot.pawn.auto_aim.is_target_acquired}\n"
                    # "\n"
                )
            except AttributeError:
                bot_text = ""
            try:
                turret_text = (
                    "Turret position = "
                    f"{np.array(self.game.turret.pawn.node.getPos())}\n"
                    "Turret angle to target = "
                    f"{self.game.turret.pilot.angle_to_target_deg:.1f}°\n"
                    "Turret health = "
                    f"{self.game.turret.pawn.health:.1f}\n"
                    "\n"
                )
            except AttributeError:
                turret_text = ""
            hud_text = player_text + bot_text + turret_text

            self.debug.setText(hud_text)

    def clean(self) -> None:
        """
        Cleans the HUD object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        if DEBUG_HUD:
            self.debug_textNodePath.removeNode()
            self.debug = None
        if self.fps_counter_enabled:
            self.fps_textNodePath.removeNode()
            self.fps_counter = None
        self.events_textNodePath.removeNode()
        self.events = None
        self.chatter_textNodePath.removeNode()
        self.chatter = None
        self.ordnance_hud.clean()
        self.ordnance_hud = None
        self.energy_hud.clean()
        self.energy_hud = None
        self.game = None


class OrdnanceHUD:
    """
    The player's ordnance, bottom right: the secondary weapons on a rolling
    drum (see :class:`~space_flight.ui.utils.RollingDrum`), the selected one
    facing the player, and the flares left under it. Spent ordnance keeps its
    line, at x0.
    """

    def __init__(self, game: FlightState, parent_node: NodePath) -> None:
        """
        :param game: The flight state
        :param parent_node: The node the lines are anchored to (bottom-right
            corner of the screen)
        """
        self.game = game
        self.root = parent_node.attachNewNode("ordnanceHud")
        self.root.setPos(ORDNANCE_HUD_RIGHT_X, 0, 0)

        self.drum = RollingDrum(
            parent_node=self.root,
            clock=self.game.game_time.get_current_time,
            text_scale=ORDNANCE_TEXT_SCALE,
        )
        self.drum.root.setZ(DRUM_CENTER_Z)
        self.flare_line = make_text_line(self.root, "flares")
        self.flare_line.setPos(0, 0, FLARE_LINE_Z)
        self.flare_line.setScale(ORDNANCE_TEXT_SCALE)

    @staticmethod
    def format_line(name: str, stock: int) -> str:
        """
        :param name: The ordnance's display name
        :param stock: How many are left
        :return: The HUD line for it
        """
        return f"{name} {stock}"

    def update(self) -> None:
        """
        Refresh the secondary weapons drum (rolling it if the selection changed)
        and the flares line.
        """
        pawn = self.game.player.pawn
        self.drum.update(
            items=pawn.secondary_cycle(),
            selected=pawn.selected_secondary,
            label=lambda launcher: self.format_line(
                launcher.display_name, launcher.stock
            ),
        )

        flare_launcher = pawn.flare_launcher
        self.flare_line.node().setText(
            self.format_line(
                flare_launcher.display_name if flare_launcher else "FLARE",
                flare_launcher.stock if flare_launcher else 0,
            )
        )

    def clean(self) -> None:
        """
        Cleans the OrdnanceHUD object
        """
        self.drum.clean()
        self.drum = None
        self.root.removeNode()
        self.root = None
        self.flare_line = None
        self.game = None


def gauge_brightness(energy: EnergySystem, system: str) -> float:
    """
    :param energy: The ship's energy system
    :param system: The system the gauge shows (ENGINES, LASERS or SHIELDS)
    :return: The gauge's brightness: raised if power is redirected to it
    """
    if energy.is_favoured(system):
        return FAVOURED_GAUGE_BRIGHTNESS
    return GAUGE_BRIGHTNESS


class EnergyHUD:
    """
    The player's gauges, bottom left. Left to right:

    - HP: a pink half-ring, the health left written at its centre
    - lasers: a red column
    - engines: a green half-ring, the ship's speed written at its centre
    - shields: a blue half-ring, the shield strength written at its centre
      (only for shielded ships)

    The energy gauges of the system power is redirected to are brighter.
    """

    def __init__(self, game: FlightState, parent_node: NodePath) -> None:
        """
        :param game: The flight state
        :param parent_node: The node the gauges are anchored to (bottom-left
            corner of the screen)
        """
        self.game = game
        self.root = parent_node.attachNewNode("energyHud")
        self.root.setPos(ENERGY_HUD_LEFT_X, 0, ENERGY_HUD_BOTTOM_Z)
        # Shown by the first update
        self.root.hide()

        x = ARC_GAUGE_RADIUS
        self.hp_gauge = self._make_arc_gauge("hpGauge", HP_GAUGE_COLOR, x)
        self.hp_gauge.set_brightness(GAUGE_BRIGHTNESS)
        x += ARC_GAUGE_RADIUS + GAUGE_SPACING + 0.5 * COLUMN_GAUGE_WIDTH
        self.laser_gauge = ColumnGauge(
            parent_node=self.root,
            name="laserGauge",
            color=LASER_GAUGE_COLOR,
            width=COLUMN_GAUGE_WIDTH,
            height=COLUMN_GAUGE_HEIGHT,
        )
        self.laser_gauge.root.setX(x)
        x += 0.5 * COLUMN_GAUGE_WIDTH + GAUGE_SPACING + ARC_GAUGE_RADIUS
        self.engine_gauge = self._make_arc_gauge("engineGauge", ENGINE_GAUGE_COLOR, x)
        x += 2.0 * ARC_GAUGE_RADIUS + GAUGE_SPACING
        self.shield_gauge = self._make_arc_gauge("shieldGauge", SHIELD_GAUGE_COLOR, x)
        if not self.game.player.pawn.energy.has_shields:
            self.shield_gauge.root.hide()

    def _make_arc_gauge(
        self, name: str, color: tuple[float, float, float], x: float
    ) -> ArcGauge:
        """
        :param name: The gauge's node name
        :param color: The gauge's colour
        :param x: The gauge's centre's position along the row
        :return: A half-ring gauge in the row
        """
        gauge = ArcGauge(
            parent_node=self.root,
            name=name,
            color=color,
            radius=ARC_GAUGE_RADIUS,
            thickness=ARC_GAUGE_THICKNESS,
            n_segments=ARC_GAUGE_SEGMENTS,
            text_scale=GAUGE_TEXT_SCALE,
        )
        gauge.root.setX(x)
        return gauge

    def update(self) -> None:
        """
        Refresh the gauges' levels, texts and brightness.
        """
        if self.root.isHidden():
            self.root.show()
        pawn = self.game.player.pawn
        energy = pawn.energy

        health = max(pawn.health, 0.0)
        self.hp_gauge.set_level(health / pawn.max_health)
        self.hp_gauge.set_text(f"{health:.0f}")

        self.laser_gauge.set_level(energy.lasers)
        self.laser_gauge.set_brightness(gauge_brightness(energy, LASERS))

        self.engine_gauge.set_level(energy.engines)
        self.engine_gauge.set_text(f"{magnitude(pawn.speed):.0f} m/s")
        self.engine_gauge.set_brightness(gauge_brightness(energy, ENGINES))

        if energy.has_shields:
            self.shield_gauge.set_level(pawn.shield / pawn.max_shield)
            self.shield_gauge.set_text(f"{pawn.shield:.0f}")
            self.shield_gauge.set_brightness(gauge_brightness(energy, SHIELDS))

    def clean(self) -> None:
        """
        Cleans the EnergyHUD object
        """
        for gauge in (
            self.hp_gauge,
            self.laser_gauge,
            self.engine_gauge,
            self.shield_gauge,
        ):
            gauge.clean()
        self.hp_gauge = None
        self.laser_gauge = None
        self.engine_gauge = None
        self.shield_gauge = None
        self.root.removeNode()
        self.root = None
        self.game = None


class TargetHUD:
    def __init__(self, game: FlightState) -> None:
        self.game = game
        self.id = uuid.uuid4()

        # Prepare target indicator atachment and aspect ratio correction
        self.root = NodePath("targetHudRoot")
        self.root.reparentTo(render2d)

        self.aspect = NodePath("aspectFix")
        self.aspect.reparentTo(self.root)

        # Define target indicator
        self.square = make_hud_card(
            "targetBox",
            TARGET_BOX_HALF_WIDTH,
            TARGET_BOX_HALF_HEIGHT,
            self.game.app.loader.loadTexture(
                DATAFILES_PATH / "models/UI/target_indicator_white.png"
            ),
        )
        self.square.reparentTo(self.aspect)

        # Define scan progress bar: fills the target box from its left edge,
        # scaled horizontally by the target's scan progress (see
        # space_flight.actors.scan)
        scan_cm = CardMaker("scanBar")
        scan_cm.setFrame(
            0,
            2 * TARGET_BOX_HALF_WIDTH,
            -TARGET_BOX_HALF_HEIGHT,
            TARGET_BOX_HALF_HEIGHT,
        )
        self.scan_bar = NodePath(scan_cm.generate())
        self.scan_bar.setTransparency(TransparencyAttrib.MAlpha)
        self.scan_bar.reparentTo(self.aspect)
        self.scan_bar.setPos(-TARGET_BOX_HALF_WIDTH, 0, 0)

        # Define distance label
        self.distance_label = DirectLabel(
            text="",
            scale=0.04,
            pos=(0, 0, -0.06),
            parent=self.aspect,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        # Define name label
        self.name_label = DirectLabel(
            text="",
            scale=0.02,
            pos=(0, 0, 0.04),
            parent=self.aspect,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        self.game.method_lists[self.id] = [self.target_hud_update_task]

        # Make sure the targeting HUD is rendered above other UI things (the
        # box already is, see make_hud_card)
        self.scan_bar.setDepthTest(False)
        self.scan_bar.setDepthWrite(False)
        self.scan_bar.setBin("fixed", 9)

        self.distance_label.setDepthTest(False)
        self.distance_label.setDepthWrite(False)
        self.distance_label.setBin("fixed", 10)

        self.name_label.setDepthTest(False)
        self.name_label.setDepthWrite(False)
        self.name_label.setBin("fixed", 10)

        # Hide at startup
        self.distance_label.hide()
        self.name_label.hide()
        self.square.hide()
        self.scan_bar.hide()

    def target_hud_update_task(self) -> None:
        target = self.game.player.pawn.target
        if target is None:
            # Either there is no target selected or it has been purged recently
            self.distance_label.hide()
            self.name_label.hide()
            self.square.hide()
            self.scan_bar.hide()
            self.game.player.pawn.target_id = None
            self.game.player.pawn.target_idx = None
        elif target.is_dead:
            # The target died recently but has not yet been purged
            self.distance_label.hide()
            self.name_label.hide()
            self.square.hide()
            self.scan_bar.hide()
            self.game.player.pawn.target = None
            self.game.player.pawn.target_id = None
            self.game.player.pawn.target_idx = None
        else:
            # Most targets show their parent's name (a ship shows its bot's name).
            # Subsystems have no named parent, so fall back to their own name.
            display_name = getattr(target.parent, "name", None) or getattr(
                target, "name", ""
            )
            scan = getattr(target, "scan", None)
            status = scan.status_text if scan is not None else ""
            if status and scan is not None:
                self.name_label["text"] = f"{display_name} - {status}"
                self.scan_bar.setScale(max(scan.progress, 1e-3), 1, 1)
                self.scan_bar.setColor(*SCAN_BAR_COLORS[scan.result])
                self.scan_bar.show()
            else:
                self.name_label["text"] = display_name
                self.scan_bar.hide()
            self.distance_label.show()
            self.name_label.show()
            self.square.show()
            self.update_lock_tint()

            cam = self.game.app.cam
            lens = self.game.app.camLens

            aspect = self.game.app.getAspectRatio()
            self.aspect.setScale(1, 1, aspect)

            # World position of target
            target_pos = target.position
            world_pos = Point3(*target_pos)

            # Convert to camera space and project. Default case: target is
            # ahead, just take the projection
            cam_space_pos = cam.getRelativePoint(self.game.root_node, world_pos)
            indic_x, indic_z, behind = project_to_screen(lens, cam_space_pos)

            if behind:
                # Target is behind the camera. The perspective divide in
                # lens.project() is by a negative depth (cam_space_pos.y < 0),
                # which mirrors the projection through the screen centre: both
                # indic_x and indic_z come out with the wrong sign. Negate them
                # to recover the true on-screen direction (sign(cam_x),
                # sign(cam_z)), so the indicator sits on the correct edge and
                # only ever switches sides once, when the target passes directly
                # behind.
                indic_x = -indic_x
                indic_z = -indic_z

            inside = (
                not behind
                and abs(indic_x) <= EDGE_HORIZONTAL
                and abs(indic_z) <= EDGE_VERTICAL
            )
            if not inside:
                # Target is off-screen (out of the FoV or behind): pin the
                # indicator to the screen border along the direction to the
                # target. We intersect the (indic_x, indic_z) ray with the edge
                # rectangle by scaling the whole vector by a single factor, so
                # the position varies smoothly as the direction rotates.
                #
                # Clamping each axis independently instead would drive both
                # components to their maxima whenever the projection is large on
                # both axes (which happens as the depth approaches zero, near
                # the camera's XZ plane), snapping the card to a corner that
                # flips around as the target wobbles -> jitter. Ray-to-rectangle
                # scaling avoids that and is continuous with the in-view
                # projection (the scale is exactly 1 at the border).
                ax = abs(indic_x)
                az = abs(indic_z)
                scale_x = EDGE_HORIZONTAL / ax if ax > EPSILON_TOLERANCE else np.inf
                scale_z = EDGE_VERTICAL / az if az > EPSILON_TOLERANCE else np.inf
                scale = min(scale_x, scale_z)
                if np.isfinite(scale):
                    indic_x *= scale
                    indic_z *= scale
                else:
                    # Direction undefined (target dead centre while behind):
                    # park the indicator on one side rather than at the origin.
                    indic_x = EDGE_HORIZONTAL
                    indic_z = 0.0

            self.root.setPos(indic_x, 0, indic_z)

            # Find distance and write it below the box
            distance = (
                world_pos - self.game.app.camera.getPos(self.game.root_node)
            ).length()
            self.distance_label["text"] = f"{distance:.0f} m"

    def update_lock_tint(self) -> None:
        """
        Turn the target box red while the armed missile is locked on the target
        (a missile launched now would be guided to it), white otherwise.
        """
        locked = self.game.player.pawn.is_missile_locked
        self.square.setColorScale(
            *(TARGET_BOX_MISSILE_LOCKED_COLOR if locked else TARGET_BOX_COLOR)
        )

    def clean(self) -> None:
        """
        Clean the TargetHud object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.name_label.destroy()
        self.distance_label.destroy()
        self.square.removeNode()
        self.scan_bar.removeNode()
        self.aspect.removeNode()
        self.root.removeNode()
        self.game = None  # type: ignore[assignment]  # released on clean


class AimHUD:
    """
    The player's aiming cues:

    - a crosshair where the lasers go: the ship's nose direction, projected as
      a point at infinity (the cannons fire parallel to the nose), so it stays
      true when the pilot's head is jolted or turned. White, red while auto-aim
      is locked (shots lead the target).
    - a lead indicator where to aim to hit the target: its position predicted
      by auto-aim (see AutoAim.predict_target_position). Shown only with a
      target, its prediction ahead and on screen.
    """

    def __init__(self, game: FlightState) -> None:
        self.game = game
        self.id = uuid.uuid4()

        # The cards are placed in screen coordinates, and scaled for the aspect
        # ratio (see aim_hud_update_task)
        self.root = NodePath("aimHudRoot")
        self.root.reparentTo(render2d)

        loader = self.game.app.loader
        self.crosshair = make_hud_card(
            "crosshair",
            CROSSHAIR_HALF_SIZE,
            CROSSHAIR_HALF_SIZE,
            loader.loadTexture(DATAFILES_PATH / "models/UI/crosshair.png"),
        )
        self.crosshair.reparentTo(self.root)
        self.lead_indicator = make_hud_card(
            "leadIndicator",
            LEAD_INDICATOR_HALF_SIZE,
            LEAD_INDICATOR_HALF_SIZE,
            loader.loadTexture(DATAFILES_PATH / "models/UI/lead_indicator.png"),
        )
        self.lead_indicator.reparentTo(self.root)

        # Hide at startup
        self.crosshair.hide()
        self.lead_indicator.hide()

        self.game.method_lists[self.id] = [self.aim_hud_update_task]

    def aim_hud_update_task(self) -> None:
        """
        Place the crosshair and the lead indicator, and tint the crosshair.
        """
        aspect = self.game.app.getAspectRatio()
        self.crosshair.setScale(1, 1, aspect)
        self.lead_indicator.setScale(1, 1, aspect)
        self.update_crosshair()
        self.update_lead_indicator()

    def update_crosshair(self) -> None:
        """
        Place the crosshair where the nose points, tinted by the auto-aim lock;
        hidden if that is off screen (the pilot looking away).
        """
        pawn = self.game.player.pawn
        nose = self.game.app.cam.getRelativeVector(
            self.game.root_node, Vec3(*pawn.forward)
        )
        x, z, behind = project_to_screen(self.game.app.camLens, Point3(nose))
        if not is_on_screen(x, z, behind):
            self.crosshair.hide()
            return
        self.crosshair.setPos(x, 0, z)
        locked = pawn.auto_aim.is_target_acquired
        self.crosshair.setColorScale(
            *(CROSSHAIR_LOCKED_COLOR if locked else CROSSHAIR_COLOR)
        )
        self.crosshair.show()

    def lead_indicator_position(self) -> tuple[float, float] | None:
        """
        :return: The screen position of the target's predicted position, or
            None if there is no live target, no prediction, or it is behind the
            camera or off screen
        """
        pawn = self.game.player.pawn
        target = pawn.target
        if target is None or target.is_dead:
            return None
        lead_position = pawn.auto_aim.predict_target_position()
        if lead_position is None:
            return None
        cam_space_pos = self.game.app.cam.getRelativePoint(
            self.game.root_node, Point3(*lead_position)
        )
        x, z, behind = project_to_screen(self.game.app.camLens, cam_space_pos)
        if not is_on_screen(x, z, behind):
            return None
        return x, z

    def update_lead_indicator(self) -> None:
        """
        Place the lead indicator, or hide it (see lead_indicator_position).
        """
        position = self.lead_indicator_position()
        if position is None:
            self.lead_indicator.hide()
            return
        x, z = position
        self.lead_indicator.setPos(x, 0, z)
        self.lead_indicator.show()

    def clean(self) -> None:
        """
        Clean the AimHUD object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.crosshair.removeNode()
        self.lead_indicator.removeNode()
        self.root.removeNode()
        self.game = None  # type: ignore[assignment]  # released on clean
