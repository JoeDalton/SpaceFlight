# Performance

This page is for developers profiling the game's CPU cost. It covers how to
measure it, where the time currently goes, and which optimization levers are
left, with their expected gain and trade-offs. Rendering (GPU) is out of scope:
all figures come from headless runs, which don't render.

## Measuring

`invoke profile` runs the Dev level headlessly with ~20 ships:
[`scripts/profile_dev_level.py`](../../scripts/profile_dev_level.py) steps
through three windows.

1. **Warm-up** (`--warmup-steps`, default 200): lets the mission's waves spawn.
2. **Timed** (`--timing-steps`, default 900), without the profiler: prints the
   median, 99th percentile and max frame time. Use it to spot periodic spikes,
   which a profile's totals hide.
3. **Profiled** (`--steps`, default 900) under `cProfile`: prints the top
   functions and writes `profiles/dev_level.prof`. Browse that file with
   `poetry run snakeviz profiles/dev_level.prof`.

cProfile inflates the cost of the many small Python calls, so profiled
seconds are a relative measure. Compare frame times for real-time gains.
Headless runs are not fully deterministic (random AI and effects), so run
twice before trusting a small difference.

## Where the time goes

Snapshot of the Dev level, 900 frames:

- **Total:** ~5.0–5.5s profiled, median frame ~3.7–4.2 ms.
- **Before optimization** (history below): 23.8s profiled, and 6.7 ms median
  frame once recording was off.

| Item | Profiled | Share | Notes |
|---|---|---|---|
| Ship physics (`Ship.move`) | 2.1s | ~38% | `compute_derivatives` 0.9s, `set_inputs` + low-pass filter 0.4s, `_sanitize_state` 0.25s, node `setPos` 0.08s; most of the ~234k small `np.array` creations (0.25s) |
| Bots thinking | ~1.1s | ~20% | navigate 0.31s, weapon triggers 0.30s, auto-aim 0.21s, tactician 0.17s, pilot 0.16s |
| Collision traversal (C++) | 0.45–0.5s | ~9% | ship, munition and active sensor colliders |
| Turret / tractor-beam mounts | 0.41s | ~7% | per-frame aim integration and firing checks |
| `Interactions.update_interactions` | 0.29s | ~5% | already vectorized |
| Panda3D event system | 0.24s | ~4% | ~16 events per frame, 80% of them discarded (see below) |

## Remaining levers

Ranked by expected gain.

### 1. Vectorize the ship flight model (largest)

The flight model runs once per ship per frame: ~19k calls per 900 frames,
each doing arithmetic on 3- and 4-element arrays. Most of the cost is Python
and numpy call overhead, not arithmetic. Computing every ship's derivatives
at once would turn this into a few whole-array operations over all ships. The
arrays would be positions, orientations, speeds, rates, thrust, and the
drag / lift parameters. `Interactions` already works this way.

- **Expected gain:** plausibly half or more of the ~2.1s, and it grows with
  ship count.
- **Cost:** a structural refactor of `Ship` and the `Integrator`. Ship state
  would live in shared arrays instead of per-ship objects, and per-ship
  special cases (death tumble, tractor-beam forces, non-finite state
  recovery) would have to be vectorized too, or handled out of the batch.
- **How to verify it:** a parity test against the current per-ship
  `compute_derivatives`. The existing `test_ship.py` reference test is the
  model to follow.

### 2. Stop capital ships colliding with their own subsystems

Every frame, each capital ship's hull touches its own turret, shield
generator and targeting system. Each contact becomes a
`ship-again-subsystem` event, which `ship_into_subsystem_pushback` then discards
because `owners_share_vehicle` says it's the same vehicle. That's ~13 of the
~16 events per frame, plus their collision tests.

- **Fix:** give subsystems their own collision layer, which fighters and
  munitions test against but capital-ship hulls don't. The contacts are then
  never generated.
- **Expected gain:** ~0.15s profiled for the events, plus some traversal time.
- **Trade-off (gameplay):** a capital ship ramming *another* capital ship's
  turret would then only register as hull-against-hull.

### 3. Smaller items

Each is worth a few percent at most.

- **`set_inputs` / `low_pass_filter_first_order`** (~0.4s): the thrust and
  rates are filtered through a 4-element array every frame. A scalar filter
  per input, in plain floats, would avoid the array round-trip.
- **`_sanitize_state`** (0.25s): `np.all(np.isfinite(state))` plus two pose
  copies every frame. Could check finiteness more cheaply, and only copy the
  last good pose every few frames.
- **Turret mounts** (0.41s): same kind of per-mount small-array work as the
  ships; would fold into lever 1 if mounts joined the batch.
- **Weapon triggers** (0.30s): they re-resolve target geometry from
  `Interactions` every frame between thinks. Needed for rate of fire and bomb
  accuracy, but the lookups could be cached per frame.

## Mission 3 (rendered)

Mission 3 is the heaviest level: WorldBuilder's planet (terrain, raymarched
clouds with genera and cirrus, swell ocean, shadows) and some 25 ships lit and
shadowed by the world. The headless harness cannot run it (it draws nothing,
and the sea needs a window), so it is measured drawn, by
`scripts/bench_mission3.py`: the real game in an offscreen buffer at a fixed
size and render scale 1.0, warmed up until the first waves have spawned and the
world has settled, then 600 frames each waiting for the GPU (CPU and GPU in
series). `--pose fly`, `--toggle`, `--world SECTION.KNOB=VALUE`, `--profile` and
`--pstats` as its docstring says.

