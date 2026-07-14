"""
Standalone demo for the hyperspace loading shaders.

Plays the same sequence the in-game loading overlay does, but driven by the
keyboard so the transitions are easy to inspect:

    into  (entering, fixed)  ->  inside (seamless looping tunnel)
        --[SPACE]-->  outof (dropping out)  ->  quit

It loads the real shaders from space_flight/datafiles/shaders (not local
copies), so it doubles as a quick visual check of those files. Run it from a
project environment where space_flight is importable::

    python scripts/demo_transition.py

Controls:
    SPACE   jump out of hyperspace (only while the tunnel is showing)
    ESC     quit
"""

import sys

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    CardMaker,
    ClockObject,
    LVecBase2f,
    Shader,
    TransparencyAttrib,
    Vec3,
)

from space_flight import DATAFILES_PATH

_SHADER_DIR = DATAFILES_PATH / "shaders"
_VERT = _SHADER_DIR / "hyperspace.vert"
_FRAGS = {
    "into": _SHADER_DIR / "hyperspace_into.frag",
    "inside": _SHADER_DIR / "hyperspace_inside.frag",
    "outof": _SHADER_DIR / "hyperspace_outof.frag",
}

# Fed to hyperspace_into.frag as the iIntoDuration uniform, so the shader's
# whiteout lands exactly when "into" cross-fades to the tunnel.
INTO_DURATION = 2.5
OUTOF_DURATION = 1.9
FADE_DURATION = 1.0
CENTER_OFFSET = 0.1


def _smoothstep(x):
    """
    Ease 0..1 with a Hermite curve, matching the in-game overlay's fades.

    :param x: input in any range; clamped to 0..1
    :return: the eased value
    """
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


class HyperspaceTransitionDemo(ShowBase):
    """
    A keyboard-driven player for the three hyperspace phase shaders.

    Mirrors the cross-fade scheme of the in-game overlay: two stacked fullscreen
    quads, an opaque back quad and an incoming front quad faded in on top.
    """

    def __init__(self):
        super().__init__()
        self.set_background_color(0, 0, 0)
        self.disable_mouse()

        self._clock = ClockObject.getGlobalClock()
        self._shaders = {
            name: Shader.load(Shader.SL_GLSL, vertex=_VERT, fragment=frag)
            for name, frag in _FRAGS.items()
        }

        # Two stacked fullscreen quads: index 0 = back (sort 0), 1 = front.
        self._quads = [self._make_quad(sort=0), self._make_quad(sort=1)]
        props = self.win.getProperties()
        res = LVecBase2f(props.getXSize(), props.getYSize())
        for quad in self._quads:
            quad.setShaderInput("iResolution", res)
            quad.setShaderInput("iMouse", Vec3(0, 0, 0))
            quad.setShaderInput("iTime", 0.0)
            quad.setShaderInput("iAlpha", 0.0)
            quad.setShaderInput("iCenterOffset", CENTER_OFFSET)
            quad.setShaderInput("iIntoDuration", INTO_DURATION)
            quad.hide()

        self._quad_time = [0.0, 0.0]
        self._back = 0
        self._front = 1
        self._transitioning = False
        self._fade_t = 0.0
        self._next_state = None

        self._show_shader(self._back, "into", alpha=1.0)
        self._state = "into"

        self.accept("space", self._request_jump_out)
        self.accept("escape", sys.exit)
        self.accept("window-event", self._on_window)
        self.win.set_close_request_event("window-close")
        self.accept("window-close", sys.exit)
        self.taskMgr.add(self._update, "hyperspace_demo_update")

        print(__doc__)

    # -- internals -----------------------------------------------------------

    def _make_quad(self, sort):
        """
        Build one transparent fullscreen quad on render2d.

        :param sort: fixed-bin sort order (higher draws on top)
        :return: the quad NodePath
        """
        cm = CardMaker("hyperspace_quad")
        cm.setFrameFullscreenQuad()
        quad = self.render2d.attachNewNode(cm.generate())
        quad.setDepthWrite(False)
        quad.setDepthTest(False)
        quad.setTransparency(TransparencyAttrib.MAlpha)
        quad.setBin("fixed", sort)
        return quad

    def _show_shader(self, idx, name, alpha):
        """
        Assign a phase shader to a quad, reset its clock and reveal it.

        :param idx: quad index (0 or 1)
        :param name: phase shader name (into / inside / outof)
        :param alpha: initial cross-fade opacity
        """
        self._quads[idx].setShader(self._shaders[name])
        self._quad_time[idx] = 0.0
        self._quads[idx].setShaderInput("iAlpha", alpha)
        self._quads[idx].show()

    def _start_transition(self, next_state):
        """
        Begin cross-fading the incoming phase in over the opaque back quad.

        :param next_state: phase shader name to fade in
        """
        self._transitioning = True
        self._fade_t = 0.0
        self._next_state = next_state
        self._show_shader(self._front, next_state, alpha=0.0)

    def _finish_transition(self):
        """Swap the faded-in front quad to be the new opaque back quad."""
        self._transitioning = False
        self._state = self._next_state
        self._quads[self._back].hide()
        self._back, self._front = self._front, self._back
        self._quads[self._back].setShaderInput("iAlpha", 1.0)
        self._quads[self._back].setBin("fixed", 0)
        self._quads[self._front].setBin("fixed", 1)

    def _request_jump_out(self):
        """Trigger the outof phase, but only while the tunnel is showing."""
        if self._state == "inside" and not self._transitioning:
            self._start_transition("outof")

    def _update(self, task):
        dt = self._clock.getDt()

        for i in range(2):
            if not self._quads[i].isHidden():
                self._quad_time[i] += dt
                self._quads[i].setShaderInput("iTime", self._quad_time[i])

        if self._transitioning:
            self._fade_t += dt
            self._quads[self._front].setShaderInput(
                "iAlpha", _smoothstep(self._fade_t / FADE_DURATION)
            )
            if self._fade_t >= FADE_DURATION:
                self._finish_transition()
            return task.cont

        back_time = self._quad_time[self._back]
        if self._state == "into":
            if back_time >= INTO_DURATION:
                self._start_transition("inside")
        elif self._state == "inside":
            pass  # loops seamlessly until the user presses SPACE
        elif self._state == "outof":
            if back_time >= OUTOF_DURATION:
                sys.exit(0)

        return task.cont

    def _on_window(self, win):
        """Keep iResolution in sync when the window is resized."""
        props = win.getProperties()
        res = LVecBase2f(props.getXSize(), props.getYSize())
        for quad in self._quads:
            quad.setShaderInput("iResolution", res)


if __name__ == "__main__":
    HyperspaceTransitionDemo().run()
