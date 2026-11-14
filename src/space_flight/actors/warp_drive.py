"""
Local warp: a hyperspace jump in flight, to cross inter-planetary distances.

The player holds the warp key:

    IDLE
      -> CHARGING  (key held: the "into" animation over the scene; the ship flies
                    on at cruise throttle, barely steerable, and can still be shot)
      -> INSIDE    (key still held once charged: the see-through tunnel; the ship
                    warps, its speed growing with its altitude above the nearest
                    body; untargetable, only terrain stops it)
      -> EXITING   (key released, too close to a body, or flying out of range: the
                    "outof" animation; the ship slows down to cruise speed)
      -> IDLE

Releasing the key while charging aborts the jump.

Physics never stops: the ship stays in the integrator and really moves. While
INSIDE and EXITING, its flight model is the warp one (see
Ship.compute_derivatives): its velocity relaxes to the warp speed along its nose
with a time constant WARP_RELAX_TIME_S. As the warp speed is
WARP_SPEED_PER_ALTITUDE (k) times the altitude h, the approach to a body is
h'' = -(h' + k h) / tau: overdamped, so never into the ground, as long as
k * tau < 0.25. Dropping out still carries the ship on for a while as it slows
down: in tests/test_warp.py, auto-dropping out at 5 km stops it about 3.3 km up
at 60 fps, 2.2 km at 10 fps (the relaxation is stretched at low frame rates).

The drive only reads the state of the warp key: the player feeds it (and
applies its throttle and turn rate limits, see turn_rate_factor) every frame,
before the ship moves.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from space_flight import (
    WARP_AUTO_EXIT_ALTITUDE_M,
    WARP_CRUISE_THROTTLE,
    WARP_MIN_ALTITUDE_M,
    WARP_TURN_RATE_FACTOR,
)
from space_flight.actors.hyperspace import mute_colliders, restore_colliders
from space_flight.fx.hyperspace_overlay import INTO_DURATION, OUTOF_DURATION
from space_flight.game.collisions import CollisionLayers
from space_flight.scenes.scenes import warp_speed_at_altitude

if TYPE_CHECKING:
    from space_flight.actors.ship import Ship
    from space_flight.fx.hyperspace_overlay import HyperspaceOverlay

# How long each timed phase lasts: as long as its animation
CHARGE_DURATION_S = INTO_DURATION
EXIT_DURATION_S = OUTOF_DURATION


class WarpState(Enum):
    IDLE = "idle"
    CHARGING = "charging"
    INSIDE = "inside"
    EXITING = "exiting"


class WarpDrive:
    """A ship's warp drive, driven by the state of the warp key."""

    def __init__(self, ship: Ship, overlay: HyperspaceOverlay | None = None):
        """
        :param ship: The ship that warps
        :param overlay: The hyperspace effect to play (with the warp look), None
            to play none (headless games)
        """
        self.ship = ship
        self.overlay = overlay
        # Whether the level (or its mission) lets the player warp
        self.allowed = False
        self.state = WarpState.IDLE
        # Time spent in the current state, seconds (game time)
        self.state_time_s = 0.0
        # Set when the drive stops a jump on its own: the key must be released
        # before it can start another one
        self._needs_release = False
        self._key_was_held = False
        # Game time of the last press refused for want of altitude, None if
        # none (the HUD blinks the engine gauge, see EnergyHUD)
        self.refused_at_s: float | None = None
        self._muted_colliders = []

    @property
    def active(self) -> bool:
        """Whether a jump is under way (charging, warping or dropping out)."""
        return self.state is not WarpState.IDLE

    @property
    def turn_rate_factor(self) -> float:
        """The cap on the ship's turn rate commands, 1 when not jumping."""
        return WARP_TURN_RATE_FACTOR if self.active else 1.0

    @property
    def throttle(self) -> float | None:
        """The throttle imposed on the ship while jumping, None when not."""
        return WARP_CRUISE_THROTTLE if self.active else None

    def update(self, key_held: bool, dt: float):
        """
        Advance the drive by a frame. Call it before the ship moves.

        :param key_held: Whether the warp key is held
        :param dt: Time step, seconds (game time: 0 while paused)
        """
        if not key_held:
            self._needs_release = False
        self.state_time_s += dt

        if self.active and self._ship_lost():
            self.stop()
        elif self.state is WarpState.IDLE:
            if key_held and self._ready() and self._high_enough():
                self._enter(WarpState.CHARGING)
            elif key_held and not self._key_was_held and self._ready():
                # Pressed too close to a body: tell the player why nothing
                # happens
                self.refused_at_s = self.ship.game.game_time.get_current_time()
        elif self.state is WarpState.CHARGING:
            if not key_held or not self.allowed or not self.ship.engines_online():
                self._abort()
            elif self.state_time_s >= CHARGE_DURATION_S:
                self._enter(WarpState.INSIDE)
        elif self.state is WarpState.INSIDE:
            altitude_m = self.ship.game.scene.altitude_m(self.ship.position)
            if altitude_m < WARP_AUTO_EXIT_ALTITUDE_M or not self.allowed:
                # Dropped out by the drive, not the player: make them release
                # the key before jumping again
                self._needs_release = True
                self._enter(WarpState.EXITING)
            elif not key_held:
                self._enter(WarpState.EXITING)
            else:
                self._set_warp_speed(altitude_m)
        elif self.state is WarpState.EXITING:
            if self.state_time_s >= EXIT_DURATION_S:
                self._finish()

        self._key_was_held = key_held
        if self.overlay is not None:
            self.overlay.update(dt)

    def stop(self):
        """Stop any jump at once, whatever its state (e.g. the ship died)."""
        if self.state in (WarpState.INSIDE, WarpState.EXITING):
            self._leave_hyperspace()
        if self.active:
            self._play("hide")
        self.state = WarpState.IDLE
        self.state_time_s = 0.0

    def clean(self):
        """Stop any jump at once and remove the effect."""
        self.stop()
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None

    # -- internals -----------------------------------------------------------

    def _ready(self) -> bool:
        """Whether the drive can jump, wherever the ship is: allowed, the key
        pressed afresh after a drop out by the drive, engines running."""
        return self.allowed and not self._needs_release and self.ship.engines_online()

    def _high_enough(self) -> bool:
        """Whether the ship is far enough from any body to jump ("in space")."""
        altitude_m = self.ship.game.scene.altitude_m(self.ship.position)
        return altitude_m > WARP_MIN_ALTITUDE_M

    def _ship_lost(self) -> bool:
        return self.ship.is_dead or self.ship.is_dying

    def _enter(self, state: WarpState):
        """Switch to a state, with its effect on the ship and the animation."""
        self.state = state
        self.state_time_s = 0.0
        if state is WarpState.CHARGING:
            self._play("show", "into")
        elif state is WarpState.INSIDE:
            self._go_into_hyperspace()
            self._set_warp_speed()
            self._play("cross_fade_to", "inside")
        elif state is WarpState.EXITING:
            # Slow down to cruise speed, still in the warp flight model
            self.ship.warp_target_speed_mps = self.ship.cruise_speed_mps(
                WARP_CRUISE_THROTTLE
            )
            self._play("cross_fade_to", "outof")

    def _abort(self):
        """Stop charging: the jump never happened."""
        self.state = WarpState.IDLE
        self.state_time_s = 0.0
        self._play("fade_out")

    def _finish(self):
        """End of the drop out: back to normal flight, at cruise speed."""
        self._leave_hyperspace()
        self.state = WarpState.IDLE
        self.state_time_s = 0.0
        # Outof has dissolved into the scene by now
        self._play("hide")

    def _go_into_hyperspace(self):
        """
        Out of every interaction (untargetable, see Interactions), and out of
        every collision but with terrain.
        """
        ship = self.ship
        ship.in_hyperspace = True
        self._muted_colliders = mute_colliders(ship.node)
        hull = getattr(ship, "collision_sphere_np", None)
        if hull is not None and not hull.isEmpty():
            hull.node().setFromCollideMask(CollisionLayers.WARPING_HULL_FROM)
            hull.node().setIntoCollideMask(CollisionLayers.WARPING_HULL_INTO)

    def _set_warp_speed(self, altitude_m: float | None = None):
        """
        Pull the ship to the warp speed of its altitude.

        :param altitude_m: The ship's altitude, if already known
        """
        if altitude_m is None:
            altitude_m = self.ship.game.scene.altitude_m(self.ship.position)
        self.ship.warp_target_speed_mps = warp_speed_at_altitude(altitude_m)

    def _leave_hyperspace(self):
        """Back to normal flight, interactions and collisions."""
        restore_colliders(self._muted_colliders)
        self._muted_colliders = []
        self.ship.in_hyperspace = False
        self.ship.warp_target_speed_mps = None
        # "Up" is only reckoned once a second: the ship may be far from where
        # it was last reckoned
        self.ship.game.scene.forget_up()

    def _play(self, method: str, *args: str):
        """Call an overlay method, if there is an overlay."""
        if self.overlay is not None:
            getattr(self.overlay, method)(*args)