Two runs of the same tree differ by up to 0.8 ms: compare medians of runs
interleaved, at least two each.

### Where the time goes (RTX 3070, 2560x1440, high)

About 17 ms a frame, still:

- **The GPU, ~7.5 ms**, then Panda's cull and draw on the CPU, ~5.5 ms. The
  frame is GPU-bound at this size: at 1280x720 it is ~11 ms.
- The cloud raymarch is the largest GPU item: a quarter of the view's
  resolution instead of a half takes ~3.5 ms off, 32 steps instead of 64
  ~1.4 ms (both lower the clouds' quality: left to the graphics settings).
- `World.update`, ~2 ms of Python, mostly the light at the camera and at the
  ships (`lights_at`, a CPU march through the clouds' shadow).
- The bots, ~1.5 ms (flight model and thinking, see above).
- The rear-view mirror, the cirrus and the ships' shadows each cost under
  0.5 ms. Drawing the ships with Panda3D's lights instead of the world's
  model shader is *slower* (+2.5 ms): one light state per ship.

### Done

| Change | Effect |
|---|---|
| Every wave's ship models loaded while the level loads (`FlightState._preload_wave_models`) | No more 1-2 s stall when a new kind of ship first spawns (the glTF importer's tangents) |
| The light at the ships and the camera reckoned every 3 frames (`World.light_period`, `LIGHT_PERIOD_FRAMES`), at once when the sun moves or a ship is tracked | ~0.5 ms |
| "Up" reckoned at the player once a second for every ship (`Scene.up_at`, `UP_REFRESH_S`) | gravity evaluations from 6 call sites per bot per frame gone |
| The model shader's attrib set only when it changes; the bodies' arrays and the casters' bookkeeping kept between frames (WorldBuilder) | fewer render states made each frame |
| The HUD's FPS and flare lines set only when their text changes | |
| The speed dust animated in its vertex shader (`speed_dust.vert`) | a Python loop over 100 nodes gone |
| The Earth-like ground solid within 10 km (`TERRAIN_COLLISION_RANGE_M`; WorldBuilder's default is now 20 km) | fewer chunks checked each frame |
| The cloud march's inputs bound once, the planet's rotation given only when it turns (WorldBuilder) | fewer render states made each frame |

Measured, no change: `transform-cache false` in the PRC (16.4/15.8 ms
median without, 16.6/16.5 with).

PStats (`--pstats` with `text-stats`) of a still frame: on the GPU, the
clouds' far and near marches 2.5 and 1.5 ms, the main view 2.8 ms (its far
range 2.1), the sea's reflection 0.55 ms; on the CPU, Panda's draw 5.3 ms
(3 ms setting states), its cull 1.5 ms, the game's Python about 6.5 ms. See
WorldBuilder's docs/source/performance_backlog.md for what is left there.

Still: 17.5-18.1 ms median (mean 18.3-20.7 with the stalls) before,
16-17 ms (mean 16.1-17.4) after. Flying: 19.3 ms median, 22.2 mean, 832 ms
worst before; 16.8, 17.4 and 51 ms after.

### Left

- The clouds' raymarch resolution and steps, and the render scale: the
  frame's GPU cost, but each lowers what is seen.
- Panda's cull and draw (~5.5 ms): the scene is culled by about ten cameras
  (near and far, the clouds' two depth passes, the sea's reflection, the
  mirror, the shadow maps).
- The bots' flight model (above).

## Ruled out

- **Collision queues for every collision.** Sensors switched from events to a
  `CollisionHandlerQueue` because they produced ~100 contacts per frame. Only
  ~16 events per frame remain, so the ceiling is ~0.2s profiled. Queues also
  don't distinguish first contact from continuing contact, which the
  `*-into-*` / `*-again-*` handlers rely on, so that bookkeeping would have to
  be rebuilt by hand. Lever 2 removes most of those events more simply.
- **Updating `Interactions` pairs less often (issue #19).** Once vectorized,
  recomputing every pair costs about as much as scheduling per-pair updates.
  Navigators and auto-aim also need fresh geometry every frame for lead
  pursuit and firing solutions.
- **Approximating `sqrt` near 1** (2nd-order Taylor, in `normalize`). Slower
  than `math.sqrt` in CPython, and its ~1e-4 error broke exact-orthonormality
  assumptions.

## History

Optimizations so far, in order:

1. **Small-vector math out of numpy's generic routines:**
   - `rotate_single_vector`, `cross3`, `normalize`, `magnitude` and the
     low-pass filter's array branch use plain floats;
   - one rotation matrix per ship per frame in `compute_derivatives`;
   - scalar `np.clip` calls replaced by `min`/`max`.
2. **`Interactions.update_interactions` vectorized** over all live pairs.
3. **Recording off by default** (`RECORD_GAME = False`).
4. **Bots think on their pilot's sample clock** (`ThinkScheduler`, see
   [ai.md](ai.md#when-a-bot-thinks)), with a balanced spread over frames and
   per-frame weapon checks in between.
5. **Sensor contacts through a queue**, collected only on the frame before a
   bot thinks (see
   [game.md](game.md#sensor-contacts-from-traversal-to-avoidance)).
