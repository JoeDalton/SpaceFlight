from __future__ import annotations

import math
import random
import uuid
from typing import TYPE_CHECKING

import numpy as np
import yaml
from panda3d.core import CardMaker, LVecBase2f, Point3, Shader, TransparencyAttrib, Vec3

from space_flight import DATAFILES_PATH
from space_flight.fx.damage_fx import (
    DEFAULT_FIRE_HEALTH_FRAC,
    DEFAULT_SMOKE_HEALTH_FRAC,
)
from space_flight.fx.spark_fx import SparkPreset

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# ===========================================================================
# COCKPIT LOW-HEALTH FX (first-person player feedback)
# ===========================================================================
#
# The exterior DamageFX trail is emitted at the hull -- i.e. at the camera in
# first person -- so it gives the player no read on their own ship's condition.
# CockpitFX is the player-only, display-only counterpart: a red damage vignette,
# a cockpit rattle, a directional laser-coloured hit flash, and electrical sparks
# (engine sputter lives on Ship, at the engine-sound source). It is built by
# Player only when not headless and cleaned with the player.
#
# Everything keys off the SAME two health tiers the exterior FX use, so interior
# and exterior stay in sync.

# ---------------------------------------------------------------------------
# Health tiers (shared with the exterior thresholds)
# ---------------------------------------------------------------------------

#: 0 intact, 1 damaged, 2 critical.
INTACT, DAMAGED, CRITICAL = 0, 1, 2


def health_tier(fraction: float) -> int:
    """
    Map a health fraction to a damage tier, reusing the exterior FX thresholds
    (:data:`DEFAULT_SMOKE_HEALTH_FRAC` = 2/3, :data:`DEFAULT_FIRE_HEALTH_FRAC` =
    1/3) so cockpit feedback matches the ship's smoke/fire.

    :param fraction: health / max_health, in [0, 1]
    :return: INTACT, DAMAGED or CRITICAL
    """
    if fraction <= DEFAULT_FIRE_HEALTH_FRAC:
        return CRITICAL
    if fraction <= DEFAULT_SMOKE_HEALTH_FRAC:
        return DAMAGED
    return INTACT


def screen_direction_from_incoming(
    incoming_world_dir, pawn_right, pawn_up
) -> np.ndarray:
    """
    Project an incoming shot's world direction onto the pilot's screen axes and
    return the 2D on-screen direction the shot *came from* (x right, y up), unit
    length -- what the directional hit flash biases toward.

    Uses the pawn's own body basis rather than the camera node, so it is
    independent of the head-look offset and testable without a live camera.

    :param incoming_world_dir: the shot's world-space travel direction (velocity)
    :param pawn_right: the ship's world-space right axis
    :param pawn_up: the ship's world-space up axis
    :return: a length-2 unit vector, or [0, 0] for a head-on/degenerate hit
    """
    d = np.asarray(incoming_world_dir, dtype=float)
    norm = np.linalg.norm(d)
    if norm < 1e-9:
        return np.zeros(2)
    came_from = -d / norm  # toward the source
    screen = np.array(
        [
            float(np.dot(came_from, np.asarray(pawn_right, dtype=float))),
            float(np.dot(came_from, np.asarray(pawn_up, dtype=float))),
        ]
    )
    mag = np.linalg.norm(screen)
    if mag < 1e-9:
        # Shot travelled straight down the view axis: no meaningful side.
        return np.zeros(2)
    return screen / mag


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_OVERLAY_VERT = DATAFILES_PATH / "shaders/cockpit_overlay.vert"
_OVERLAY_FRAG = DATAFILES_PATH / "shaders/cockpit_overlay.frag"

#: render2d bin sort for the overlay: above the game scene, below the target
#: reticle (fixed 10) and prompts so they stay readable over the tint.
_OVERLAY_BIN_SORT = 5

#: Vignette tint and per-tier strength; a slow pulse is added when critical.
_VIGNETTE_COLOR = (0.2, 0.05, 0.05)
_VIGNETTE_STRENGTH = {DAMAGED: 0.35, CRITICAL: 0.75}
_CRIT_PULSE_AMP = 0.1
_CRIT_PULSE_RATE = 2.0  # rad/s

#: Hit-flash peak strength (the value each new hit resets the flash to) and its
#: fade time (seconds from that peak to nothing).
_FLASH_PEAK = 0.7
_FLASH_DECAY_S = 0.35

