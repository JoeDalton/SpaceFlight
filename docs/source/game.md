# Game

The `game` package is the session's runtime: the `FlightState` that owns
every live subsystem, physics integration, collision resolution, time
keeping, and the mission engine that runs a level's scripted events. This page is the guided tour; the per-class API is generated from the
docstrings in the [code reference](apidocs/index.rst).

Most of the code lives in
[`src/space_flight/game/`](../../src/space_flight/game/), with level definitions
under [`game/levels/`](../../src/space_flight/game/levels/) and the mission
scripting engine under [`game/scenario/`](../../src/space_flight/game/scenario/).

## `FlightState` — the session owner

[`flight_state.py`](../../src/space_flight/game/flight_state.py)'s `FlightState`
is the app state active while actually flying (as opposed to menus or loading
screens); `game` throughout the rest of the codebase almost always means
"the current `FlightState` instance." It owns every session-scoped
subsystem — the integrator, collision system, interactions, mission,
explosion/fire-smoke and spark pools, time keeping, the player, the scene,
HUD — and drives the top-level per-frame update.

- **Two-phase, animated level entry.** `enter()` builds the level in two
  phases around a hyperspace-jump animation
  ([`hyperspace_loading_state.py`](../../src/space_flight/game/hyperspace_loading_state.py)):
  first `_build_upfront()` runs synchronously on a black screen for GPU-heavy
  one-time work (player, ocean/cloud reflections) so their first-render
  compile spike is invisible; then `_build_generator` (a generator from the
  level module) is advanced one step per frame by the loading overlay during
  its looping "inside" phase, via `_advance_build`. `_on_build_complete`
  wires up input/HUD/tasks once the build finishes (still hidden behind the
  animation); `_on_reveal` starts the simulation exactly as the overlay fades
  out, so the world is already alive the moment it becomes visible. With
  `WAIT_FOR_JUMP_KEY` (`True` by default) the overlay holds the tunnel after
  the build until the player presses the jump-out key. Headless runs
  (`FlightState(app, headless=True)`) skip the overlay and HUD entirely:
  `_enter_headless` builds both phases synchronously and starts the
  simulation straight away.
- **`update_game_world_task`** is the fixed per-frame order of operations:
  delayed methods → kill destructibles whose health hit zero → resolve
  collisions → recompute actor interactions → integrate physics → run every
  actor's registered update methods (`game.method_lists`) → check player
  death. **`update_mission_task`** separately advances `game.mission` each
  frame. Both are no-ops while `is_paused`.
