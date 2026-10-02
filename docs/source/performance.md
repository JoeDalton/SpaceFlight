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
`ship-again-subsystem` event, which `ship_again_subsystem` then discards
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