#: Electrical-spark cadence and burst size per tier. The count is how many of the
#: ship's authored cockpit emitters fire on each burst (a random subset); each
#: fires a small cone of sparks from the shared SparkPool.
_SPARK_INTERVAL_S = {DAMAGED: 1.5, CRITICAL: 0.8}
_SPARK_COUNT = {DAMAGED: 2, CRITICAL: 4}
#: Cockpit sparks reuse the hit-spark pool/shader (game.spark_fx_pool), just a
#: small preset seen up close. size_scale/speed_scale shrink it against the pool's
#: global scales (tuned for distant hits), since the cockpit is right at the camera.
_COCKPIT_SPARK_PRESET = SparkPreset(
    color_inner=(0.55, 0.7, 1.0, 1.0),
    color_outer=(0.1, 0.3, 1.0, 1.0),
    count=15,
    speed=6.0,
    spread=0.6,
    gravity=1.0,
    lifetime=0.35,
    size=0.03,
)
_COCKPIT_SIZE_MULT = 0.03
_COCKPIT_SPEED_MULT = 0.05
#: Ship-config key holding the path (under datafiles) to this cockpit's spark
#: emitter file. Absent -> the ship emits no cockpit sparks.
_SPARK_EMITTERS_CONF_KEY = "cockpit_spark_emitters"

#: Damage "stutter": synchronized, random discrete events (rather than a
#: continuous vibration) that jolt the camera and cut the engine at the same
#: instant -- see :meth:`CockpitFX.sputter_intensity`, read by both. Per tier: a
#: random gap between events, a single-jolt duration, and a peak amplitude in
#: [0, 1] (both consumers scale their own magnitude by the shared envelope).
_STUTTER_GAP_S = {DAMAGED: (0.8, 2.6), CRITICAL: (0.1, 1.2)}
_STUTTER_DURATION_S = {DAMAGED: (0.3, 0.8), CRITICAL: (0.5, 1.2)}
_STUTTER_PEAK = {DAMAGED: (0.5, 0.8), CRITICAL: (0.8, 1.0)}

#: Cockpit rattle amplitude (metres) and roll (degrees) per tier: the peak of a
#: fast vibration whose amplitude is faded in and out by the stutter envelope, so
#: the camera buzzes during each event and settles between them.
_RATTLE_AMP_M = {DAMAGED: 0.0015, CRITICAL: 0.005}
_RATTLE_ROLL_DEG = {DAMAGED: 0.3, CRITICAL: 0.7}
#: (rad/s) frequencies of the sines summed into the vibration.
_RATTLE_FREQS = (61.0, 43.0, 89.0, 71.0, 53.0, 97.0)


# ---------------------------------------------------------------------------
# Emitter loading
# ---------------------------------------------------------------------------


def load_cockpit_spark_emitters(conf: dict):
    """
    Load a cockpit's authored spark emitters from the ship config.

    The config key :data:`_SPARK_EMITTERS_CONF_KEY` gives a path (under
    ``datafiles``) to a YAML file of ``emitters: [{position, normal}, ...]``,
    both length-3 vectors in the ship body frame (X right, Y forward, Z up). Tie
    variants share one file (``models/ships/tie_common/cockpit``); other fighters
    have their own. A ship with no such key emits no cockpit sparks.

    :param conf: the ship's loaded ``configuration.yaml`` dict
    :return: list of (position, normal) numpy pairs in the ship body frame
    """
    rel_path = conf.get(_SPARK_EMITTERS_CONF_KEY)
    if not rel_path:
        return []
    with open(DATAFILES_PATH / rel_path, "r") as f:
        data = yaml.safe_load(f)
    return [
        (
            np.array(entry["position"], dtype=float),
            np.array(entry["normal"], dtype=float),
        )
        for entry in data.get("emitters", [])
    ]


# ---------------------------------------------------------------------------
# Cockpit FX hub
# ---------------------------------------------------------------------------