- **`initialize_game_structure()`** constructs every session-scoped object
  once, in dependency order (see [Where things live](#where-things-live)
  below for the object graph), and **`exit()`** tears them down in roughly
  reverse order (the `Mission` is simply dropped rather than cleaned) — the
  two together are the definitive list of what a `FlightState` owns.
- `pause()`/`resume()` propagate to `IntervalManager` and `GameTimeManager` so
  intervals and the game clock freeze together, e.g. for the pause menu.

## Time keeping

[`time_keeping.py`](../../src/space_flight/game/time_keeping.py) has three small
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

[`integrator.py`](../../src/space_flight/game/integrator.py)'s `Integrator` is a
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

[`collisions.py`](../../src/space_flight/game/collisions.py) is the largest
module in this package: it defines Panda3D collision layers and owns all the
`*-into-*` event handlers that turn a raw collision entry into game effects.

- **`CollisionLayers`** defines bitmask layers (`MUNITION`, `SHIELD`,
  `DESTRUCTIBLE`, `ENVIRONMENT`, plus `SENSOR` sharing bit 0 with
  `MUNITION`) and, for each named collider type
  (`laser`/`bomb`/`sensor`/`destructible`/`terrain`/`subsystem`/`shield`), which
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
  - **Munition hits** (`munition_into_destructible`, `munition_into_terrain`,
    `munition_into_shield`, shared by lasers and bombs) apply damage, delete
    the munition node, and trigger the matching sound. A shield only blocks a
    munition crossing *inward* — one fired from inside passes through,
    resolved by the sign of the munition's velocity dotted with the shield's
    surface normal (see the handler's own docstring).
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

[`game/levels/`](../../src/space_flight/game/levels/) has one Python module
per level, holding everything about it: its tunable constants, its waves
(`WaveSpec` constants), a `build_<name>_upfront(game)` function for the
black-screen phase (create the player, pick a
[scene](../../src/space_flight/scenes/) and build its heavy objects), and a
mission body — the level's scripted events, see
[scenario_scripting.md](scenario_scripting.md).

| Level | File | Scene | Premise |
|-------|------|-------|---------|
| Mission 1: Rookies | [`mission1_level.py`](../../src/space_flight/game/levels/mission1_level.py) | `asteroids` | Tutorial: target-filter menu, follow a formation, then race it |
| Mission 2: Escort | [`intro_level.py`](../../src/space_flight/game/levels/intro_level.py) | `ocean_planet` | Escort a convoy past an enemy blockade |
| Dev | [`dev_level.py`](../../src/space_flight/game/levels/dev_level.py) | `debug` | Sandbox for the latest feature under development |

`game/levels/__init__.py`'s `LEVELS` registry maps
`app.configuration["selected_level"]` to a `LevelEntry(upfront, mission,
description)`. `FlightState._build_upfront` calls the level's upfront
function; `_make_build_generator` builds the rest of the scene
(`scene.build_decomposed()`) during the animation, then creates the level's
`Mission` and starts its body.

## Mission scripting

[`game/scenario/`](../../src/space_flight/game/scenario/) runs a level's
mission body — a plain Python generator — see
[scenario_scripting.md](scenario_scripting.md) for how to write one.

- **`mission.py`** (`Mission`, `Trigger`): the per-level owner, kept on
  `game.mission`. Each frame, `update()` fires the due reactive rules
  (`Trigger`s registered with `on()`), then steps every running **job** — a
  generator advanced once per frame: the mission body itself, and each
  wave's spawn (distinct from the level-build generators in `FlightState`).
  It also provides the sequencing helpers (`wait`, `wait_until`), the
  clock-based conditions (`after`, `delay`, `sustained`) and the actions
  (HUD text, subtitled speech — audio is a logging stub for now — player
  waypoints, ending the level).
- **`wave.py`** (`WaveSpec`, `WaveHandle`): a `WaveSpec` is a frozen
  dataclass describing a group of bots; a `WaveHandle` is its live side for
  one run. Spawning schedules a job creating one ship per frame (so a large
  wave never stalls a frame), optionally arranged into a `Formation` (see
  [docs/ai.md](ai.md)) — each ship taking the formation's next free slot, so
  a wave can `join` another's formation even mid-spawn. The handle records
  its members' pawn ids, reads their state live (`pawns`, `alive`,
  `all_destroyed`, `any_destroyed`) and mutates them (`set_targets`,
  `set_team` — which cascades a capital ship's cached team to its
  sub-systems, shield and mounted turrets — and `set_waypoints`).
- **`conditions.py`**: zero-argument condition factories (`near`,
  `near_actor`, `reached_waypoint`), the `all_of`/`any_of`/`not_`
  combinators, and `pawns_of`, the single resolver turning a wave handle, a
  Player/Bot or a pawn into live pawns.

## `Record`

[`record.py`](../../src/space_flight/game/record.py)'s `Record` is a minimal
offline-analysis logger, gated by the `RECORD_GAME` flag: `new_time` starts
a new row keyed by the current game time, `record` appends a named value to
the current row, and `save` dumps the accumulated rows to a timestamped
Parquet file under `target/`. Used by `Player.record_state` (see
[docs/actors.md](actors.md)) to capture flight-dynamics traces for tuning,
and by `Bot.record_state` for bots of a `WaveSpec(record=True)` wave
(their tactical decisions).

## Where things live

`FlightState` (`flight_state.py`) is the root object; its
`initialize_game_structure`/`exit` pair is the definitive list of everything
a session owns: `GameTimeManager`/`IntervalManager`/`DelayedMethodManager`
(`time_keeping.py`), `FireSmokePool` and `SparkPool` (see
[docs/fx.md](fx.md)), `Destructibles` (see [docs/actors.md](actors.md)), `CollisionSystem`
(`collisions.py`), `Interactions` (see [docs/ai.md](ai.md)), `Integrator`
(`integrator.py`), and `Mission` (`scenario/mission.py`). Level definitions
live under [`game/levels/`](../../src/space_flight/game/levels/), one module per
level; the mission scripting engine lives under
[`game/scenario/`](../../src/space_flight/game/scenario/). The auto-generated
[code reference](apidocs/index.rst) has the full per-class API.
