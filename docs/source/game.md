# Game

The `game` package is the session's runtime: the `FlightState` that owns
every live subsystem, physics integration, collision resolution, time
keeping, and the mission engine that runs a level's scripted events. This
page is the guided tour; the per-class API is in the
[code reference](apidocs/index.rst).

The code lives in [`src/space_flight/game/`](../../src/space_flight/game/),
with level definitions under
[`game/levels/`](../../src/space_flight/game/levels/) and the mission engine
under [`game/scenario/`](../../src/space_flight/game/scenario/).

## `FlightState` — the session owner

[`flight_state.py`](../../src/space_flight/game/flight_state.py)'s `FlightState`
is the app state active while flying (as opposed to menus or loading
screens); `game` elsewhere in the codebase almost always means "the current
`FlightState`". It owns every session-scoped object (see
[Where things live](#where-things-live)) plus the player, the scene and the
HUD, and drives the per-frame update.

- **Two-phase, animated level entry.** `enter()` builds the level around a
  hyperspace-jump animation
  ([`hyperspace_loading_state.py`](../../src/space_flight/game/hyperspace_loading_state.py)):
  1. `_build_upfront()` runs synchronously on a black screen for the
     GPU-heavy one-time work (player, ocean and its reflection, cloud
     field), so its first-render compile spike is invisible;
  2. the loading overlay then advances `_build_generator` (the rest of the
     scene, then the mission) one step per frame via `_advance_build`,
     during its looping "inside" phase;
  3. `_on_build_complete` wires up input, HUD and tasks, still hidden behind
     the animation;
  4. `_on_reveal` starts the simulation as the overlay fades out, so the
     world is alive the moment it becomes visible.

  With `WAIT_FOR_JUMP_KEY` (`True` by default) the overlay holds the tunnel
  after the build until the player presses the jump-out key. Headless runs
  (`FlightState(app, headless=True)`) skip the overlay and HUD:
  `_enter_headless` builds both phases synchronously and starts at once.
- **`update_game_world_task`** is the fixed per-frame order: delayed methods
  → kill destructibles whose health hit zero → resolve collisions →
  recompute actor interactions → integrate physics → run every actor's
  registered update methods (`game.method_lists`) → re-centre the render
  origin on the player (see
  [The floating render origin](#the-floating-render-origin)) → check player
  death. **`update_mission_task`** separately advances `game.mission`. Both
  are no-ops while `is_paused`.
- **`initialize_game_structure()`** builds the session-scoped objects in
  dependency order; **`exit()`** tears them down in roughly reverse order
  (the `Mission` is simply dropped).
- `pause()`/`resume()` propagate to `IntervalManager` and `GameTimeManager`,
  so intervals and the game clock freeze together (e.g. for the pause menu).

## The floating render origin

The scene graph has two frames that are easy to confuse:

- **`game.root_node` is the world frame.** It is the single child of
  `render` created by `initialize_game_structure()`, and every gameplay node
  hangs under it: ships, munitions, asteroids, the ocean, clouds, skybox,
  lights. A position relative to `root_node` is a world position, the same
  thing physics stores in `pawn.position`.
- **`render` is the frame Panda3D draws from.** The engine composes every
  node's net transform from `render` down, in float32.

`FlightState.recenter_render_origin()` moves `root_node` inside `render` so
that the player's ship sits at the render origin. It runs every frame right
after the actors' updates (once `Ship.move()` has written and sanitised the
player's pose), and once in `_on_build_complete` so the first frame is
already centred.

**Why.** Physics runs in float64 numpy, but a float32 world position only has
a coarse grid far from the origin: about 1 mm at 10 km, 4 mm at 50 km and
8 mm at 100 km. The camera and the cockpit are siblings under the player's
ship node, so without the offset each gets its own large net transform,
rounded independently, and the cockpit shakes against the camera by several
pixels (issue #29). The ship node and the offset are rounded from the same
float64 position, so their translations cancel exactly, and everything near
the player gets small, precise render transforms. Nothing visibly moves: the
whole world, camera included, shifts by the same amount, and rendering only
depends on positions relative to the camera.

**Rules for code that touches the scene graph:**

- Read and write world positions relative to `game.root_node`
  (`getPos(root_node)`, `getSurfacePoint(root_node)`,
  `getRelativePoint(root_node, …)`), never relative to `render`. Parent new
  world-space nodes under `root_node`. Local moves (`setPos()` with no
  reference node) are unaffected.
- Treat render-space positions as valid for the current frame only: `render`
  space moves with the player every frame.
- In shaders, Panda3D's `p3d_ModelMatrix`, `p3d_ViewMatrix` and
  `p3d_ViewProjectionMatrix` are relative to `render`, not to the world. Don't
  mix them with positions Python measured relative to `root_node`. See the
  shader [mental model](shaders.md#mental-model) for how each shader deals
  with it.
- 3D audio (`Audio3DManager`) works in `render` space. That is fine because
  only positions relative to the listener matter, but a sound must be placed
  before it plays: see `SFX.attach_sound` in [docs/fx.md](fx.md).

**What stays at world scale.** Collision traversal resolves in float32 world
coordinates. Particle bursts (sparks, explosions, cockpit sparks) bake world
positions into their vertex data, so they keep a few millimetres of GPU
rounding far from the origin. World-anchored shader noise (the ocean swell)
is sampled at world coordinates. None of these is visible in practice.

The behaviour is pinned by the `recenter_render_origin` tests in
[`tests/test_flight_state.py`](../../tests/test_flight_state.py), including one
that shows the imprecision without the offset.

## Time keeping

[`time_keeping.py`](../../src/space_flight/game/time_keeping.py) has three small
pause-aware managers:

- **`GameTimeManager`** is the single source of truth for game time. It
  subtracts the cumulative time spent paused (`time_in_pause_s`) from
  Panda3D's real clock, so `get_current_time()` and `get_time_step()` freeze
  across a pause instead of jumping when play resumes. Everything that needs
  "now" or "dt" — physics, PID controllers, cooldowns — reads it rather than
  Panda3D's clock.
- **`IntervalManager`** tracks Panda3D `Interval`s (like the laser travel
  animation) so they pause/resume as a group, and drops each one once it
  finishes (`on_interval_done`).
- **`DelayedMethodManager`** reimplements Panda3D's `doMethodLater` on game
  time, so scheduled callbacks (laser cleanup, sound release, hit-force
  removal) respect pause too.

## `Integrator` — shared physics stepping

[`integrator.py`](../../src/space_flight/game/integrator.py)'s `Integrator` is
one flat state buffer shared by every physics-driven actor (ships, capital
ships), not one integrator per actor. Each frame, each actor calls
`set_state_variables` to claim the next contiguous slice of a pre-allocated
array (`FlightState` allocates `max_state_size=5000`) and gets back the index
to read its result from after `step()`. This avoids per-actor allocation and
lets one call advance the whole simulation. `step()` is a 2nd-order
Adams-Bashforth integrator (forward Euler on the very first step, when there
is no previous time step), computed in place on the claimed `[:next_idx]`
slice only; it then releases the whole buffer, since which actors exist can
change from frame to frame. `first_order_euler_step` is a separate one-off
integrator for low-precision motion (e.g. the player's camera head bob) that
needs no slot in the shared buffer.

## `CollisionSystem` — layers, routing and physical response

[`collisions.py`](../../src/space_flight/game/collisions.py) defines the
Panda3D collision layers and owns the handlers that turn a raw collision
entry into game effects.

- **`CollisionLayers`** defines bitmask layers (`MUNITION`, `SHIELD`,
  `DESTRUCTIBLE`, `ENVIRONMENT`, `DECOY`, plus `SENSOR` sharing bit 0 with
  `MUNITION`) and, for each collider type
  (`laser`/`ordnance`/`flare`/`sensor`/`destructible`/`terrain`/`subsystem`/`shield`),
  which layers it collides *from* and *into*. `terrain`, `subsystem`,
  `shield` and `flare` are into-only (they are only ever hit), so they are not
  registered with the traverser at all (`add_to_collision_handler=False`).
  `ordnance` (bombs, rockets, missiles) hits what a laser hits plus `DECOY`,
  the flares' layer; nothing hits ordnance, and only ordnance hits flares, so
  two flares never collide.
- **`owners_share_vehicle()`** spares a ship from colliding with its own
  bolted-on parts: two collision owners are the "same vehicle" if they're
  identical, one is `mounted_on` the other, or both share the same
  `mounted_on` host (siblings). Every handler that could fire on a
  ship-vs-its-own-subsystem pair checks it first.
- **`CollisionSystem`** owns the `CollisionTraverser` and two handlers:
  - a `CollisionHandlerEvent` with `-into-`/`-again-` patterns, used by every
    collider except sensors, with a handler method subscribed to each event
    name Panda3D emits;
  - a `CollisionHandlerQueue` for collision sensors (`sensor_queue`), read
    directly instead of going through events: see
    [Sensor contacts](#sensor-contacts-from-traversal-to-avoidance) below.

  `update_collisions()` (called once per frame from `FlightState`) runs the
  traverser, then hands each queued sensor contact to `sensor_into_obstacle`.
  The game logic lives in the handler methods:
  - **Munition hits** (`munition_into_destructible`, `munition_into_terrain`,
    `munition_into_shield`, shared by lasers and ordnance) apply damage, spend
    the munition (`on_impact()`), and trigger sparks and sound. A shield only blocks a
    munition crossing *inward* — one fired from inside passes through —
    decided by the sign of the munition's velocity dotted with the shield's
    surface normal.
  - **Flares** (`ordnance_into_flare`): ordnance hitting a flare of another
    team is spent, and so is the flare.
  - **Ship physical hits** (`ship_into_*` / `ship_again_*` pairs, against
    ships, terrain, turrets and subsystems) resolve an impulse collision
    tuned by `SOLID_COLLISION_ELASTICITY`, rather than Panda3D's collision
    forces, which are too stiff. In `ship_into_subsystem_pushback` the hit
    subsystem is rigid and never itself pushed: momentum is exchanged between
    the incoming ship and the subsystem's **parent ship** (split by mass),
    while the collision *damage* goes to the subsystem alone.
  - **`sensor_into_obstacle`** records the hit (normal + point) onto the
    sensor for `CollisionSensor.compute_repulsion` (see [docs/ai.md](ai.md))
    to consume later in the same frame.
- **`attach_collision_sphere` / `_tube` / `_segment` / `_plane`** are the
  factory functions every actor uses to build a collider: they resolve the
  from/into masks for a collider type, attach the Panda3D collision solid,
  tag it with an `owner` python-tag (read back by every handler above), and
  register it with the traverser unless its type is into-only (with the
  sensor queue for sensors, the event handler otherwise).

### Sensor contacts: from traversal to avoidance

Sensor contacts don't go through Panda3D's event messenger: there are ~100
of them per frame, and routing each one through events cost more than the
avoidance itself. They are plain function calls instead.

**Setup.** `CollisionSensor.__init__` builds its three look-ahead spheres
with `attach_collision_sphere(..., collider_type="sensor")`, which registers
them with the traverser using `CollisionSystem.sensor_queue`.

**Each frame, inside `FlightState.update_game_world_task`:**

1. **Traversal.** `update_collisions()` runs `traverser.traverse(render)`,
   during which Panda3D clears `sensor_queue` and fills it with one
   `CollisionEntry` per contact of an *active* sensor sphere (other colliders
   still throw their events).
2. **Recording.** Right after, `update_collisions()` calls
   `sensor_into_obstacle(entry)` for each queued entry. The handler finds the
   sensor from the entry's `owner` tag, ignores contacts with the sensor's
   own vehicle (`owners_share_vehicle`), and calls
   `sensor.record_obstacle({normal, hit_point, range})`. The sensor keeps only
   the current frame's contacts: the first contact of a new frame starts a
   fresh list.
3. **Consumption.** Later in the same frame, a bot that thinks runs its
   navigator, whose `navigate_avoidance` calls
   `collision_sensor.compute_repulsion()` on the contacts recorded in step 2;
   contacts left from an earlier frame are discarded.
4. **Next frame's sensor state.** At the end of its update, the bot calls
   `sensor.set_active(...)` (`Bot._schedule_sensor`): the sensor is active only
   if the bot thinks next frame. An inactive sensor's spheres have an empty
   from-collide mask, so the next traversal skips them, saving the traversal
   cost for bots that won't read the contacts. If a frame comes later than
   expected and a bot is due to think while its sensor sat out that frame's
   traversal, the bot turns the sensor on and thinks one frame later, so it
   never thinks without fresh contacts. The player's sensor is never
   switched off.

This is also one frame fresher than events, which Panda3D's event-loop task
delivers at the start of the *next* frame.

## Levels

[`game/levels/`](../../src/space_flight/game/levels/) has one module per level
holding everything about it: tunable constants, its waves (`WaveSpec`
constants), a `build_<name>_upfront(game)` function for the black-screen
phase (create the player, pick a [scene](../../src/space_flight/scenes/) and
build its heavy objects), and a mission body — the level's scripted events,
see [scenario_scripting.md](scenario_scripting.md).

| Level | File | Scene | Premise |
|-------|------|-------|---------|
| Mission 1: Rookies | [`mission1_level.py`](../../src/space_flight/game/levels/mission1_level.py) | `asteroids` | Tutorial: target-filter menu, follow a formation, then race it |
| Mission 2: Smugglers | [`mission2_level.py`](../../src/space_flight/game/levels/mission2_level.py) | `asteroids` | Patrol with a formation, scan passing transports, stop the gun-runner |
| Mission 3: Escort | [`intro_level.py`](../../src/space_flight/game/levels/intro_level.py) | `ocean_planet` | Escort a convoy past an enemy blockade |
| Dev | [`dev_level.py`](../../src/space_flight/game/levels/dev_level.py) | `lava_planet` | Sandbox for the latest feature under development |

`game/levels/__init__.py`'s `LEVELS` registry maps
`app.configuration["selected_level"]` to a `LevelEntry(upfront, mission,
description)`; the level selection menu reads it too. `FlightState` calls
the level's upfront function in `_build_upfront`; `_make_build_generator`
builds the rest of the scene (`scene.build_decomposed()`) during the
animation, then creates the level's `Mission` and starts its body.

## Mission scripting

[`game/scenario/`](../../src/space_flight/game/scenario/) runs a level's
mission body — a plain Python generator; see
[scenario_scripting.md](scenario_scripting.md) for how to write one.

- **`mission.py`** (`Mission`, `Trigger`): the per-level owner, kept on
  `game.mission`. Each frame, `update()` fires the due reactive rules
  (`Trigger`s registered with `on()`), then steps every running **job** — a
  generator advanced once per frame: the mission body, each wave's spawn,
  each scan, and anything `schedule()`d (distinct from the level-build
  generator in `FlightState`). It also provides the sequencing helpers
  (`wait`, `wait_until`), the clock-based conditions (`after`, `delay`,
  `sustained`), scanning (`scan`, implemented in `actors/scan.py`) and the
  actions (HUD text, subtitled speech — audio is a logging stub for now —
  player waypoints, ending the level).
- **`wave.py`** (`WaveSpec`, `WaveHandle`): a `WaveSpec` is a frozen
  dataclass describing a group of bots; a `WaveHandle` is its live side for
  one run. Spawning schedules a job creating one ship per frame (so a large
  wave never stalls a frame), optionally arranged into a `Formation` (see
  [docs/ai.md](ai.md)) — each ship taking the formation's next free slot, so
  a wave can `join` another's formation even mid-spawn. The handle records
  its members' pawn ids, reads their state live (`pawns`, `alive`,
  `all_destroyed`, `any_destroyed`) and mutates them (`set_targets`,
  `set_team`, `set_waypoints`, `follow`).
- **`conditions.py`**: zero-argument condition factories (`near`,
  `near_actor`, `reached_waypoint`, `damaged`), the `all_of`/`any_of`/`not_`
  combinators, and `pawns_of`, the single resolver turning a wave handle, a
  Player/Bot or a pawn into live pawns.

## `Record`

[`record.py`](../../src/space_flight/game/record.py)'s `Record` is a minimal
offline-analysis logger, enabled by the `RECORD_GAME` flag: `new_time` starts
a row keyed by the current game time, `record` adds a named value to the
current row, and `save` dumps the rows to a timestamped Parquet file under
`target/`. Used by `Player.record_state` (see [docs/actors.md](actors.md)) to
capture flight-dynamics traces for tuning, and by `Bot.record_state` for
bots of a `WaveSpec(record=True)` wave (their tactical decisions).

## Where things live

`FlightState` (`flight_state.py`) is the root object; its
`initialize_game_structure`/`exit` pair is the definitive list of what a
session owns: `GameTimeManager`/`IntervalManager`/`DelayedMethodManager`
(`time_keeping.py`), `FireSmokePool` and `SparkPool` (see [docs/fx.md](fx.md)),
`Destructibles` (see [docs/actors.md](actors.md)), `CollisionSystem`
(`collisions.py`), `Interactions` and `ThinkScheduler` (see
[docs/ai.md](ai.md)), `Integrator` (`integrator.py`), `Mission`
(`scenario/mission.py`) and, with `RECORD_GAME`, `Record` (`record.py`).
