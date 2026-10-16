from __future__ import annotations

import uuid
from collections import deque
from typing import TYPE_CHECKING, Callable, NamedTuple, Optional

import numpy as np
from direct.gui.DirectGui import DirectLabel
from direct.showbase.ShowBaseGlobal import aspect2d, render2d
from panda3d.core import (
    CardMaker,
    Lens,
    LineSegs,
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
from space_flight.ai.missile.incoming_missile import nearest_incoming
from space_flight.game.scenario.objectives import ACTIVE, COMPLETE, FAILED
from space_flight.global_architecture.gameplay_settings import gameplay_config
from space_flight.ui.utils import (
    TEXT_CENTER_OFFSET,
    ArcGauge,
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

# How long each scenario text stays up, in seconds of game time: radio
# chatter, tutorial hints and event banners (see ScenarioText)
CHATTER_DISPLAY_S = 3.0
HINT_DISPLAY_S = 5.0
EVENT_DISPLAY_S = 5.0

# Event banner: centred above the crosshair
EVENT_Z = 0.2
EVENT_TEXT_SCALE = 0.1
# Tutorial hints: in place of the event banner, smaller and wrapped narrower
HINT_TEXT_SCALE = 0.06
HINT_WRAP_WIDTH = 1.6

# Objectives checklist (see ObjectivesHUD), in the top-left corner's
# coordinates: one line per objective, its checkbox on the left. Lower with
# the debug text, which takes that corner.
OBJECTIVES_LEFT_X = 0.06
OBJECTIVES_TOP_Z = -0.9 if DEBUG_HUD else -0.08
OBJECTIVES_TEXT_SCALE = 0.045
OBJECTIVES_LINE_SPACING = 0.06
OBJECTIVE_BOX_HALF_SIZE = 0.014
OBJECTIVE_TEXT_X = 0.04
OBJECTIVE_COLORS = {
    ACTIVE: (1.0, 1.0, 1.0, 1.0),
    COMPLETE: (0.45, 1.0, 0.45, 1.0),
    FAILED: (1.0, 0.35, 0.3, 1.0),
}
# A line blinks for a while once added, ticked or failed
OBJECTIVE_FLASH_S = 1.5
OBJECTIVE_FLASH_PERIOD_S = 0.25
OBJECTIVE_FLASH_DIM_ALPHA = 0.3

# Energy HUD (see EnergyHUD), in the bottom-left corner's coordinates: the HP,
# shield, engine and laser gauges, left to right
ENERGY_HUD_LEFT_X = 0.06
ENERGY_HUD_BOTTOM_Z = 0.06
GAUGE_SPACING = 0.04
ARC_GAUGE_RADIUS = 0.15
ARC_GAUGE_THICKNESS = 0.035
ARC_GAUGE_OUTLINE_WIDTH = 0.006
ARC_GAUGE_SEGMENTS = 60
GAUGE_TEXT_SCALE = 0.06
HP_GAUGE_COLOR = (1.0, 0.45, 0.75)
LASER_GAUGE_COLOR = (1.0, 0.15, 0.1)
ENGINE_GAUGE_COLOR = (0.15, 1.0, 0.25)
SHIELD_GAUGE_COLOR = (0.2, 0.55, 1.0)
# Engine gauge text while the engines are dead (instead of the speed)
ENGINES_OFFLINE_TEXT = "OFFLINE"
# Appended to the target's name while it is disabled by ion hits
DISABLED_TEXT = "DISABLED"
# Gauge brightness, raised for the system power is redirected to (its outline
# is also highlighted, and the gauge grown about its base by the scale below,
# which the spacing leaves room for)
GAUGE_BRIGHTNESS = 0.6
FAVOURED_GAUGE_BRIGHTNESS = 1.0
FAVOURED_GAUGE_SCALE = 1.1

# Target box tint, by missile lock: locked (a missile launched now would be
# guided to the target) or not.
TARGET_BOX_COLOR = (1.0, 1.0, 1.0, 1.0)
TARGET_BOX_MISSILE_LOCKED_COLOR = (1.0, 0.0, 0.0, 1.0)

# Crosshair and lead indicator half-sizes, in their textures' proportions
CROSSHAIR_HALF_SIZE = 0.03
LEAD_INDICATOR_HALF_SIZE = 0.027
MISSILE_MARKER_HALF_SIZE = 1.5 * LEAD_INDICATOR_HALF_SIZE
# Crosshair tint, by auto-aim lock (shots lead the target) or not.
CROSSHAIR_COLOR = (1.0, 1.0, 1.0, 1.0)
CROSSHAIR_LOCKED_COLOR = (1.0, 0.0, 0.0, 1.0)

# Incoming missile warning (see AimHUD): the warning line below the screen centre,
# in aspect2d coordinates, and the marker on the nearest missile, a violet ring
# like the lead indicator's, only bigger
MISSILE_WARNING_COLOR = (1.0, 0.1, 0.1, 1.0)
MISSILE_WARNING_Z = -0.3
MISSILE_WARNING_TEXT_SCALE = 0.07
MISSILE_MARKER_COLOR = (0.8, 0.3, 1.0, 1.0)
# The warning line blinks faster as the missile closes in: its blink period is
# the time to impact divided by this, within the bounds below
MISSILE_WARNING_BLINKS_PER_IMPACT = 5.0
MISSILE_WARNING_MIN_BLINK_PERIOD_S = 0.15
MISSILE_WARNING_MAX_BLINK_PERIOD_S = 0.6

# Transparent fill of the scan bar: while scanning, then by scan result.
SCAN_BAR_COLORS = {
    None: (1.0, 0.85, 0.0, 0.35),
    "clear": (0.0, 1.0, 0.0, 0.35),
    "contraband": (1.0, 0.0, 0.0, 0.35),
}


def project_to_screen(lens: Lens, cam_space_pos: Point3) -> tuple[float, float, bool]:
    """
    :param lens: The camera's lens
    :param cam_space_pos: A point in camera space (its depth is clamped away
        from zero in place, see MIN_PROJECTION_DEPTH)
    :return: Its screen coordinates (x, z), in [-1, 1] when on screen, and
        whether it is behind the camera (then the projection is mirrored
        through the screen centre)
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
    :return: Whether a point projected at (x, z) is ahead and inside the screen
    """
    return not behind and abs(x) <= 1.0 and abs(z) <= 1.0


def pin_to_screen_edge(x: float, z: float, behind: bool) -> tuple[float, float]:
    """
    Where to put an indicator that never leaves the screen: on a point's
    projection while it is inside the edge rectangle (EDGE_HORIZONTAL,
    EDGE_VERTICAL), else pinned to that rectangle's border, in the direction of
    the point.

    :param x: The point's projected screen x (see project_to_screen)
    :param z: The point's projected screen z
    :param behind: Whether the point is behind the camera
    :return: The indicator's screen coordinates (x, z)
    """
    if behind:
        # The perspective divide in lens.project() is by a negative depth,
        # which mirrors the projection through the screen centre: both x and z
        # come out with the wrong sign. Negate them to recover the true
        # on-screen direction, so the indicator sits on the correct edge and
        # only ever switches sides once, when the point passes directly behind.
        x = -x
        z = -z
    elif abs(x) <= EDGE_HORIZONTAL and abs(z) <= EDGE_VERTICAL:
        return x, z

    # Off screen (out of the FoV or behind): intersect the (x, z) ray with the
    # edge rectangle by scaling the whole vector by a single factor, so the
    # position varies smoothly as the direction rotates.
    #
    # Clamping each axis independently instead would drive both components to
    # their maxima whenever the projection is large on both axes (which happens
    # as the depth approaches zero, near the camera's XZ plane), snapping the
    # card to a corner that flips around as the point wobbles -> jitter.
    # Ray-to-rectangle scaling avoids that and is continuous with the in-view
    # projection (the scale is exactly 1 at the border).
    ax = abs(x)
    az = abs(z)
    scale_x = EDGE_HORIZONTAL / ax if ax > EPSILON_TOLERANCE else np.inf
    scale_z = EDGE_VERTICAL / az if az > EPSILON_TOLERANCE else np.inf
    scale = min(scale_x, scale_z)
    if not np.isfinite(scale):
        # Direction undefined (point dead centre while behind): park the
        # indicator on one side rather than at the origin.
        return EDGE_HORIZONTAL, 0.0
    return x * scale, z * scale


def draw_on_top(node_path: NodePath, sort: int = 10):
    """
    Draw a node over the scene and the other UI, regardless of depth.

    :param node_path: The node to draw
    :param sort: Its order in the "fixed" bin (higher draws on top)
    """
    node_path.setDepthTest(False)
    node_path.setDepthWrite(False)
    node_path.setBin("fixed", sort)


def make_hud_card(
    name: str,
    half_width: float,
    half_height: float,
    texture: Texture | None = None,
    left_aligned: bool = False,
) -> NodePath:
    """
    :param name: The card's name
    :param half_width: Its half width
    :param half_height: Its half height
    :param texture: Its texture, if any
    :param left_aligned: Whether its origin is on its left edge (e.g. a bar
        scaled from there), rather than its centre
    :return: A card drawn over the scene and the other UI
    """
    cm = CardMaker(name)
    if left_aligned:
        cm.setFrame(0, 2 * half_width, -half_height, half_height)
    else:
        cm.setFrame(-half_width, half_width, -half_height, half_height)
    card = NodePath(cm.generate())
    if texture is not None:
        card.setTexture(texture)
    card.setTransparency(TransparencyAttrib.MAlpha)
    draw_on_top(card)
    return card


CHATTER = "chatter"
HINT = "hint"
EVENT = "event"


class ScenarioMessage(NamedTuple):
    kind: str  # CHATTER, HINT or EVENT
    text: str
    display_time_s: float


class ScenarioText:
    """
    Who has the screen among the scenario texts: radio chatter on one side,
    tutorial hints and event banners on the other (they share a spot), never
    both at once.

    A message replaces one of its own side straight away (a new line of
    chatter cuts the previous one short), but waits for one of the other
    side to time out. Waiting messages are shown in order, each for its full
    time, and a new message queues behind them, unless it repeats the last
    one waiting (a rule posting every frame queues it once).

    :param clock: The game clock, in seconds
    """

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        #: The message on screen, if any, and when it comes down
        self.current: Optional[ScenarioMessage] = None
        self.current_end_s = 0.0
        self.pending: deque[ScenarioMessage] = deque()

    @staticmethod
    def same_side(kind: str, other: str) -> bool:
        return (kind == CHATTER) == (other == CHATTER)

    def post(self, kind: str, text: str, display_time_s: float):
        """
        :param kind: CHATTER, HINT or EVENT
        :param text: The message
        :param display_time_s: How long it stays up once shown
        """
        message = ScenarioMessage(kind, text, display_time_s)
        self.update()
        if not self.pending and (
            self.current is None or self.same_side(self.current.kind, kind)
        ):
            self._show(message)
        elif not self.pending or self.pending[-1] != message:
            self.pending.append(message)

    def update(self):
        """Take down the message whose time is up, and show the next one."""
        if self.current is not None and self.clock() >= self.current_end_s:
            self.current = None
        if self.current is None and self.pending:
            self._show(self.pending.popleft())

    def text(self, kind: str) -> str:
        """What a kind's line shows now (empty if it isn't on screen)."""
        if self.current is None or self.current.kind != kind:
            return ""
        return self.current.text

    def _show(self, message: ScenarioMessage):
        self.current = message
        self.current_end_s = self.clock() + message.display_time_s


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
            self.debug_textNodePath = make_text_line(
                self.game.app.a2dTopLeft, "Debug", align=TextNode.ALeft
            )
            self.debug = self.debug_textNodePath.node()
            self.debug_textNodePath.setScale(0.07)
            self.debug_textNodePath.setPos(0.05, 0, -0.1)

        # Performance info
        if self.fps_counter_enabled:
            self.fps_textNodePath = make_text_line(
                self.game.app.a2dTopRight, "FPS", align=TextNode.ALeft
            )
            self.fps_counter = self.fps_textNodePath.node()
            self.fps_textNodePath.setScale(0.07)
            self.fps_textNodePath.setPos(-0.4, 0, -0.1)

        # Scenario texts: chatter, hints and events, taking turns
        self.scenario_text = ScenarioText(clock=self.game.game_time.get_current_time)

        # Event text
        self.events_textNodePath = make_text_line(
            aspect2d, "Events", align=TextNode.ACenter
        )
        self.events = self.events_textNodePath.node()
        self.events_textNodePath.setScale(EVENT_TEXT_SCALE)
        self.events_textNodePath.setPos(0.0, 0.0, EVENT_Z)

        # Tutorial hint text
        self.hints_textNodePath = make_text_line(
            aspect2d, "Hints", align=TextNode.ACenter
        )
        self.hints = self.hints_textNodePath.node()
        self.hints.setWordwrap(HINT_WRAP_WIDTH / HINT_TEXT_SCALE)
        self.hints_textNodePath.setScale(HINT_TEXT_SCALE)
        self.hints_textNodePath.setPos(0.0, 0.0, EVENT_Z)

        # Chatter text
        self.chatter_textNodePath = make_text_line(
            aspect2d, "Chatter", align=TextNode.ACenter
        )
        self.chatter = self.chatter_textNodePath.node()
        self.chatter.setTextColor(252 / 255, 212 / 255, 10 / 255, 1)
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

        # The mission's objectives checklist
        self.objectives_hud = ObjectivesHUD(
            game=self.game, parent_node=self.game.app.a2dTopLeft
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
        self.objectives_hud.update()
        self.update_scenario_text()

    def set_event_text(self, text: str, display_time_s: float = EVENT_DISPLAY_S):
        """
        Shows an event banner, once no chatter is on screen (see ScenarioText)
        """
        self.scenario_text.post(EVENT, text, display_time_s)
        self.update_scenario_text()

    def set_hint_text(self, text: str, display_time_s: float = HINT_DISPLAY_S):
        """
        Shows a tutorial hint, once no chatter is on screen (see ScenarioText)
        """
        self.scenario_text.post(HINT, text, display_time_s)
        self.update_scenario_text()

    def set_chatter_text(self, text: str, display_time_s: float = CHATTER_DISPLAY_S):
        """
        Shows a line of chatter, once no hint or event is on screen (see
        ScenarioText)
        """
        self.scenario_text.post(CHATTER, text, display_time_s)
        self.update_scenario_text()

    def update_scenario_text(self) -> None:
        """
        Show whichever scenario text has the screen, and clear the others
        """
        self.scenario_text.update()
        for kind, node in (
            (EVENT, self.events),
            (HINT, self.hints),
            (CHATTER, self.chatter),
        ):
            text = self.scenario_text.text(kind)
            if node.getText() != text:
                node.setText(text)

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
                    "Lead Bot throttle = "
                    f"{self.game.lead_bot.pilot.throttle:.4f}\n"
                    "Lead Bot Speed = "
                    f"{magnitude(self.game.lead_bot.pawn.state[7:10]):.1f}m/s\n"
                    "\n"
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
            self.game.method_lists.pop(self.id, None)
        if DEBUG_HUD:
            self.debug_textNodePath.removeNode()
            self.debug = None
        if self.fps_counter_enabled:
            self.fps_textNodePath.removeNode()
            self.fps_counter = None
        self.events_textNodePath.removeNode()
        self.events = None
        self.hints_textNodePath.removeNode()
        self.hints = None
        self.chatter_textNodePath.removeNode()
        self.chatter = None
        self.ordnance_hud.clean()
        self.ordnance_hud = None
        self.energy_hud.clean()
        self.energy_hud = None
        self.objectives_hud.clean()
        self.objectives_hud = None
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


def make_checkbox_mark(parent_node: NodePath, name: str, points: list) -> NodePath:
    """
    A checkbox stroke: line strips in the box's coordinates (its half size 1).

    :param parent_node: The checkbox's node
    :param name: The stroke's node name
    :param points: The strips, each a list of (x, z) points
    :return: The stroke's node path
    """
    segs = LineSegs(name)
    segs.setThickness(2.0)
    for strip in points:
        segs.moveTo(strip[0][0], 0, strip[0][1])
        for x, z in strip[1:]:
            segs.drawTo(x, 0, z)
    return parent_node.attachNewNode(segs.create())


class ObjectiveLine:
    """
    One line of the objectives checklist: a checkbox (empty, ticked or
    crossed) and the objective's text on its right.

    :param parent_node: The checklist's node
    :param number: The line's number, top to bottom
    """

    def __init__(self, parent_node: NodePath, number: int) -> None:
        self.root = parent_node.attachNewNode(f"objective{number}")
        self.root.setZ(-number * OBJECTIVES_LINE_SPACING)
        self.root.setTransparency(TransparencyAttrib.MAlpha)

        self.box = self.root.attachNewNode("checkbox")
        self.box.setScale(OBJECTIVE_BOX_HALF_SIZE)
        self.box.setPos(
            OBJECTIVE_BOX_HALF_SIZE, 0, TEXT_CENTER_OFFSET * OBJECTIVES_TEXT_SCALE
        )
        make_checkbox_mark(
            self.box, "frame", [[(-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1)]]
        )
        self.tick = make_checkbox_mark(
            self.box, "tick", [[(-0.6, 0.0), (-0.15, -0.55), (0.65, 0.6)]]
        )
        self.cross = make_checkbox_mark(
            self.box, "cross", [[(-0.6, -0.6), (0.6, 0.6)], [(-0.6, 0.6), (0.6, -0.6)]]
        )

        self.text = make_text_line(self.root, "text", align=TextNode.ALeft)
        self.text.setPos(OBJECTIVE_TEXT_X, 0, 0)
        self.text.setScale(OBJECTIVES_TEXT_SCALE)

        self.state = None

    def show(self, label: str, state: str, alpha: float) -> None:
        """
        :param label: The objective's text
        :param state: ACTIVE, COMPLETE or FAILED
        :param alpha: The line's opacity (it blinks after a change)
        """
        if self.text.node().getText() != label:
            self.text.node().setText(label)
        if state != self.state:
            self.state = state
            self.root.setColorScale(*OBJECTIVE_COLORS[state])
            for mark, shown in ((self.tick, COMPLETE), (self.cross, FAILED)):
                if state == shown:
                    mark.show()
                else:
                    mark.hide()
        self.root.setAlphaScale(alpha)
        self.root.show()


class ObjectivesHUD:
    """
    The mission's objectives, top left: a checklist read from
    ``game.mission.objectives``, a line per objective, ticked when complete,
    crossed when failed. A line blinks for a moment when it is added or
    settled. Hidden while the mission has no objectives.
    """

    def __init__(self, game: FlightState, parent_node: NodePath) -> None:
        """
        :param game: The flight state
        :param parent_node: The node the checklist is anchored to (top-left
            corner of the screen)
        """
        self.game = game
        self.root = parent_node.attachNewNode("objectivesHud")
        self.root.setPos(OBJECTIVES_LEFT_X, 0, OBJECTIVES_TOP_Z)
        self.lines: list[ObjectiveLine] = []
        self.root.hide()

    def update(self) -> None:
        """
        Refresh the lines from the mission's objectives.
        """
        objectives = self.game.mission.objectives
        if not objectives:
            self.root.hide()
            return
        self.root.show()

        now = self.game.game_time.get_current_time()
        for number, objective in enumerate(objectives):
            while len(self.lines) <= number:
                self.lines.append(ObjectiveLine(self.root, len(self.lines)))
            self.lines[number].show(
                objective.label(),
                objective.state,
                self.flash_alpha(now - objective.changed_at_s),
            )
        for line in self.lines[len(objectives) :]:
            line.root.hide()

    @staticmethod
    def flash_alpha(since_change_s: float) -> float:
        """
        :param since_change_s: Time since the objective last changed
        :return: Its line's opacity: blinking for a while, then steady
        """
        if since_change_s >= OBJECTIVE_FLASH_S:
            return 1.0
        if int(since_change_s / OBJECTIVE_FLASH_PERIOD_S) % 2:
            return OBJECTIVE_FLASH_DIM_ALPHA
        return 1.0

    def clean(self) -> None:
        """
        Cleans the ObjectivesHUD object
        """
        self.root.removeNode()
        self.root = None
        self.lines = []
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
    - shields: a blue half-ring, the shield strength written at its centre
      (only for shielded ships; the next gauges move left to take its place)
    - engines: a green half-ring, the ship's speed written at its centre (or
      ENGINES_OFFLINE_TEXT while the engines are dead)
    - lasers: a red half-ring, the laser charge written at its centre

    The gauges are outlined in black; the energy gauge of the system power is
    redirected to is bigger, brighter, and outlined in white.
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

        has_shields = self.game.player.pawn.energy.has_shields
        self.hp_gauge = self._make_arc_gauge("hpGauge", HP_GAUGE_COLOR, 0)
        self.hp_gauge.set_brightness(GAUGE_BRIGHTNESS)
        self.shield_gauge = self._make_arc_gauge("shieldGauge", SHIELD_GAUGE_COLOR, 1)
        if not has_shields:
            self.shield_gauge.root.hide()
        slot = 2 if has_shields else 1
        self.engine_gauge = self._make_arc_gauge(
            "engineGauge", ENGINE_GAUGE_COLOR, slot
        )
        self.laser_gauge = self._make_arc_gauge(
            "laserGauge", LASER_GAUGE_COLOR, slot + 1
        )

    def _make_arc_gauge(
        self, name: str, color: tuple[float, float, float], slot: int
    ) -> ArcGauge:
        """
        :param name: The gauge's node name
        :param color: The gauge's colour
        :param slot: The gauge's place in the row, from the left
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
            outline_width=ARC_GAUGE_OUTLINE_WIDTH,
        )
        gauge.root.setX(
            ARC_GAUGE_RADIUS + slot * (2.0 * ARC_GAUGE_RADIUS + GAUGE_SPACING)
        )
        return gauge

    def update(self) -> None:
        """
        Refresh the gauges' levels, texts, brightness, highlights and sizes.
        """
        if self.root.isHidden():
            self.root.show()
        pawn = self.game.player.pawn
        energy = pawn.energy

        health = max(pawn.health, 0.0)
        self.hp_gauge.set_level(health / pawn.max_health)
        self.hp_gauge.set_text(f"{health:.0f}")

        self.laser_gauge.set_level(energy.lasers)
        self.laser_gauge.set_text(f"{100.0 * max(energy.lasers, 0.0):.0f}%")
        self._show_power(self.laser_gauge, energy, LASERS)

        self.engine_gauge.set_level(energy.engines)
        if energy.is_engine_dead:
            self.engine_gauge.set_text(ENGINES_OFFLINE_TEXT)
        else:
            self.engine_gauge.set_text(f"{magnitude(pawn.speed):.0f} m/s")
        self._show_power(self.engine_gauge, energy, ENGINES)

        if energy.has_shields:
            self.shield_gauge.set_level(pawn.shield / pawn.max_shield)
            self.shield_gauge.set_text(f"{pawn.shield:.0f}")
            self._show_power(self.shield_gauge, energy, SHIELDS)

    @staticmethod
    def _show_power(gauge: ArcGauge, energy: EnergySystem, system: str) -> None:
        """
        Brighten, highlight and grow a gauge if power is redirected to its
        system.

        :param gauge: The system's gauge
        :param energy: The ship's energy system
        :param system: The system (ENGINES, LASERS or SHIELDS)
        """
        favoured = energy.is_favoured(system)
        gauge.set_brightness(gauge_brightness(energy, system))
        gauge.set_highlighted(favoured)
        gauge.root.setScale(FAVOURED_GAUGE_SCALE if favoured else 1.0)

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


def missile_warning_text(count: int, distance_m: float) -> str:
    """
    :param count: How many missiles home on the player
    :param distance_m: The nearest one's distance
    :return: The missile warning line
    """
    if count == 1:
        return f"MISSILE {distance_m:.0f} m"
    return f"{count} MISSILES {distance_m:.0f} m"


def missile_warning_blink_period_s(time_to_impact_s: float) -> float:
    """
    :param time_to_impact_s: The nearest missile's time to impact (infinite if
        not closing in)
    :return: The warning line's blink period: shorter as the missile closes in
    """
    return float(
        np.clip(
            time_to_impact_s / MISSILE_WARNING_BLINKS_PER_IMPACT,
            MISSILE_WARNING_MIN_BLINK_PERIOD_S,
            MISSILE_WARNING_MAX_BLINK_PERIOD_S,
        )
    )


class AimHUD:
    """
    The player's aiming cues:

    - a target box with the target's name, distance and scan progress, pinned
      to the screen border when off screen. Red while missile locked.
    - a crosshair where the lasers go (where the nose points). Red while
      auto-aim is locked.
    - a lead indicator where to aim to hit the target (see
      AutoAim.predict_target_position), shown only when on screen, and only if
      the gameplay settings enable it.
    - while guided missiles home on the player (see
      :class:`~space_flight.ai.missile.incoming_missile.IncomingMissile`), a
      red warning line below the screen centre, with the nearest missile's distance
      (and their count if several), blinking faster as it closes in, and a
      violet ring on the nearest missile, pinned to the screen border when off
      screen.
    """

    def __init__(self, game: FlightState) -> None:
        self.game = game
        self.id = uuid.uuid4()
        # Read once per level, like every gameplay setting
        self.show_lead_indicator = gameplay_config(game)["player"]["lead_indicator"]

        # Cues are placed in screen coordinates, scaled for the aspect ratio
        self.root = NodePath("aimHudRoot")
        self.root.reparentTo(render2d)
        loader = self.game.app.loader

        # The target box, its scan bar and labels move together on an anchor
        self.target_anchor = self.root.attachNewNode("targetAnchor")
        self.target_aspect = self.target_anchor.attachNewNode("targetAspectFix")

        self.square = make_hud_card(
            "targetBox",
            TARGET_BOX_HALF_WIDTH,
            TARGET_BOX_HALF_HEIGHT,
            loader.loadTexture(DATAFILES_PATH / "models/UI/target_indicator_white.png"),
        )
        self.square.reparentTo(self.target_aspect)

        # Define scan progress bar: fills the target box from its left edge,
        # scaled horizontally by the target's scan progress (see
        # space_flight.actors.scan)
        # (drawn under the box)
        self.scan_bar = make_hud_card(
            "scanBar", TARGET_BOX_HALF_WIDTH, TARGET_BOX_HALF_HEIGHT, left_aligned=True
        )
        draw_on_top(self.scan_bar, sort=9)
        self.scan_bar.reparentTo(self.target_aspect)
        self.scan_bar.setPos(-TARGET_BOX_HALF_WIDTH, 0, 0)

        # Define distance label
        self.distance_label = DirectLabel(
            text="",
            scale=0.04,
            pos=(0, 0, -0.06),
            parent=self.target_aspect,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        # Define name label
        self.name_label = DirectLabel(
            text="",
            scale=0.02,
            pos=(0, 0, 0.04),
            parent=self.target_aspect,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )

        # Draw the labels above other UI things, as the cards are
        draw_on_top(self.distance_label)
        draw_on_top(self.name_label)

        # Crosshair and lead indicator
        self.crosshair = make_hud_card(
            "crosshair",
            CROSSHAIR_HALF_SIZE,
            CROSSHAIR_HALF_SIZE,
            loader.loadTexture(DATAFILES_PATH / "models/UI/crosshair.png"),
        )
        self.crosshair.reparentTo(self.root)
        lead_texture = loader.loadTexture(
            DATAFILES_PATH / "models/UI/lead_indicator.png"
        )
        self.lead_indicator = make_hud_card(
            "leadIndicator",
            LEAD_INDICATOR_HALF_SIZE,
            LEAD_INDICATOR_HALF_SIZE,
            lead_texture,
        )
        self.lead_indicator.reparentTo(self.root)

        # Incoming missile warning: a line below the screen centre and a marker on
        # the nearest missile. The line blinks; blink_phase is its cycle's
        # progress, in [0, 1), the line showing during the first half.
        self.missile_warning_line = make_text_line(
            aspect2d, "missileWarning", TextNode.ACenter
        )
        self.missile_warning_line.setPos(0, 0, MISSILE_WARNING_Z)
        self.missile_warning_line.setScale(MISSILE_WARNING_TEXT_SCALE)
        self.missile_warning_line.node().setTextColor(*MISSILE_WARNING_COLOR)
        self.missile_blink_phase = 0.0
        self.missile_marker = make_hud_card(
            "missileMarker",
            MISSILE_MARKER_HALF_SIZE,
            MISSILE_MARKER_HALF_SIZE,
            lead_texture,
        )
        self.missile_marker.setColorScale(*MISSILE_MARKER_COLOR)
        self.missile_marker.reparentTo(self.root)

        # Hide at startup
        self.target_anchor.hide()
        self.scan_bar.hide()
        self.crosshair.hide()
        self.lead_indicator.hide()
        self.missile_warning_line.hide()
        self.missile_marker.hide()

        self.game.method_lists[self.id] = [self.aim_hud_update_task]

    def aim_hud_update_task(self) -> None:
        """
        Update the cues; the target box first, as it drops a dead target.
        """
        aspect = self.game.app.getAspectRatio()
        self.target_aspect.setScale(1, 1, aspect)
        self.crosshair.setScale(1, 1, aspect)
        self.lead_indicator.setScale(1, 1, aspect)
        self.missile_marker.setScale(1, 1, aspect)
        self.update_target_box()
        self.update_crosshair()
        self.update_lead_indicator()
        self.update_missile_warning()

    def update_target_box(self) -> None:
        """
        Place, label and tint the target box; drop a dead target.
        """
        pawn = self.game.player.pawn
        target = pawn.target
        if target is None or target.is_dead:
            # Either there is no target selected, it has been purged recently,
            # or it died recently but has not yet been purged
            self.target_anchor.hide()
            pawn.target = None
            pawn.target_id = None
            pawn.target_idx = None
            return

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
            # A subsystem knocked out by ion hits says so
            if getattr(target, "is_disabled", False):
                display_name = f"{display_name} - {DISABLED_TEXT}"
            self.name_label["text"] = display_name
            self.scan_bar.hide()
        self.target_anchor.show()
        self.update_lock_tint()

        # Project the target, pinned to the border if off screen
        self._pin_on_screen(self.target_anchor, self._cam_space(target.position))

        # Find distance and write it below the box
        distance = (
            Point3(*target.position) - self.game.app.camera.getPos(self.game.root_node)
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

    def update_crosshair(self) -> None:
        """
        Place the crosshair where the nose points (the cannons fire parallel to
        it: a point at infinity), tinted by the auto-aim lock.
        """
        pawn = self.game.player.pawn
        nose = self.game.app.cam.getRelativeVector(
            self.game.root_node, Vec3(*pawn.forward)
        )
        self._place_on_screen(self.crosshair, Point3(nose))
        locked = pawn.auto_aim.is_target_acquired
        self.crosshair.setColorScale(
            *(CROSSHAIR_LOCKED_COLOR if locked else CROSSHAIR_COLOR)
        )

    def update_lead_indicator(self) -> None:
        """
        Place the lead indicator on the target's predicted position, if any and
        if enabled.
        """
        if not self.show_lead_indicator:
            # Hidden since startup
            return
        pawn = self.game.player.pawn
        lead_position = None
        if pawn.target is not None:
            lead_position = pawn.auto_aim.predict_target_position()
        if lead_position is None:
            self.lead_indicator.hide()
            return
        self._place_on_screen(self.lead_indicator, self._cam_space(lead_position))

    def update_missile_warning(self) -> None:
        """
        Show the warning line and the marker on the nearest missile while
        missiles home on the player, hide them otherwise.
        """
        pawn = self.game.player.pawn
        incoming = nearest_incoming(pawn)
        if incoming is None:
            self.missile_warning_line.hide()
            self.missile_marker.hide()
            self.missile_blink_phase = 0.0
            return

        self.missile_warning_line.node().setText(
            missile_warning_text(len(pawn.incoming_missiles), incoming.distance_m)
        )
        self.missile_blink_phase = (
            self.missile_blink_phase
            + self.game.game_time.get_time_step()
            / missile_warning_blink_period_s(incoming.time_to_impact_s)
        ) % 1.0
        if self.missile_blink_phase < 0.5:
            self.missile_warning_line.show()
        else:
            self.missile_warning_line.hide()

        self._pin_on_screen(self.missile_marker, self._cam_space(incoming.position))
        self.missile_marker.show()

    def _cam_space(self, world_position: np.ndarray) -> Point3:
        """:return: A world position, in camera space"""
        return self.game.app.cam.getRelativePoint(
            self.game.root_node, Point3(*world_position)
        )

    def _pin_on_screen(self, node: NodePath, cam_space_pos: Point3) -> None:
        """
        Place a node on a camera-space point, pinned to the screen border if
        that is off screen.
        """
        x, z = pin_to_screen_edge(
            *project_to_screen(self.game.app.camLens, cam_space_pos)
        )
        node.setPos(x, 0, z)

    def _place_on_screen(self, card: NodePath, cam_space_pos: Point3) -> None:
        """
        Place a card on a camera-space point, or hide it if that is off screen.
        """
        x, z, behind = project_to_screen(self.game.app.camLens, cam_space_pos)
        if not is_on_screen(x, z, behind):
            card.hide()
            return
        card.setPos(x, 0, z)
        card.show()

    def clean(self) -> None:
        """
        Clean the AimHUD object
        """
        if self.game.method_lists:
            self.game.method_lists.pop(self.id, None)
        self.name_label.destroy()
        self.distance_label.destroy()
        # The warning line is on aspect2d; the cards go with the root
        self.missile_warning_line.removeNode()
        self.missile_warning_line = None
        self.root.removeNode()
        self.game = None  # type: ignore[assignment]  # released on clean
