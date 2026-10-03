# UI

`ui` is the player-facing layer between raw hardware and gameplay: the input
pipeline (hardware polling → contexts that interpret it), the HUD, the
rear-view mirror, and player waypoint guidance. This page is the guided tour;
the per-class API is in the [code reference](apidocs/index.rst).

All of it lives in [`src/space_flight/ui/`](../../src/space_flight/ui/).

## Mental model

- Input has two layers, each with one job:
  [`input_reader.py`](../../src/space_flight/ui/input_reader.py) only knows
  *hardware* (which raw button/axis is active this frame — no game logic);
  [`input_context.py`](../../src/space_flight/ui/input_context.py) only knows
  *meaning* (what a bound action does in the current game mode). A new game
  mode means a new `InputContext` pushed on the stack — never touching the
  reader.
- Only the **top** of the `InputContextStack` receives input each frame, so
  pushing a context (e.g. the radial menu over flight) blocks whatever is
  beneath it without either context knowing about the other.
- Every action name (`"fire"`, `"pause"`, `"throttle_up"`, ...) is resolved
  through the YAML bindings (`configuration/configuration.yaml`), never
  hardcoded to a key. Since every reader exposes the same `InputState` shape,
  the same context code drives keyboard, gamepad and joystick.
- `HUD`, `TargetHUD` and `PlayerWaypoints` follow the scene-piece lifecycle
  (see [docs/scenes.md](scenes.md)): construct with `game`, register a
  per-frame update in `game.method_lists`, `clean()`. `RearViewMirror` (owned
  by `Player`) and `WaypointMarker` (driven by `PlayerWaypoints`) have no
  per-frame task, only `clean()`.

## `input_reader.py` — the hardware layer

Each frame the reader subclass matching the configured `input_type` rebuilds a
plain `InputState` snapshot (`buttons`/`repeats`/`releases`/`axes`):

- **Hybrid detection.** **Polling** is the primary source: `read_all_buttons()`
  each frame, compared with the previous frame to derive pressed/held/released.
  **`accept()` events** are a safety net for a button pressed *and* released
  between two polls, which polling alone would miss. `event-repeat` is
  deliberately unused — held state comes from polling only.
- **`KeyboardReader`** polls Panda3D's `MouseWatcher` for every bound key.
  Keyboards have no analogue axes, so `read_axes` is a no-op and flight axes
  are synthesised in `FlightInputContext`.
- **`GamepadReader`** and **`JoystickReader`** poll their device, apply dead
  zones (`dz()`: zeroes the band and shifts the rest down so output starts at
  0 at its edge; not renormalised, so full deflection gives `1 - dead_zone`),
  and handle hot-plugging (falling back to another device of the same class,
  or showing an on-screen warning when none is attached). Only
  `GamepadReader` registers per-button safety-net events; most flight-stick
  buttons don't generate reliable Panda3D events, so `JoystickReader` is
  polling-only.
- **The Windows Unicode monkey-patch.** `_patched_attachInputDevice` /
  `_patched_detachInputDevice` replace two `ShowBase` methods that read
  Panda3D's `device.name`, which raises `UnicodeDecodeError` for some
  controllers. `safe_device_name()` provides a printable name instead, with a
  three-tier fallback (direct read → re-encode → synthesised
  `VID_xxxx&PID_xxxx`).
