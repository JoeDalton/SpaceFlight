# Game

The `game` package is the session's runtime: the `FlightState` that owns
every live subsystem, physics integration, collision resolution, time
keeping, and the data-driven scenario/mission engine that scripts a level's
events. This page is the guided tour; the per-class API is generated from the
docstrings in the [code reference](docs/).

Most of the code lives in
[`src/space_flight/game/`](../src/space_flight/game/), with level definitions
under [`game/levels/`](../src/space_flight/game/levels/) and the scenario
scripting engine under [`game/scenario/`](../src/space_flight/game/scenario/).

## `FlightState` — the session owner

[`flight_state.py`](../src/space_flight/game/flight_state.py)'s `FlightState`
is the app state active while actually flying (as opposed to menus or loading
screens); `game` throughout the rest of the codebase almost always means
"the current `FlightState` instance." It owns every session-scoped
subsystem — the integrator, collision system, interactions, scenario,
explosion pool, time keeping, the player, the scene, HUD — and drives the
top-level per-frame update.

- **Two-phase, animated level entry.** `enter()` builds the level in two
  phases around a hyperspace-jump animation
  ([`hyperspace_loading_state.py`](../src/space_flight/game/hyperspace_loading_state.py)):
  first `_build_upfront()` runs synchronously on a black screen for GPU-heavy
  one-time work (player, ocean/cloud reflections) so their first-render
  compile spike is invisible; then `_build_generator` (a generator from the
  level module) is advanced one step per frame by the loading overlay during
  its looping "inside" phase, via `_advance_build`. `_on_build_complete`
  wires up input/HUD/tasks once the build finishes (still hidden behind the
  animation); `_on_reveal` starts the simulation exactly as the overlay fades
  out, so the world is already alive the moment it becomes visible.
- **`update_game_world_task`** is the fixed per-frame order of operations:
  delayed methods → kill destructibles whose health hit zero → resolve
  collisions → recompute actor interactions → integrate physics → run every
  actor's registered update methods (`game.method_lists`) → check player
  death. **`update_scenario_task`** separately advances `game.scenario` each
  frame. Both are no-ops while `is_paused`.
