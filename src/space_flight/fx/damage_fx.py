from __future__ import annotations

import random
from collections import namedtuple
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# ===========================================================================
# DAMAGE / DEATH FX
# ===========================================================================
#
# A per-actor smoke-and-fire trail driven by a single *severity* level, derived
# each frame from the owner's health ratio (maximum while dying), so a wounded
# ship's trail keeps burning -- and intensifies -- through its death spin with no
# visible restart. It emits into the shared fire/smoke pool (trail_smoke /
# trail_fire) and owns no scene nodes.

# ---------------------------------------------------------------------------
# Severity thresholds (health fraction) and lifecycle
# ---------------------------------------------------------------------------

#: Severity levels. 0 = intact, 1 = smoking, 2 = on fire, 3 = dying (max).
_INTACT, _SMOKING, _ON_FIRE, _DYING = 0, 1, 2, 3

#: Default health fractions at or below which a living actor smokes / catches
#: fire.
DEFAULT_SMOKE_HEALTH_FRAC = 2.0 / 3.0
DEFAULT_FIRE_HEALTH_FRAC = 1.0 / 3.0

#: Fraction of the actor's velocity smoke puffs inherit. Kept low so the ship
#: flies out of its smoke, laying a column rather than dragging a clump along.
_SMOKE_VELOCITY_DRAG = 0.12

# ---------------------------------------------------------------------------
# Per-severity emission
# ---------------------------------------------------------------------------
# One spec per wounded severity: seconds between puffs, billboards per puff and
# puff scale (a size/speed multiplier, NOT a metre radius) for each layer. fire_*
# are unused below _ON_FIRE; _INTACT emits nothing.
#
# Continuity comes from few big overlapping puffs (cheap on the shared pool)
# rather than a dense stream of tiny ones: at typical flight speeds the large
# sizes bridge the gaps. Particle lifetimes belong to the pool's trail layers
# (fire_smoke_fx.py).

_SeveritySpec = namedtuple(
    "_SeveritySpec",
    "smoke_interval smoke_count smoke_scale fire_interval fire_count fire_scale",
)

_SEVERITY = {
    _SMOKING: _SeveritySpec(0.11, 1, 3.5, None, 0, 0.0),
    _ON_FIRE: _SeveritySpec(0.085, 1, 5.0, 0.09, 1, 1.6),
    _DYING: _SeveritySpec(0.06, 2, 7.0, 0.06, 2, 2.4),
}


class DamageFX:
    """
    A severity-driven smoke/fire trail shared by a ship's damage and death visuals.

    The owner is duck-typed: anything exposing ``position`` (length-3 array),
    ``speed`` (length-3 array), ``health`` and ``max_health`` floats, and an
    optional ``is_dying`` flag works (ships, subsystems). Register :meth:`update`
    as a per-frame task; it derives the severity from the owner's state and emits
    accordingly.

    :param game: The game/flight state (owns the shared fire/smoke pool)
    :param owner: The actor this trail belongs to
    :param smoke_health_frac: Health fraction at/below which smoke starts
    :param fire_health_frac: Health fraction at/below which fire starts
    """

    def __init__(
        self,
        game: FlightState,
        owner: Any,
        smoke_health_frac: float = DEFAULT_SMOKE_HEALTH_FRAC,
        fire_health_frac: float = DEFAULT_FIRE_HEALTH_FRAC,
    ):
        self.game = game
        self.owner = owner
        self.smoke_health_frac = smoke_health_frac
        self.fire_health_frac = fire_health_frac

        # Next (game-clock) time each layer is allowed to emit again. The game
        # clock is pause-aware, so the cadence freezes with the game.
        self._next_smoke_at = 0.0
        self._next_fire_at = 0.0

    def _severity(self) -> int:
        """
        Derive the current severity from the owner's health (max while dying).

        :return: A severity level in 0..3
        """
        if getattr(self.owner, "is_dying", False):
            return _DYING
        max_health = getattr(self.owner, "max_health", 0.0)
        if max_health <= 0.0:
            return _INTACT
        fraction = self.owner.health / max_health
        if fraction <= self.fire_health_frac:
            return _ON_FIRE
        if fraction <= self.smoke_health_frac:
            return _SMOKING
        return _INTACT

    def update(self):
        """
        Emit this frame's smoke/fire puffs for the owner's current severity.

        A no-op while intact or after cleanup. Puffs spawn at the owner's current
        position and ride (a fraction of) its velocity, so the trail follows the
        actor as it manoeuvres or tumbles.
        """
        if self.game is None or self.owner is None:
            return
        severity = self._severity()
        if severity <= _INTACT:
            return
        spec = _SEVERITY[severity]

        now = self.game.game_time.get_current_time()
        pool = self.game.fire_smoke_pool
        position = np.asarray(self.owner.position, dtype=float)
        velocity = np.asarray(self.owner.speed, dtype=float)

        # Smoke (all wounded severities): a lagging trail behind the actor.
        if now >= self._next_smoke_at:
            self._next_smoke_at = now + spec.smoke_interval
            pool.trail_smoke(
                position=position,
                base_velocity=velocity * _SMOKE_VELOCITY_DRAG,
                scale=spec.smoke_scale,
                count=spec.smoke_count,
            )

        # Fire (on-fire and dying): rides fully with the actor, at its hull.
        if severity >= _ON_FIRE and now >= self._next_fire_at:
            self._next_fire_at = now + spec.fire_interval
            pool.trail_fire(
                position=position + _hull_jitter(severity),
                base_velocity=velocity,
                scale=spec.fire_scale,
                count=spec.fire_count,
            )

    def clean(self):
        """Drop references (the effect owns no scene nodes)."""
        self.game = None
        self.owner = None


def _hull_jitter(severity: int) -> np.ndarray:
    """
    A small random offset so fire puffs flicker across the hull rather than
    stacking on the exact centre. Grows a little with severity.

    :param severity: The current severity level
    :return: A length-3 world-space offset
    """
    spread = 0.5 * severity
    return np.array(
        [
            random.uniform(-spread, spread),
            random.uniform(-spread, spread),
            random.uniform(-spread, spread),
        ]
    )
