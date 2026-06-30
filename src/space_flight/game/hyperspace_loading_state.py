"""
Hyperspace loading-screen overlay state.

Plays a hyperspace jump animation while the level builds underneath it:

    into   (entering, fixed duration — nothing heavy runs, so it is smooth)
      -> inside (looping tunnel; the level is built here, one step per frame,
                 and the loop is held until the build finishes)
      -> outof  (dropping out, fixed duration)
      -> reveal (fade the overlay out into the live game scene), then pops.

The build is driven *by this state*: it calls ``build_step`` once per frame
during the ``inside`` phase only. Keeping all heavy work out of ``into`` (and
out of every cross-fade) means those parts stay smooth; the unavoidable
per-step stutter is confined to the looping tunnel, which has no fixed
endpoint and so never "ends too soon".

Cross-fades render two phase shaders simultaneously on stacked fullscreen
quads. The back quad stays fully opaque (so the half-built world never shows
through); only the incoming front quad fades in, eased with a smoothstep.

This state declares ``PAUSES_BELOW = False`` so the :class:`FlightState`
below it stays alive (its game tasks are created during the build and only
start simulating once we trigger the reveal).
"""

from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    CardMaker,
    ClockObject,
    LVecBase2f,
    Shader,
    TextNode,
    TransparencyAttrib,
    Vec3,
)

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.base_state import BaseState

_VERT = DATAFILES_PATH / "shaders/hyperspace.vert"
_FRAGS = {
    "into": DATAFILES_PATH / "shaders/hyperspace_into.frag",
    "inside": DATAFILES_PATH / "shaders/hyperspace_inside.frag",
    "outof": DATAFILES_PATH / "shaders/hyperspace_outof.frag",
}

# Fixed durations, in seconds, of the non-looping phases.
# INTO_DURATION is fed to hyperspace_into.frag as the iIntoDuration uniform, so
# the shader's whiteout lands exactly when this phase cross-fades to the tunnel
# — one source of truth, no constant to keep in sync.
INTO_DURATION = 2.5
# Minimum time the looping tunnel is shown, even if the level loads instantly,
# so the "inside" phase never flashes by.
INSIDE_MIN_DURATION = 2.0
# Kept just under the shader's own 2.0s loop (T_MAX) so the effect settles to
# black at the end instead of wrapping back to the opening white flash.
OUTOF_DURATION = 1.9
# Cross-fade length between two consecutive phases.
FADE_DURATION = 1.0
# Final fade from the (now black) overlay into the live game scene.
REVEAL_DURATION = 0.8
# Tunnel vanishing-point offset below the screen centre, shared by all three
# phases so their centres line up across transitions.
CENTER_OFFSET = 0.1

_TASK_NAME = "hyperspace_update"


