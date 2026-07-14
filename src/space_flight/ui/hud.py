import uuid

import numpy as np
from direct.gui.DirectGui import DirectLabel
from direct.showbase.ShowBaseGlobal import aspect2d, render2d
from panda3d.core import (
    CardMaker,
    NodePath,
    Point2,
    Point3,
    TextNode,
    TransparencyAttrib,
)

from space_flight import DATAFILES_PATH, EPSILON_TOLERANCE

EDGE_HORIZONTAL = 0.94
EDGE_VERTICAL = 0.88

# Smallest camera-space depth (forward distance) we let the projection see.
# When the target sits in the camera's XZ plane the true depth is ~0 and the
# perspective divide explodes, making the card jitter; clamping the depth to
# this non-zero magnitude keeps the projection finite and stable.
MIN_PROJECTION_DEPTH = 1e-3


class HUD:
    """
    Creates an overlay of text displaying important
    simulation parameters on screen.
    """

    def __init__(self, game):
        self.game = game
        self.id = uuid.uuid4()

        # Debug info
        self.debug = TextNode("Debug")
        self.debug.setSmallCaps(True)
        self.debug.setShadow(0.05, 0.05)
        self.debug.setShadowColor(0, 0, 0, 1)
        self.debug_textNodePath = aspect2d.attachNewNode(self.debug)
        self.debug_textNodePath.setScale(0.07)
        self.debug_textNodePath.reparentTo(self.game.app.a2dTopLeft)
        self.debug_textNodePath.setPos(0.05, 0, -0.1)

        # Performance info
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
        self.chatter.setShadow(0.05, 0.05)
        self.chatter.setShadowColor(0, 0, 0, 1)
        self.chatter_textNodePath = aspect2d.attachNewNode(self.chatter)
        self.chatter_textNodePath.setScale(0.05)
        self.chatter_textNodePath.setPos(0.0, 0, -0.8)

        self.game.method_lists[self.id] = [self.hud_update_task]

    def hud_update_task(self):
        """
        A method that gets the relevant informations from the sim
        and updates the text displayed in the HUD.
        """
        self.update_debug_hud()
        self.clear_scenario_hud()

    def set_event_text(self, text: str, display_time_s: float = 2.5):
        """
        Sets an event text and its display time
        """
        self.events.set_text(text)
        self.event_text_endtime = (
            self.game.game_time.get_current_time() + display_time_s
        )
        self.events.setAlign(TextNode.ACenter)

    def set_chatter_text(self, text: str, display_time_s: float = 2.5):
        """
        Sets a chatter text and its display time
        """
        self.chatter.set_text(text)
        self.chatter_text_endtime = (
            self.game.game_time.get_current_time() + display_time_s
        )
        self.chatter.setAlign(TextNode.ACenter)

    def clear_scenario_hud(self):
        """
        A method to clear the scenario text on screen if the display time is spent
        """
        current_time = self.game.game_time.get_current_time()
        if current_time > self.event_text_endtime:
            self.events.set_text("")
        if current_time > self.chatter_text_endtime:
            self.chatter.set_text("")

    def update_debug_hud(self):
        """
        A method to update debug info on screen
        """
        frame_rate = self.game.game_time.get_average_frame_rate()
        self.fps_counter.setText(f"FPS = {frame_rate:.0f}")

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
            f"{np.linalg.norm(self.game.player.pawn.state[7:10]):.1f}m/s\n"
            f"Player health = {self.game.player.pawn.health:.1f}\n"
            f"Player shield = {self.game.player.pawn.shield:.1f}\n"
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
                f"{np.linalg.norm(self.game.lead_bot.pawn.state[7:10]):.1f}m/s\n"
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

    def clean(self):
        """
        Cleans the HUD object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.debug_textNodePath.removeNode()
        self.debug = None
        self.fps_textNodePath.removeNode()
        self.fps_counter = None
        self.game = None
        self.events_textNodePath.removeNode()
        self.events = None
        self.chatter_textNodePath.removeNode()
        self.chatter = None
        self.game = None


class TargetHUD:
    def __init__(self, game):
        # TODO add lead indicator
        self.game = game
        self.id = uuid.uuid4()

        # Prepare target indicator atachment and aspect ratio correction
        self.root = NodePath("targetHudRoot")
        self.root.reparentTo(render2d)

        self.aspect = NodePath("aspectFix")
        self.aspect.reparentTo(self.root)

        # Define target indicator
        cm = CardMaker("targetBox")
        cm.setFrame(-0.038, 0.038, -0.03, 0.03)

        self.square = NodePath(cm.generate())
        self.square.setTexture(
            self.game.app.loader.loadTexture(
                DATAFILES_PATH / "models/UI/target_indicator_white.png"
            )
        )
        self.square.setTransparency(TransparencyAttrib.MAlpha)
        self.square.reparentTo(self.aspect)

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

        # Make sure the targeting HUD is rendered above other UI things
        self.square.setDepthTest(False)
        self.square.setDepthWrite(False)
        self.square.setBin("fixed", 10)

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

    def target_hud_update_task(self):
        target = self.game.player.pawn.target
        if target is None:
            # Either there is no target selected or it has been purged recently
            self.distance_label.hide()
            self.name_label.hide()
            self.square.hide()
            self.game.player.pawn.target_id = None
            self.game.player.pawn.target_idx = None
        elif target.is_dead:
            # The target died recently but has not yet been purged
            self.distance_label.hide()
            self.name_label.hide()
            self.square.hide()
            self.game.player.target = None
            self.game.player.pawn.target_id = None
            self.game.player.pawn.target_idx = None
        else:
            # Most targets show their parent's name (a ship shows its bot's name).
            # Subsystems have no named parent, so fall back to their own name.
            display_name = getattr(target.parent, "name", None) or getattr(
                target, "name", ""
            )
            self.name_label["text"] = display_name
            self.distance_label.show()
            self.name_label.show()
            self.square.show()

            cam = self.game.app.cam
            lens = self.game.app.camLens

            aspect = self.game.app.getAspectRatio()
            self.aspect.setScale(1, 1, aspect)

            # World position of target
            target_pos = self.game.player.pawn.target.position
            world_pos = Point3(*target_pos)

            # Convert to camera space
            cam_space_pos = cam.getRelativePoint(self.game.root_node, world_pos)

            # Guard against the degenerate projection when the target lies in
            # the camera's XZ plane (depth ~ 0): clamp the forward depth to a
            # small non-zero magnitude, preserving its sign so the behind-camera
            # handling below still triggers correctly.
            if abs(cam_space_pos.y) < MIN_PROJECTION_DEPTH:
                cam_space_pos.y = (
                    MIN_PROJECTION_DEPTH
                    if cam_space_pos.y >= 0
                    else -MIN_PROJECTION_DEPTH
                )

            screen_pos = Point2()
            lens.project(cam_space_pos, screen_pos)

            # Default case: target is ahead, just take the projection
            indic_x = screen_pos.x
            indic_z = screen_pos.y

            behind = cam_space_pos.y <= 0
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

    def clean(self):
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
        self.aspect.removeNode()
        self.root.removeNode()
        self.game = None