class CockpitFX:
    """
    Player-only, display-only hub for first-person low-health feedback: the
    damage vignette + directional hit flash (one fullscreen overlay shader),
    electrical sparks from the ship's authored cockpit emitters (emitted through
    the shared ``game.spark_fx_pool``), and the cockpit rattle offset consumed by
    :meth:`Player.move_camera`. Driven each frame off the player pawn's health
    tier; built by :class:`Player` only when not headless.

    :param game: The game/flight state
    :param player: The player whose pawn's health drives the effects
    """

    def __init__(self, game: FlightState, player) -> None:
        self.game = game
        self.player = player
        self.id = uuid.uuid4()

        self._flash_strength = 0.0
        self._next_spark_at = 0.0

        # Shared random damage-stutter state (drives both the camera jolt and the
        # engine cut, so they fire together). intensity is the current [0,1]
        # envelope of the active event; between events it is 0.
        self._stutter_intensity = 0.0
        self._stutter_elapsed = 0.0
        self._stutter_duration = 0.0
        self._stutter_peak = 0.0
        self._next_stutter_at = 0.0

        # Authored cockpit spark emitters (body-frame position + normal), from the
        # ship config; empty for ships that declare none.
        self._emitters = load_cockpit_spark_emitters(player.pawn.conf)

        self._overlay = self._make_overlay_quad()

        # Drive ourselves each frame, under our own id so clean() can drop it.
        self.game.method_lists[self.id] = [self.update]

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _make_overlay_quad(self):
        """Build the fullscreen render2d overlay quad + shader (vignette+flash)."""
        cm = CardMaker("cockpit_overlay")
        cm.setFrameFullscreenQuad()
        quad = self.game.app.render2d.attachNewNode(cm.generate())
        quad.setDepthWrite(False)
        quad.setDepthTest(False)
        quad.setTransparency(TransparencyAttrib.MAlpha)
        quad.setBin("fixed", _OVERLAY_BIN_SORT)
        quad.setShader(
            Shader.load(Shader.SL_GLSL, vertex=_OVERLAY_VERT, fragment=_OVERLAY_FRAG)
        )
        quad.setShaderInput("uVignetteColor", Vec3(*_VIGNETTE_COLOR))
        quad.setShaderInput("uVignetteStrength", 0.0)
        quad.setShaderInput("uFlashColor", Vec3(1.0, 1.0, 1.0))
        quad.setShaderInput("uFlashDir", LVecBase2f(0.0, 1.0))
        quad.setShaderInput("uFlashStrength", 0.0)
        return quad

    # ------------------------------------------------------------------
    # Per-frame
    # ------------------------------------------------------------------
    def update(self) -> None:
        """Drive the vignette, decay the flash, and emit sparks for the tier."""
        if self.game is None or self._overlay is None:
            return
        now = self.game.game_time.get_current_time()
        dt = self.game.game_time.get_time_step()
        pawn = self.player.pawn
        tier = health_tier(_health_fraction(pawn))

        # Vignette: per-tier strength, pulsing when critical.
        strength = _VIGNETTE_STRENGTH.get(tier, 0.0)
        if tier == CRITICAL:
            strength *= 1.0 + _CRIT_PULSE_AMP * math.sin(now * _CRIT_PULSE_RATE)
        self._overlay.setShaderInput("uVignetteStrength", strength)

        # Hit flash: decay toward zero.
        if self._flash_strength > 0.0:
            self._flash_strength = max(0.0, self._flash_strength - dt / _FLASH_DECAY_S)
            self._overlay.setShaderInput("uFlashStrength", self._flash_strength)

        # Shared random stutter (camera jolt + engine cut, computed once here).
        self._advance_stutter(now, dt, tier)

        # Electrical sparks: tier-gated cadence.
        if tier >= DAMAGED and now >= self._next_spark_at:
            self._next_spark_at = now + _SPARK_INTERVAL_S[tier]
            self._emit_sparks(tier)

    def _emit_sparks(self, tier: int) -> None:
        """
        Fire a random subset of the cockpit's authored emitters (skipped headless
        or when the ship declares none). Each chosen emitter's body-frame position
        and normal are transformed to world through the ship node, and a spark
        streaks out along that normal with a small random cone spread.
        """
        if self.game.headless or not self._emitters:
            return
        pawn = self.player.pawn
        mat = pawn.node.getMat(self.game.root_node)
        base_velocity = np.asarray(pawn.speed, dtype=float)
        count = min(_SPARK_COUNT[tier], len(self._emitters))
        for local_pos, local_normal in random.sample(self._emitters, count):
            world_pos = np.array(mat.xformPoint(Point3(*local_pos)), dtype=float)
            world_normal = np.array(mat.xformVec(Vec3(*local_normal)), dtype=float)
            # Reuse the shared hit-spark pool/shader, scaled down for close range.
            self.game.spark_fx_pool.spawn(
                position=world_pos,
                normal=world_normal,
                base_velocity=base_velocity,
                preset=_COCKPIT_SPARK_PRESET,
                size_scale=_COCKPIT_SIZE_MULT,
                speed_scale=_COCKPIT_SPEED_MULT,
            )

    def _advance_stutter(self, now: float, dt: float, tier: int) -> None:
        """
        Advance the shared random damage-stutter one frame: decay the current
        jolt, and fire a fresh one (a kick in a random direction + a matching
        engine cut) at random intervals while damaged. Computed once per frame so
        the camera jolt (:meth:`rattle_offset`) and the engine cut
        (:meth:`sputter_intensity`) read one synchronized value.

        :param now: current (pause-aware) game time
        :param dt: frame timestep
        :param tier: current health tier
        """
        # Decay any active jolt (ease-out to zero over its duration).
        if self._stutter_duration > 0.0:
            self._stutter_elapsed += dt
            u = self._stutter_elapsed / self._stutter_duration
            if u >= 1.0:
                self._stutter_intensity = 0.0
                self._stutter_duration = 0.0
            else:
                self._stutter_intensity = self._stutter_peak * (1.0 - u) ** 2

        # No stutter while intact; hold the next-event clock ahead so entering the
        # damaged tier does not fire one instantly.
        if tier == INTACT:
            self._stutter_intensity = 0.0
            self._stutter_duration = 0.0
            self._next_stutter_at = now + _STUTTER_GAP_S[DAMAGED][0]
            return

        # Fire the next event when due (and not already mid-jolt).
        if now >= self._next_stutter_at and self._stutter_duration <= 0.0:
            self._stutter_elapsed = 0.0
            self._stutter_duration = random.uniform(*_STUTTER_DURATION_S[tier])
            self._stutter_peak = random.uniform(*_STUTTER_PEAK[tier])
            self._stutter_intensity = self._stutter_peak
            self._next_stutter_at = now + random.uniform(*_STUTTER_GAP_S[tier])

    def sputter_intensity(self) -> float:
        """
        The current [0, 1] intensity of the shared damage stutter (0 between
        events / when intact), read by both the cockpit jolt and the engine
        sputter (:meth:`Ship._engine_sputter_factor`) so they fire together.

        :return: the stutter envelope this frame
        """
        return self._stutter_intensity

    def rattle_offset(self):
        """
        The current cockpit rattle, for :meth:`Player.move_camera` to add to the
        head position: a fast multi-frequency vibration whose amplitude is faded
        in and out by the shared stutter envelope, so the camera buzzes during
        each random event and settles to nothing between them.

        :return: (offset_m length-3 array, roll_deg float); zeros when idle
        """
        if self._stutter_intensity <= 0.0:
            return np.zeros(3), 0.0
        tier = health_tier(_health_fraction(self.player.pawn))
        t = self.game.game_time.get_current_time()
        f = _RATTLE_FREQS
        osc = np.array(
            [
                math.sin(t * f[0]) + 0.5 * math.sin(t * f[1] + 1.3),
                math.sin(t * f[2] + 2.1) + 0.5 * math.sin(t * f[3]),
                math.sin(t * f[4] + 0.7),
            ]
        )
        offset = osc * _RATTLE_AMP_M.get(tier, 0.0) * self._stutter_intensity
        roll = (
            _RATTLE_ROLL_DEG.get(tier, 0.0)
            * math.sin(t * f[5])
            * self._stutter_intensity
        )
        return offset, roll

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def flash(self, color, screen_dir) -> None:
        """
        Trigger a directional hit flash tinted *color*, biased toward *screen_dir*.

        :param color: RGB of the laser that hit (length-3 iterable)
        :param screen_dir: 2D screen direction the shot came from (x right, y up)
        """
        if self._overlay is None:
            return
        self._overlay.setShaderInput(
            "uFlashColor", Vec3(float(color[0]), float(color[1]), float(color[2]))
        )
        self._overlay.setShaderInput(
            "uFlashDir", LVecBase2f(float(screen_dir[0]), float(screen_dir[1]))
        )
        self._flash_strength = _FLASH_PEAK
        self._overlay.setShaderInput("uFlashStrength", self._flash_strength)

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------
    def clean(self) -> None:
        """Drop the per-frame task and overlay quad (sparks use the shared pool)."""
        if self.game is not None and self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        if self._overlay is not None:
            self._overlay.removeNode()
            self._overlay = None
        self.game = None
        self.player = None


def _health_fraction(pawn) -> float:
    """Pawn health as a fraction of its maximum, clamped so max<=0 reads as 0."""
    if getattr(pawn, "max_health", 0.0) > 0.0:
        return pawn.health / pawn.max_health
    return 0.0