def _smoothstep(x):
    """Ease 0..1 with a Hermite curve for a softer-feeling fade."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


class HyperspaceLoadingState(BaseState):
    """Animated hyperspace overlay shown while a level loads."""

    # Keep the FlightState below us alive while the animation plays.
    PAUSES_BELOW = False

    def __init__(
        self,
        app,
        build_step=None,
        on_build_complete=None,
        on_reveal=None,
        wait_for_key=False,
        await_prompt="",
    ):
        """
        Create the overlay and store the callbacks the level drives it with.

        :param app: the ShowBase application
        :param build_step: callable advancing the level build by one step;
            returns True while steps remain, False once the build is complete.
            Called once per frame during the ``inside`` phase. If None, the
            overlay behaves as if the build is already finished.
        :param on_build_complete: called once, on the frame the build finishes
            (still during ``inside``). Good place to wire up input/HUD/tasks.
        :param on_reveal: called once, when the final reveal fade begins — i.e.
            as the world becomes visible. Good place to start the simulation.
        :param wait_for_key: when True, hold the looping tunnel after the build
            finishes (showing ``await_prompt``) until :meth:`request_jump_out`
            is called, instead of dropping out of hyperspace automatically.
        :param await_prompt: message shown while waiting for the jump-out key;
            empty for no on-screen text.
        """
        super().__init__(app)
        self._build_step = build_step
        self._on_build_complete = on_build_complete
        self._on_reveal = on_reveal
        self._wait_for_key = wait_for_key
        self._await_prompt = await_prompt

    def enter(self):
        self._clock = ClockObject.getGlobalClock()

        # Compile the three phase shaders (shared vertex shader).
        self._shaders = {
            name: Shader.load(Shader.SL_GLSL, vertex=_VERT, fragment=frag)
            for name, frag in _FRAGS.items()
        }

        # Two stacked fullscreen quads: index 0 = back (sort 0), 1 = front.
        self._quads = [self._make_quad(sort=0), self._make_quad(sort=1)]
        props = self.app.win.getProperties()
        res = LVecBase2f(props.getXSize(), props.getYSize())
        for quad in self._quads:
            quad.setShaderInput("iResolution", res)
            quad.setShaderInput("iMouse", Vec3(0, 0, 0))
            quad.setShaderInput("iTime", 0.0)
            quad.setShaderInput("iAlpha", 0.0)
            quad.setShaderInput("iCenterOffset", CENTER_OFFSET)
            quad.setShaderInput("iIntoDuration", INTO_DURATION)
            quad.hide()

        # Per-quad elapsed time (each phase restarts its own clock from 0).
        self._quad_time = [0.0, 0.0]
        self._back = 0
        self._front = 1

        self._transitioning = False
        self._fade_t = 0.0
        self._next_state = None
        self._build_done = self._build_step is None
        self._popped = False
        # Wait-for-jump state (only used when wait_for_key is True).
        self._awaiting_jump = False
        self._jump_requested = False
        self._prompt = None
        # Final reveal (fade overlay out to show the game scene).
        self._revealing = False
        self._reveal_t = 0.0

        # Start on the "into" phase, fully opaque on the back quad.
        self._show_shader(self._back, "into", alpha=1.0)
        self._state = "into"

        self.app.accept("window-event", self._on_window)
        self.app.taskMgr.add(self._update, _TASK_NAME)

    def exit(self):
        self.app.taskMgr.remove(_TASK_NAME)
        # Restore ShowBase's default window-event handler. `ignore` would leave
        # the app with no handler, so closing the window would no longer quit.
        self.app.accept("window-event", self.app.windowEvent)
        if self._prompt is not None:
            self._prompt.destroy()
            self._prompt = None
        for quad in self._quads:
            quad.removeNode()
        self._quads = []
        self._shaders = {}

    # -- internals -----------------------------------------------------------

    def _make_quad(self, sort):
        cm = CardMaker("hyperspace_quad")
        cm.setFrameFullscreenQuad()
        quad = self.app.render2d.attachNewNode(cm.generate())
        quad.setDepthWrite(False)
        quad.setDepthTest(False)
        quad.setTransparency(TransparencyAttrib.MAlpha)
        quad.setBin("fixed", sort)
        return quad

    def _show_shader(self, idx, name, alpha):
        """Assign a phase shader to a quad, reset its clock, reveal it."""
        self._quads[idx].setShader(self._shaders[name])
        self._quad_time[idx] = 0.0
        self._quads[idx].setShaderInput("iAlpha", alpha)
        self._quads[idx].show()

    def _start_transition(self, next_state):
        self._transitioning = True
        self._fade_t = 0.0
        self._next_state = next_state
        self._show_shader(self._front, next_state, alpha=0.0)

    def _finish_transition(self):
        self._transitioning = False
        self._state = self._next_state
        # Hide the outgoing quad so it stops rendering and advancing its clock.
        self._quads[self._back].hide()
        # The incoming quad becomes the new stable back quad.
        self._back, self._front = self._front, self._back
        self._quads[self._back].setShaderInput("iAlpha", 1.0)
        self._quads[self._back].setBin("fixed", 0)
        self._quads[self._front].setBin("fixed", 1)

    def _step_build(self):
        """Advance the level build by one step during the inside phase."""
        if self._build_done:
            return
        if not self._build_step():
            self._build_done = True
            if self._on_build_complete is not None:
                self._on_build_complete()

    def request_jump_out(self):
        """
        Ask the overlay to drop out of hyperspace now.

        Only has an effect while the overlay is waiting for the jump-out key
        (``wait_for_key``); the ``outof`` transition then begins on the next
        frame. Wired to the player's input via the hyperspace input context.
        """
        if self._awaiting_jump:
            self._jump_requested = True

    def _enter_await(self):
        """Begin waiting for the jump-out key, showing the prompt message."""
        self._awaiting_jump = True
        if self._await_prompt:
            self._prompt = OnscreenText(
                text=self._await_prompt,
                pos=(0.0, -0.85),
                scale=0.06,
                fg=(1.0, 1.0, 1.0, 1.0),
                shadow=(0.0, 0.0, 0.0, 0.6),
                align=TextNode.ACenter,
                mayChange=False,
            )
            # Draw on top of the (opaque) tunnel quads.
            self._prompt.setBin("fixed", 100)
            self._prompt.setDepthTest(False)
            self._prompt.setDepthWrite(False)

    def _exit_await(self):
        """Stop waiting and remove the prompt message."""
        self._awaiting_jump = False
        if self._prompt is not None:
            self._prompt.destroy()
            self._prompt = None

    def _update(self, task):
        dt = self._clock.getDt()

        # Final reveal: the animation is frozen on its last (black) frame; fade
        # the overlay out so the game scene behind it appears, then pop.
        if self._revealing:
            self._reveal_t += dt
            alpha = 1.0 - _smoothstep(self._reveal_t / REVEAL_DURATION)
            self._quads[self._back].setShaderInput("iAlpha", alpha)
            if self._reveal_t >= REVEAL_DURATION:
                self._pop_self()
                return task.done
            return task.cont

        # Advance time only on visible quads.
        for i in range(2):
            if not self._quads[i].isHidden():
                self._quad_time[i] += dt
                self._quads[i].setShaderInput("iTime", self._quad_time[i])

        # Drive the active cross-fade. The back quad stays fully opaque so the
        # half-built world never shows through; we only fade the incoming quad
        # in on top of it. No build steps run during a fade, so it stays smooth.
        if self._transitioning:
            self._fade_t += dt
            alpha = _smoothstep(self._fade_t / FADE_DURATION)
            self._quads[self._front].setShaderInput("iAlpha", alpha)
            if self._fade_t >= FADE_DURATION:
                self._finish_transition()
            return task.cont

        # Phase logic (only when stable, i.e. not mid-transition).
        back_time = self._quad_time[self._back]
        if self._state == "into":
            if back_time >= INTO_DURATION:
                self._start_transition("inside")
        elif self._state == "inside":
            # Build the level here, one step per frame, then leave once it is
            # done AND the tunnel has shown for at least INSIDE_MIN_DURATION.
            self._step_build()
            if self._build_done and back_time >= INSIDE_MIN_DURATION:
                if not self._wait_for_key:
                    self._start_transition("outof")
                else:
                    # Hold the (seamlessly looping) tunnel and prompt the player
                    # until request_jump_out() is called.
                    if not self._awaiting_jump:
                        self._enter_await()
                    if self._jump_requested:
                        self._exit_await()
                        self._start_transition("outof")
        elif self._state == "outof":
            if back_time >= OUTOF_DURATION:
                # Begin the final reveal: freeze the (now black) animation, fade
                # the overlay out, and bring the world to life as it appears.
                self._revealing = True
                self._reveal_t = 0.0
                if self._on_reveal is not None:
                    self._on_reveal()

        return task.cont

    def _pop_self(self):
        if self._popped:
            return
        self._popped = True
        # Popping triggers exit() (overlay cleanup) and resume() on the
        # FlightState below.
        self.app.state_manager.pop()

    def _on_window(self, win):
        # Accepting "window-event" on the app replaces ShowBase's own handler,
        # so call it explicitly to preserve default behaviour — in particular,
        # closing the window must still quit the app. We only piggy-back to keep
        # the shader resolution in sync with the window size.
        self.app.windowEvent(win)
        if not self._quads:
            return
        props = win.getProperties()
        res = LVecBase2f(props.getXSize(), props.getYSize())
        for quad in self._quads:
            quad.setShaderInput("iResolution", res)
