"""
Hyperspace overlay: the animated jump effect drawn over the whole screen.

Used both by the loading screen (see
:class:`~space_flight.game.hyperspace_loading_state.HyperspaceLoadingState`) and
by the in-flight warp. It has three phases, each its own fragment shader:

    into   (entering hyperspace: streaks, flare, white flash)
    inside (the seamlessly looping tunnel)
    outof  (dropping out: white flash, streaks, then the scene)

The overlay only draws: it knows nothing of level building, input or the
state stack. Its owner picks the phases and advances it with :meth:`update`,
on whichever clock suits it (the real clock for the loading screen, game time
for the warp, so that pausing the game freezes it).

What the loading screen and the warp do differently is the
:class:`HyperspaceLook`: opaque for loading (the half-built world must not
show), see-through for the warp (the player must see where they are going).

Cross-fades render two phase shaders at once on stacked fullscreen quads. The
back quad keeps its opacity; only the incoming front quad fades in, eased with a
smoothstep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from panda3d.core import LVecBase2f, Shader, Vec3

from space_flight import DATAFILES_PATH, WARP_MAX_WHITEOUT, WARP_TUNNEL_OPACITY
from space_flight.fx import make_fullscreen_quad
from space_flight.utils import clamp

if TYPE_CHECKING:
    from panda3d.core import GraphicsOutput, NodePath

_VERT = DATAFILES_PATH / "shaders/hyperspace.vert"
_FRAGS = {
    "into": DATAFILES_PATH / "shaders/hyperspace_into.frag",
    "inside": DATAFILES_PATH / "shaders/hyperspace_inside.frag",
    "outof": DATAFILES_PATH / "shaders/hyperspace_outof.frag",
}
PHASES = tuple(_FRAGS)

# Fixed durations, in seconds, of the non-looping phases.
# INTO_DURATION is fed to hyperspace_into.frag as the iIntoDuration uniform, so
# the shader's whiteout lands exactly when this phase cross-fades to the tunnel
# — one source of truth, no constant to keep in sync.
INTO_DURATION = 2.5
# Kept just under the shader's own 2.0s loop (T_MAX) so the effect has fully
# dissolved into the scene at the end instead of wrapping back to the opening
# white flash.
OUTOF_DURATION = 1.9
# Cross-fade length between two consecutive phases (and of a fade-out).
FADE_DURATION = 1.0
# Longest frame time the animation advances by. A one-off stall (e.g. a first
# spawn after the reveal) then shows as a brief hitch instead of skipping the
# rest of the current phase in a single frame.
MAX_DT = 1 / 30
# Tunnel vanishing point above the screen centre (in half the screen's shorter
# side), shared by all three phases so their centres line up across
# transitions. 0: on the crosshair, where the ship is heading.
CENTER_OFFSET = 0.0


@dataclass(frozen=True)
class HyperspaceLook:
    """
    The visual parameters of the overlay, fed to the shaders as uniforms.

    :param background_opacity: opacity of the black background, 0..1. Bright
        streaks and glows stay visible over the scene whatever its value.
    :param tunnel_opacity: overall opacity of the inside tunnel, 0..1
    :param max_whiteout: strength of the white flashes at the end of into and
        the start of outof, 0..1
    :param center_offset: tunnel vanishing point above the screen centre
    """

    background_opacity: float = 1.0
    tunnel_opacity: float = 1.0
    max_whiteout: float = 1.0
    center_offset: float = CENTER_OFFSET


# Opaque: hides the level while it builds
LOADING_LOOK = HyperspaceLook()
# See-through: the player keeps an eye on the scene while warping
WARP_LOOK = HyperspaceLook(
    background_opacity=0.0,
    tunnel_opacity=WARP_TUNNEL_OPACITY,
    max_whiteout=WARP_MAX_WHITEOUT,
)


def set_resolution(quads: list[NodePath], win: GraphicsOutput):
    """
    Feed the window size to the phase shaders of fullscreen quads.

    :param quads: The fullscreen quads
    :param win: The window (or offscreen buffer) they cover
    """
    res = LVecBase2f(win.getXSize(), win.getYSize())
    for quad in quads:
        quad.setShaderInput("iResolution", res)


def smoothstep(x: float) -> float:
    """Ease 0..1 with a Hermite curve for a softer-feeling fade."""
    x = clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


class HyperspaceOverlay:
    """
    The hyperspace effect on two stacked fullscreen quads of render2d.

    Typical use: :meth:`show` the first phase, :meth:`cross_fade_to` the next
    ones, :meth:`fade_out` (or let outof dissolve) and :meth:`destroy`. Call
    :meth:`update` every frame.
    """

    def __init__(
        self,
        render2d: NodePath,
        win: GraphicsOutput,
        look: HyperspaceLook = LOADING_LOOK,
    ):
        """
        Compile the phase shaders and build the (hidden) quads.

        :param render2d: The render2d node to draw on
        :param win: The window (or offscreen buffer) the quads cover
        :param look: The visual parameters
        """
        self.win = win
        self.look = look
        # Compile the three phase shaders (shared vertex shader).
        self._shaders = {
            name: Shader.load(Shader.SL_GLSL, vertex=_VERT, fragment=frag)
            for name, frag in _FRAGS.items()
        }

        # Two stacked fullscreen quads: index 0 = back (sort 0), 1 = front.
        self._quads = [
            make_fullscreen_quad(render2d, "hyperspace_quad", sort=sort)
            for sort in (0, 1)
        ]
        self._resolution = (win.getXSize(), win.getYSize())
        set_resolution(self._quads, win)
        for quad in self._quads:
            quad.setShaderInput("iMouse", Vec3(0, 0, 0))
            quad.setShaderInput("iTime", 0.0)
            quad.setShaderInput("iAlpha", 0.0)
            quad.setShaderInput("iCenterOffset", look.center_offset)
            quad.setShaderInput("iIntoDuration", INTO_DURATION)
            quad.setShaderInput("iBackgroundOpacity", look.background_opacity)
            quad.setShaderInput("iTunnelOpacity", look.tunnel_opacity)
            quad.setShaderInput("iMaxWhiteout", look.max_whiteout)
            quad.hide()

        # Per-quad elapsed time (each phase restarts its own clock from 0).
        self._quad_time = [0.0, 0.0]
        self._back = 0
        self._front = 1

        # The settled phase (on the back quad), None when nothing is shown
        self.phase: str | None = None
        self.transitioning = False
        self._fade_t = 0.0
        # Phase fading in on the front quad; None while fading out
        self._next_phase: str | None = None

    @property
    def phase_time(self) -> float:
        """Time since the settled phase started, in seconds."""
        return self._quad_time[self._back]

    @property
    def visible(self) -> bool:
        """Whether anything is drawn (a phase, or a cross-fade or fade-out)."""
        return self.phase is not None or self.transitioning

    def show(self, phase: str):
        """
        Show a phase at once, fully opaque, dropping whatever was shown.

        :param phase: "into", "inside" or "outof"
        """
        self.transitioning = False
        self._quads[self._front].hide()
        self._show_shader(self._back, phase, alpha=1.0)
        self.phase = phase

    def cross_fade_to(self, phase: str):
        """
        Fade a phase in over the current one, in FADE_DURATION. A cross-fade
        still running is completed at once first.

        :param phase: "into", "inside" or "outof"
        """
        if self.transitioning:
            self._finish_transition()
        if self.phase is None:
            self.show(phase)
            return
        self.transitioning = True
        self._fade_t = 0.0
        self._next_phase = phase
        self._show_shader(self._front, phase, alpha=0.0)

    def fade_out(self):
        """Fade the current phase out, in FADE_DURATION, then hide everything."""
        if self.transitioning:
            self._finish_transition()
        if self.phase is None:
            return
        self.transitioning = True
        self._fade_t = 0.0
        self._next_phase = None

    def hide(self):
        """Stop drawing at once (e.g. once outof has dissolved into the scene)."""
        self.transitioning = False
        for quad in self._quads:
            quad.hide()
        self.phase = None

    def update(self, dt: float):
        """
        Advance the animation: the visible quads' clocks and any fade.

        :param dt: Time since the last update, in seconds (clamped to MAX_DT)
        """
        dt = min(dt, MAX_DT)
        self._sync_resolution()

        # Advance time only on visible quads.
        for i in range(2):
            if not self._quads[i].isHidden():
                self._quad_time[i] += dt
                self._quads[i].setShaderInput("iTime", self._quad_time[i])

        if not self.transitioning:
            return
        self._fade_t += dt
        progress = smoothstep(self._fade_t / FADE_DURATION)
        if self._next_phase is None:
            # Fading out: the settled phase itself goes transparent
            self._quads[self._back].setShaderInput("iAlpha", 1.0 - progress)
        else:
            # Cross-fading: only the incoming phase changes, on top
            self._quads[self._front].setShaderInput("iAlpha", progress)
        if self._fade_t >= FADE_DURATION:
            self._finish_transition()

    def destroy(self):
        """Remove the quads. The overlay cannot be used afterwards."""
        for quad in self._quads:
            quad.removeNode()
        self._quads = []
        self._shaders = {}
        self.phase = None
        self.transitioning = False

    # -- internals -----------------------------------------------------------

    def _show_shader(self, idx: int, phase: str, alpha: float):
        """Assign a phase shader to a quad, reset its clock, reveal it."""
        self._quads[idx].setShader(self._shaders[phase])
        self._quad_time[idx] = 0.0
        self._quads[idx].setShaderInput("iTime", 0.0)
        self._quads[idx].setShaderInput("iAlpha", alpha)
        self._quads[idx].show()

    def _finish_transition(self):
        """Settle a cross-fade (the incoming phase becomes the back quad) or a
        fade-out (everything hidden)."""
        self.transitioning = False
        # Hide the outgoing quad so it stops rendering and advancing its clock.
        self._quads[self._back].hide()
        if self._next_phase is None:
            self.phase = None
            return
        self.phase = self._next_phase
        # The incoming quad becomes the new stable back quad.
        self._back, self._front = self._front, self._back
        self._quads[self._back].setShaderInput("iAlpha", 1.0)
        self._quads[self._back].setBin("fixed", 0)
        self._quads[self._front].setBin("fixed", 1)

    def _sync_resolution(self):
        """Follow window resizes (cheap: compares two integers per frame)."""
        resolution = (self.win.getXSize(), self.win.getYSize())
        if resolution != self._resolution:
            self._resolution = resolution
            set_resolution(self._quads, self.win)