- **`initialize_game_structure()`** constructs every session-scoped object
  once, in dependency order (see [Where things live](#where-things-live)
  below for the object graph), and **`exit()`** tears them all down in
  reverse — the two together are the definitive list of what a `FlightState`
  owns.
- `pause()`/`resume()` propagate to `IntervalManager` and `GameTimeManager` so
  intervals and the game clock freeze together, e.g. for the pause menu.

## Time keeping

[`time_keeping.py`](../src/space_flight/game/time_keeping.py) has three small
managers, all pause-aware:

- **`GameTimeManager`** is the single source of truth for "what time is it in
  the game." It tracks cumulative time spent paused (`time_in_pause_s`) and
  subtracts it from Panda3D's real clock, so `get_current_time()` and
  `get_time_step()` freeze cleanly across a pause rather than jumping when
  play resumes. Everything that needs "now" or "dt" — physics, PID
  controllers, cooldowns — reads through here rather than Panda3D's clock
  directly.
- **`IntervalManager`** wraps Panda3D `Interval`s (like the laser travel
  animation) so they can be paused/resumed as a group and are automatically
  dropped from tracking once they finish (`on_interval_done`).
- **`DelayedMethodManager`** reimplements Panda3D's `doMethodLater` on top of
  `GameTimeManager` instead of the engine's own clock, specifically so
  scheduled callbacks (laser cleanup, sound release, hit-force removal)
  respect pause the same way everything else does.

## `Integrator` — shared physics stepping

[`integrator.py`](../src/space_flight/game/integrator.py)'s `Integrator` is a
single flat state buffer shared by every physics-driven actor (ships,
capital ships), not one integrator per actor: each actor calls
`set_state_variables` to claim a contiguous slice of a pre-allocated array
(`max_state_size = 5000`) and gets back the index to read its result from
after `step()`. This avoids per-actor allocation and lets one `step()` call
advance the whole simulation. `step()` is a 2nd-order Adams-Bashforth
integrator (falling back to forward Euler on the very first step, when there
is no previous derivative), computed in-place only on the currently claimed
`[:next_idx]` slice; the buffer is re-claimed from scratch every frame since
which actors exist can change frame to frame. `first_order_euler_step` is a
separate, simpler one-off integrator used for low-precision motion (e.g. the
player's camera head bob) that doesn't need a slot in the shared buffer.

## `CollisionSystem` — layers, routing and physical response

[`collisions.py`](../src/space_flight/game/collisions.py) is the largest
module in this package: it defines Panda3D collision layers and owns all the
`*-into-*` event handlers that turn a raw collision entry into game effects.

- **`CollisionLayers`** defines bitmask layers (`LASER`, `SHIELD`,
  `DESTRUCTIBLE`, `ENVIRONMENT`, plus the implicit `SENSOR` sharing bit 0
  with `LASER`) and, for each named collider type
  (`laser`/`sensor`/`destructible`/`terrain`/`subsystem`/`shield`), which
  layers it collides *from* and *into*. `terrain`, `subsystem` and `shield`
  are into-only — like terrain, a subsystem or shield bubble never initiates
  a collision, it is only ever hit — so those three are not registered with
  the traverser's event handler at all (`add_to_collision_handler=False`).
- **`owners_share_vehicle()`** is the mechanism that spares a ship from
  colliding with its own bolted-on parts: two collision owners are the "same
  vehicle" if they're identical, one is `mounted_on` the other, or both share
  the same `mounted_on` host (siblings). Every handler that could otherwise
  fire on a ship-vs-its-own-subsystem pair checks this first.
- **`CollisionSystem`** owns the `CollisionTraverser` and a
  `CollisionHandlerEvent` with `-into-`/`-again-` patterns, and subscribes a
  handler method to each event name Panda3D emits. `update_collisions()`
  (called once per frame from `FlightState`) just runs the traverser; all the
  actual game logic lives in the handler methods:
  - **Laser hits** (`laser_into_destructible`, `laser_into_terrain`,
    `laser_into_shield`) apply damage, delete the laser node, and trigger the
    matching sound. A shield only blocks a laser crossing *inward* — one
    fired from inside passes through, resolved by the sign of
    `dot(laser.speed, surface_normal)` (see the module's own comment, and the
    `trials/shield_normal_test.py` experiment referenced there).
  - **Ship/terrain/turret physical hits** (`ship_into_*` / `ship_again_*`
    pairs) resolve an inelastic-ish impulse collision (tuned by
    `SOLID_COLLISION_ELASTICITY`) rather than using Panda3D's built-in rigid
    body physics, which the code notes are "too stiff" for this game's feel.
    `ship_into_subsystem_pushback` is the most involved: a hit subsystem is
    rigid and never itself pushed — momentum is exchanged between the
    incoming ship and the subsystem's **parent ship** (split by mass), while
    collision *damage* is dealt to the subsystem alone, never its parent.
  - **`sensor_into_obstacle`** just records the hit (normal + point) onto the
    sensor object for `CollisionSensor.compute_repulsion` (see
    [docs/ai.md](ai.md)) to consume next frame.
- **`attach_collision_sphere` / `_tube` / `_segment` / `_plane`** are the
  shared factory functions every actor uses to build a collider: they resolve
  the from/into masks for a collider type, attach the Panda3D collision
  solid, tag it with an `owner` python-tag (read back by every handler
  above), and register it with the traverser unless its type is into-only.

## Levels

[`game/levels/`](../src/space_flight/game/levels/) has one module per level,
each exposing the same two-function shape `FlightState.enter()` expects
(see above): `build_<name>_upfront(game)` for the black-screen phase, and
`build_<name>_level(game) -> Iterator` for the animated incremental phase. A
level's own logic is deliberately thin — spawn the player, pick a
[scene](../src/space_flight/scenes/), then hand off to `game.scene.build_decomposed()`
and a sibling YAML scenario file loaded via `load_scenario` (see below) — all
per-mission scripting lives in that YAML rather than in Python.

| Level | File | Scene | Premise |
|-------|------|-------|---------|
| Dev | [`dev_level.py`](../src/space_flight/game/levels/dev_level.py) | `asteroids` | Sandbox for the latest feature under development |
| Intro | [`intro_level.py`](../src/space_flight/game/levels/intro_level.py) | `ocean_planet` | Escort a convoy past an enemy blockade |
| Race | [`race_level.py`](../src/space_flight/game/levels/race_level.py) | `lava_planet` | Friendly checkpoint race against three rivals |

`FlightState._build_upfront`/`_make_build_generator` dispatch on
`app.configuration["selected_level"]` to pick which pair of functions to
call.

## Scenario — data-driven mission scripting

[`game/scenario/`](../src/space_flight/game/scenario/) turns a level's YAML
file into runtime `when → then` triggers, so mission design (spawn timings,
objectives, dialogue) lives in data rather than in each level's Python.

- **`loader.py`**: `load_scenario(path)` reads the YAML's `waves` (reusable
  spawn definitions) and `triggers` sections, recursively builds a
  `Condition`/`Action` callable for each single-key `{kind: arg}` node via
  `_build_condition`/`_build_action`, and returns a ready `Scenario`. Every
  wave id is pre-registered as an empty group up front so a condition
  referencing it before it has spawned resolves to "no live members" rather
  than warning about an unknown group.
- **`conditions.py`**: leaf conditions (`after_seconds`, `all_destroyed`,
  `any_alive`, `fired`, `near`, `reached_waypoint`) are plain
  `condition(game) -> bool` closures. Conditions that need memory are small
  callable classes instead: `Delay` latches the moment its inner condition
  first becomes true (so it survives the inner condition flickering back to
  false) and reports true `seconds` later; `AllOf`/`AnyOf` combine
  sub-conditions, letting YAML nest logic like
  `delay: {after: {all_destroyed: first_wave}, seconds: 3}`.
- **`actions.py`**: action factories build `action(game) -> None` closures.
  `spawn_wave` is the most involved — it schedules a **job** (a generator,
  see below) that spawns one ship per frame rather than blocking a whole
  frame on a large wave, optionally arranging wingmen into a `Formation`
  (see [docs/ai.md](ai.md)) around a leader. Other actions cover HUD text,
  player waypoints, subtitled speech (audio itself is a logging stub for
  now, `_play_speech_audio`), ending the level, and `all()` to sequence
  several actions under one trigger.
- **`__init__.py`** (`Scenario`, `Trigger`): `Trigger.maybe_fire` evaluates
  its condition once per frame and runs its action the first time it's true
  (or every frame, with `once=False`). `Scenario` is the per-level owner:
  it fires every trigger and steps every running **job** each frame
  (`update`/`_step_jobs` — jobs are the generator-based mechanism
  `spawn_wave` uses to spread heavy work across frames, distinct from the
  level-build generators in `FlightState`). It also tracks **identity
  groups** (`spawn`/`register`, ids appended as bots are created — the only
  sanctioned way to add a member, so the registry can never drift from
  reality) and **query groups** (`register_query`, a predicate evaluated
  live against all actors, e.g. "enemies"), unified behind `resolve()` so
  conditions/actions don't need to know which kind a group name refers to.

## `Record`

[`record.py`](../src/space_flight/game/record.py)'s `Record` is a minimal
offline-analysis logger, gated by the `RECORD_GAME` flag: `new_time` starts
a new row keyed by the current game time, `record` appends a named value to
the current row, and `save` dumps the accumulated rows to a timestamped
Parquet file under `target/`. Used by `Player.record_state` (see
[docs/actors.md](actors.md)) to capture flight-dynamics traces for tuning.

## `LoadingState`

[`loading_state.py`](../src/space_flight/game/loading_state.py)'s
`LoadingState` is a simple, non-animated alternative to the hyperspace
overlay: it shows a progress bar while Panda3D's threaded model loader loads
a single model, then transitions straight to `FlightState` once done. It
predates the two-phase hyperspace build described above and is a much
thinner fallback for cases that don't need a scripted-in-two-phases level
entry.

## Where things live

`FlightState` (`flight_state.py`) is the root object; its
`initialize_game_structure`/`exit` pair is the definitive list of everything
a session owns: `GameTimeManager`/`IntervalManager`/`DelayedMethodManager`
(`time_keeping.py`), `FireSmokePool` (see [docs/fx.md](fx.md)),
`Destructibles` (see [docs/actors.md](actors.md)), `CollisionSystem`
(`collisions.py`), `Interactions` (see [docs/ai.md](ai.md)), `Integrator`
(`integrator.py`), and `Scenario` (`scenario/__init__.py`). Level definitions
live under [`game/levels/`](../src/space_flight/game/levels/), one module (and
a sibling YAML) per level; the scenario scripting engine lives under
[`game/scenario/`](../src/space_flight/game/scenario/). The auto-generated
[code reference](docs/) has the full per-class API.
