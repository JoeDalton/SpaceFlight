# UI

`ui` is the player-facing layer that sits between raw hardware and gameplay:
the input pipeline (hardware polling → contexts that interpret it), the HUD,
the rear-view mirror, and player waypoint guidance. This page is the guided
tour; the per-class API is generated from the docstrings in the
[code reference](docs/).

All of it lives in [`src/space_flight/ui/`](../src/space_flight/ui/).

## Mental model

- Input is split into two layers, each with one job:
  [`input_reader.py`](../src/space_flight/ui/input_reader.py) only knows
  about *hardware* (which raw button/axis is active this frame — "no game
  logic lives here", per its own docstring);
  [`input_context.py`](../src/space_flight/ui/input_context.py) only knows
  about *meaning* (what a bound action does in the current game mode).
  Adding a new game mode means writing a new `InputContext` and pushing it —
  never touching the reader.
- Only the **top** of the `InputContextStack` receives input each frame.
  Pushing a context (e.g. the radial menu over flight) implicitly blocks
  whatever is beneath it without either context needing to know about the
  other.
- Every action name (`"fire"`, `"pause"`, `"throttle_up"`, ...) is resolved
  through YAML bindings (`configuration/configuration.yaml`), never
  hardcoded to a specific key or button — the same context code drives
  keyboard, gamepad, or joystick, since the reader always exposes the same
  `InputState` shape regardless of hardware.
- `HUD`, `RearViewMirror`, and `PlayerWaypoints`/`WaypointMarker` are
  independent presentation add-ons following the same lifecycle contract as
  scene pieces (see [docs/scenes.md](scenes.md)): construct with `game`,
  register a per-frame update in `game.method_lists`, `clean()`.

## `input_reader.py` — the hardware layer

[`input_reader.py`](../src/space_flight/ui/input_reader.py) turns physical
device state into a plain `InputState` snapshot (`buttons`/`repeats`/
`releases`/`axes`), rebuilt fresh every frame by whichever `InputReader`
subclass matches the configured `input_type`:

- **Hybrid detection.** Each reader combines **polling** (the primary
  source — `read_all_buttons()` each frame, compared against the previous
  frame to derive pressed/held/released) with **`accept()` events** as a
  safety net that catches a button pressed *and* released between two polls,
  which polling alone would miss entirely. `event-repeat` is deliberately
  not used — held state comes from polling only.
- **`KeyboardReader`** polls Panda3D's `MouseWatcher` for every bound key;
  keyboards have no analogue axes, so `read_axes` is a no-op and virtual
  flight axes are synthesised one layer up, in `FlightInputContext`.
- **`GamepadReader`** and **`JoystickReader`** poll their respective device
  APIs, apply dead zones (`dz()`, a symmetric dead-zone + linear rescale),
  and both support connect/disconnect hot-plugging (falling back to another
  attached device of the same class, or showing an on-screen warning label
  when none is present). `GamepadReader` additionally registers safety-net
  events per named button; `JoystickReader` deliberately does not, because
  the module notes most flight-stick buttons don't generate reliable Panda3D
  events — it's polling-only.
- **The Windows Unicode monkey-patch.** `_patched_attachInputDevice` /
  `_patched_detachInputDevice` replace two `ShowBase` methods to work around
  a `UnicodeDecodeError` some controllers trigger through Panda3D's
  `device.name` property; `safe_device_name()` is the corresponding
  three-tier fallback (direct read → re-encode attempt → synthesise a
  `VID_xxxx&PID_xxxx` string) used everywhere a printable device name is
  needed instead of touching `device.name` directly.
- **`reader_factory(app)`** loads `configuration.yaml` onto `app.bindings`
  and instantiates the matching reader subclass. It's called once at
  startup and again whenever input settings are saved (see
  [docs/menus.md](menus.md)'s `InputSettingsMenuState`), so remapped
  bindings take effect without a restart.

## `input_context.py` — the meaning layer

[`input_context.py`](../src/space_flight/ui/input_context.py) has the
`InputContext` abstract base (`consume(state)` is the only required method;
`on_activate`/`on_deactivate`/`refresh_bindings` are optional hooks) and the
`InputContextStack` that drives it — `dispatch()` only ever calls the top
context, and `push`/`pop` handle (de)activation. Concrete contexts:

- **`FlightInputContext`** is the main gameplay context, mapping bound
  actions onto ship controls, weapon fire, boost, targeting, camera look,
  and pause. It reads bindings from `contexts.flight.<input_type>` in the
  YAML and exposes small helpers (`pressed`/`held`/`active`/`released`/
  `axis`) that check both the context-specific and the `global` binding
  section for an action, so a key can be bound once globally (e.g. Escape)
  and still work everywhere. `keyboard_axes` synthesises continuous flight
  axes from discrete key presses — throttle accumulates while held
  (`+=` each frame, clamped to `[0, 1]`), yaw/pitch/roll pass through a
  first-order low-pass filter (`low_pass_filter_first_order`) so a keyboard
  press doesn't snap controls instantly to full deflection — while
  `analog_axes` reads gamepad/joystick axis values directly, since the
  hardware already gives a continuous signal.
- **`PauseMenuInputContext`** is a near-total input blocker pushed while
  paused: it does nothing except watch for the pause key (device-specific or
  global) to pop itself, letting the pause menu regain control of dismissal
  timing. Because it sits above `FlightInputContext` on the stack, the ship
  simply stops receiving input for as long as it's active — no explicit
  "freeze" logic needed.
- **`HyperspaceInputContext`** is the same blocking pattern applied to the
  hyperspace loading overlay's "press key to jump out" prompt (see
  [docs/game.md](game.md)): a one-shot trigger that fires its callback once
  on the bound key and then ignores further input, relying on the overlay's
  own reveal logic to pop it.
- **`RadialMenuInputContext`** drives the radial weapon/target-filter menu
  (see [docs/menus.md](menus.md)): each frame it reads a 2D direction
  (analog axes, or discrete directional keys combined into a vector) via
  `read_direction`, maps it to a slice index with the module-level
  `angle_to_slice` helper (slice 0 at the top, numbered clockwise) once the
  vector's magnitude clears `min_magnitude`, and calls the supplied
  `on_hover` each frame so the visual overlay can highlight the pointed-at
  slice live. Releasing the trigger button pops the radial menu state and
  fires `on_select` with the chosen slice (or `None`). It never touches game
  time, so gameplay keeps simulating while the wheel is open.

## `hud.py` — heads-up display

[`hud.py`](../src/space_flight/ui/hud.py) has two independent overlay
classes, both driven from a per-frame `game.method_lists` task:

- **`HUD`** renders four text blocks: a debug panel (FPS, player
  health/shield/speed, team counts, plus optional bot/turret debug lines
  guarded by `try`/`except AttributeError` so the HUD tolerates whichever
  debug actors happen to exist in the current level), an FPS counter, and
  two timed message lines — `set_event_text`/`set_chatter_text` set a string
  plus an expiry timestamp, and `clear_scenario_hud` blanks each one once
  its `game_time` deadline passes. `Scenario`'s `hud_text`/`speech` actions
  (see [docs/game.md](game.md)) drive these two lines.
- **`TargetHUD`** projects the player's current target's world position into
  screen space each frame (`cam.getRelativePoint` + `lens.project`) to
  position a target-box indicator and a distance/name label. When the
  target is *behind* the camera, the projected point is renormalized and
  clamped to the screen edge instead of showing the (mathematically valid
  but visually wrong) in-front projection, so the indicator reads as
  "off-screen behind you" rather than snapping to the wrong side. Falls back
  to the target's own name when it has no named parent (used for
  subsystems, which aren't bot-controlled).

## `rear_view_mirror.py`

[`rear_view_mirror.py`](../src/space_flight/ui/rear_view_mirror.py)'s
`RearViewMirror` renders a second, backward-facing camera into an offscreen
texture buffer and displays it as a small flipped card at the top of the
screen — the same offscreen-buffer-to-card pattern used by the graphics
pipeline's composite quad (see [docs/global_architecture.md](global_architecture.md))
and the ocean's reflection buffer (see [docs/scenes.md](scenes.md)). Its
resolution scales with the `mirror_scale` graphics setting; `toggle_mirror()`
(bound to a player action) disables both the camera buffer and the card so a
hidden mirror costs nothing to render.

## `player_waypoints.py`

[`player_waypoints.py`](../src/space_flight/ui/player_waypoints.py) gives the
player an on-screen guided route, used by the `player_waypoints` scenario
action (see [docs/game.md](game.md)):

- **`WaypointMarker`** is a recoloured, semi-transparent sphere that plays
  the role of a minimal "pawn" purely for targeting purposes: it registers
  itself with `Interactions` (see [docs/ai.md](ai.md)) as a neutral (team 0)
  actor exposing the small attribute contract (`id`, `team`, `position`,
  `is_dead`, ...) the targeting system and HUD expect, tagged with
  `category = "waypoint"` so the player's "Waypoints" target filter (see
  [docs/actors.md](actors.md)'s `Player`) can isolate it while other filters
  exclude it, and bots never target it (neutral team).
- **`PlayerWaypoints`** owns an ordered list of world positions and shows
  only the *next* one via a single reused `WaypointMarker`; each frame
  `update()` checks distance-squared against `arrival_radius_m` and advances
  the index once reached, hiding the marker whenever the player's target
  filter isn't `"Waypoints"`. Reaching the last waypoint calls `_finish()`,
  which cleans up the marker rather than leaving a stale route.

## Where things live

Everything in this page lives directly under
[`src/space_flight/ui/`](../src/space_flight/ui/): the hardware layer in
`input_reader.py`, the meaning layer in `input_context.py`, the HUD in
`hud.py`, the rear-view mirror in `rear_view_mirror.py`, and player waypoint
guidance in `player_waypoints.py`. The auto-generated
[code reference](docs/) has the full per-class API.