- **`reader_factory(app)`** loads `configuration.yaml` onto `app.bindings` and
  instantiates the matching reader. It runs at startup and again when input
  settings are saved (see [docs/menus.md](menus.md#settings-screens)), so
  remapped bindings apply without a restart.

## `input_context.py` — the meaning layer

`InputContext` is the abstract base (`consume(state)` is the only required
method; `on_activate`/`on_deactivate`/`clean`/`refresh_bindings` are optional
hooks). `InputContextStack.dispatch()` only calls the top context, and
`push`/`pop` handle (de)activation. Concrete contexts:

- **`FlightInputContext`** — the gameplay context: ship axes, weapons, boost,
  targeting, mirror, radial menu, head-look and pause, read from
  `contexts.flight.<input_type>`. Weapons are `fire` (lasers),
  `fire_secondary` (the selected bomb, rocket or missile launcher, while
  held), `cycle_secondary` (on press) and `drop_flare` (while held); held
  launches are paced by each launcher's reload. Its `pressed`/`held`/`active`/`released`
  helpers also check the `global` section (`axis` does not), so a key bound
  once globally (e.g. Escape for pause) works on every input type.
  `keyboard_axes` synthesises continuous axes from key presses: throttle
  accumulates while held (clamped to `[0, 1]`), and yaw/pitch/roll go through
  `low_pass_filter_first_order` so a key press doesn't snap to full
  deflection. `analog_axes` reads gamepad/joystick axes directly, applying
  the `invert_*` bindings.
- **`PauseMenuInputContext`** — pushed by the pause menu, it blocks everything
  except the pause key (device-specific or global), which calls
  `state_manager.pop()`: normally that pops the pause menu, whose `exit()`
  pops this context and resumes `FlightState` (if a settings screen is open
  above the pause menu, that screen is popped instead). Sitting above
  `FlightInputContext`, it freezes the ship's controls with no extra logic.
- **`HyperspaceInputContext`** — the same blocking pattern for the hyperspace
  overlay's "press key to drop out" prompt (see [docs/game.md](game.md)): it
  fires its callback once on the `drop_hyperspace` key (device-specific or
  global, so the keyboard key works on any input type), then ignores input
  until the overlay pops it.
- **`RadialMenuInputContext`** — drives the radial target-filter menu (see
  [docs/menus.md](menus.md#in-session-overlays)). Each frame `read_direction`
  gets a 2D direction (analog axes, or directional keys combined into a
  vector); once its magnitude clears `min_magnitude`, `angle_to_slice` maps it
  to a slice (0 at the top, clockwise), and `on_hover` is called so the
  overlay highlights it live. Releasing the trigger pops the radial menu
  state and calls `on_select` with the slice (or `None`).

## `hud.py` — heads-up display

[`hud.py`](../../src/space_flight/ui/hud.py) has two independent overlays:

- **`HUD`** — a debug panel when `DEBUG_HUD` is set (player
  speed/health/shield, game time, team strengths, target lock, plus
  lead-bot/turret lines wrapped in `try`/`except AttributeError` so it
  tolerates levels without them), an FPS counter (graphics setting
  `hud.fps_counter`), and two timed message lines: `set_event_text` /
  `set_chatter_text` store a string plus an expiry time, and
  `clear_scenario_hud` blanks each once its game-time deadline passes. They
  are driven by the mission's `hud` and `speech` actions (see
  [docs/scenario_scripting.md](scenario_scripting.md#actions)). Bottom right, an
  `OrdnanceHUD` shows the secondary weapons of the cycle
  (`Fighter.secondary_cycle`) with their stock, spent ones at x0, on a
  [`RollingDrum`](#utilspy--generic-ui-items), the selected one facing the
  player. Under it, a line always shows the flares left.
- **`TargetHUD`** — projects the player's target into screen space each frame
  (`cam.getRelativePoint` + `lens.project`) to place a target box and
  distance/name labels. In view, the box encircles the target. The box turns
  red while auto-aim is locked on the target (`update_lock_tint`): a missile
  launched then is guided to it. Off-screen
  (outside the FoV *or* behind the camera) it is pinned to the screen border
  along the true bearing, by scaling the projected vector to meet the edge
  rectangle — clamping each axis separately would snap it to jittering
  corners. Behind the camera the projection is mirrored, so its sign is
  flipped; the depth is clamped away from zero so the projection stays finite
  near the camera's XZ plane (details in the code comments). The label shows
  the target's parent name, falling back to the target's own name
  (subsystems). If the target has a scan (`pawn.scan`, a `ScanState` from
  [`actors/scan.py`](../../src/space_flight/actors/scan.py)), a transparent bar
  fills the box in proportion to its progress — yellow while scanning, then
  green (clear) or red (contraband) — and its status ("SCANNING 42%",
  "CLEAR", "CONTRABAND") is appended to the name. Only that attribute is
  read, so any pawn a mission makes scannable gets the bar.

## `rear_view_mirror.py`

`RearViewMirror` renders a backward-facing camera into an offscreen texture
buffer shown as a small horizontally flipped card at the top of the screen.
Its resolution scales with the `mirror_scale` graphics setting;
`toggle_mirror()` (the `toggle_mirror` binding) deactivates the buffer as well
as hiding the card, so a hidden mirror costs nothing to render.

## `player_waypoints.py`

Backs the mission's `player_waypoints` action (see
[docs/scenario_scripting.md](scenario_scripting.md#actions)):

- **`WaypointMarker`** — a recoloured, semi-transparent sphere posing as a
  minimal pawn for targeting: it registers with `Interactions` (see
  [docs/ai.md](ai.md)) as a neutral (team 0) actor, so bots never target it,
  exposes the attributes the targeting system and HUD read (`id`, `team`,
  `position`, `is_dead`, ...), and has `category = "waypoint"` so the
  player's "Waypoints" target filter (see [docs/actors.md](actors.md)) can
  isolate it while other filters exclude it.
- **`PlayerWaypoints`** — shows only the *next* of an ordered list of
  positions through one reused marker. Each frame `update()` advances once the
  player is within `arrival_radius_m`, and shows the marker only while the
  player's target filter is `"Waypoints"`. After the last waypoint,
  `_finish()` removes the marker.

## `utils.py` — generic UI items

- **`make_text_line`** — a HUD-style line of text (small caps, drop shadow,
  fadable).
- **`RollingDrum`** — a looping list of text lines written round a cylinder
  seen from the side: the selected item faces the viewer, the previous and
  next ones are above and below, smaller, flattened by the curvature and
  fainter, until they turn out of sight. `update(items, selected, label)`
  rolls it to a new selection, by as many slots as it moved, the shorter way
  round, easing out over `roll_time_s` (on the clock it is given).

## Where things live

Every module above sits directly under
[`src/space_flight/ui/`](../../src/space_flight/ui/); the
[code reference](apidocs/index.rst) has the full per-class API.
