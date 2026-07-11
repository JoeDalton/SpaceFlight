# FX

Everything visually or aurally reactive but not part of core gameplay logic —
explosions, engine dust, impact sounds — lives in
[`src/space_flight/fx/`](../src/space_flight/fx/). This page is the guided
tour; the per-class API is generated from the docstrings in the
[code reference](docs/).

## Mental model

- Particle effects (explosions and hit sparks) are **GPU-driven**:
  a particle is written once at spawn time into a pre-allocated vertex
  buffer, and a GLSL vertex shader reconstructs its position/size/alpha every
  frame from those spawn-time parameters. The CPU's only recurring work is
  updating three small uniforms (time, camera right/up) — no per-particle
  CPU cost after spawn, which is what makes hundreds of live particles cheap.
- Non-particle FX (the speed dust cloud) are ordinary Panda3D nodes moved by
  a per-frame Python task — simpler, and fine at their much lower particle
  count.
- Sound (`SFX`) is a thin wrapper around Panda3D's `Audio3DManager`: it owns
  sound pools per impact type and attaches/detaches sounds to short-lived
  dummy nodes so 3D positioning and Doppler come for free.

## `fx/__init__.py` — the shared GPU particle system

[`fx/__init__.py`](../src/space_flight/fx/__init__.py) is a small framework,
not just package glue: it defines the vertex format and base class every
particle effect builds on, documented at length in its own module docstring
(worth reading directly for the exact vertex-column layout).

- **`make_particle_format(columns)`** — builds one interleaved vertex format
  **per effect**: the shared billboard columns (`vertex`, `corner`,
  `spawn_time`) plus the effect's own per-particle columns. Explosion adds
  `velocity`, `size`, `spin`, `lifetime`, `tile_rect`; spark adds `velocity`,
  `size`, `lifetime`, `gravity`, `spark_color`. Each custom column is read in
  GLSL directly by name — no bit-packing, and no repurposing of the semantic
  `color`/`texcoord` columns.
- **`ParticleBuffer`** — owns one `GeomNode` of `POOL_SIZE` (512) billboard
  quads, plus the shader and render state (additive or alpha blending,
  no depth-write, always-visible bounds so it skips frustum culling cheaply).
  Slots are tracked CPU-side as `(spawn_time, duration)` pairs so
  `alloc_slot()` can find or reclaim a free slot without reading back GPU
  memory. It takes a ready-compiled `Shader` and a `columns` spec (sub-classes
  supply both); `write_slot()` writes one quad's four identical vertices (only
  the `corner` selector differs), taking each effect column as a keyword
  argument (`velocity=…`, `size=…`, …) and reserving its slot for
  `delay + duration`. `update()` runs once per frame per buffer, pushing
  `uTime`, `uCamRight`, `uCamUp` — everything else (position, size, motion,
  fade) is computed entirely on the GPU from those spawn-time values, so a
  live particle never touches the CPU again after `write_slot`.
- **`load_atlas()`** — loads a sprite-atlas PNG plus its companion JSON rect
  descriptor into a `(Texture, rects)` pair, ready to be bound and indexed
  by a shader.

## `explosion_fx.py` — fire and smoke bursts

[`explosion_fx.py`](../src/space_flight/fx/explosion_fx.py) builds one
concrete effect on top of `ParticleBuffer`:

- **`_explosion_shader()`** lazily loads the shared GLSL shader from
  [`datafiles/shaders/explosion.{vert,frag}`](../src/space_flight/datafiles/shaders/)
  (see [shaders.md](shaders.md)) via `Shader.load`. The vertex shader reads
  each per-particle value straight from its own vertex column, computes
  particle age from `uTime - spawn_time`, grows the billboard over its life,
  and applies a fade-in ramp whose length is the `uFadein` uniform. The
  fragment shader samples the atlas tile whose UV rect arrived in the
  `tile_rect` column — no uniform array or dynamic indexing needed.
- **`_ExplosionBuffer`** is a thin `ParticleBuffer` subclass: it applies the
  shared shader, sets its layer's `uFadein`, and `spawn_particle()` resolves
  the particle's `tile_index` to its atlas UV rect before calling
  `write_slot` (fire and smoke differ only by `uFadein`).
- **`ExplosionPool`** is the object the rest of the game actually talks to
  (see `Bot.play_death`, `docs/actors.md`). It owns two `_ExplosionBuffer`s —
  fire and smoke, each its own atlas and shader — and `spawn()` emits one
  burst: fire particles launch immediately in a wide cone around the impact
  normal, smoke particles launch slightly later (`_SMOKE_DELAY`, via the
  vertex shader's `spawn_delay` mechanism — no CPU timer needed) in a
  narrower cone, so smoke visually trails the fire. All per-particle
  size/speed/lifetime values are randomised within tunable ranges and scaled
  by the caller's `scale` parameter, so a fighter's death and a capital
  ship's death can reuse the same pool with different burst sizes.
- **`spawn_hit()`** is a thin wrapper over `spawn()` for the small secondary
  explosion on laser hits (see `spark_fx.py` below): it passes the
  `HIT_EXPLOSION_*` knobs — a low billboard count, reduced speed, a small scale
  multiplier and a jet-angle multiplier — so hit bursts stay cheap and contained
  next to the much larger death explosions. `spawn()` grew keyword overrides
  (`fire_count`, `smoke_count`, `speed_scale`, `jet_angle_scale`) for this, and
  the fire/smoke emission is now factored into one `_emit_layer` helper driven
  by a `_Layer` config per layer.

## `spark_fx.py` — laser hit sparks

[`spark_fx.py`](../src/space_flight/fx/spark_fx.py) is the second concrete
particle effect: a short, bright burst of round glowing sparks thrown out of a
laser impact (distinct from the death-triggered explosion).

- **`SparkPool`** is a `ParticleBuffer` subclass (one shared buffer for every
  spark) loading `datafiles/shaders/spark.{vert,frag}` via `_spark_shader()`
  and the single `spark.png` sprite via the asset manager, with additive
  blending. `spawn(position, normal, base_velocity, preset)` emits a cone of
  sparks around the surface normal, each on a ballistic (gravity-pulled)
  trajectory and shrinking as it ages.
- **`SparkPreset`** (`METAL`, `ICE`, `ROCK`, `MAGIC`) bundles the per-hit look:
  two colours, count, speed, cone spread, gravity, lifetime and size. Crucially,
  colour and gravity are written **per particle** (not as uniforms) so bursts
  of different presets can be alive together in the one buffer without
  repainting each other — each spark's tint is premixed CPU-side from its size
  (a proxy for launch speed). Global tuning knobs at the top of the module
  (`SPARK_SIZE_SCALE`, `SPARK_SPEED_SCALE`, `SPARK_JET_ANGLE_SCALE`) scale every
  preset at once.
- The pool is created in `FlightState` as `game.spark_fx_pool` (beside
  `explosion_fx_pool`) and driven from the laser collision handlers in
  [`collisions.py`](../src/space_flight/game/collisions.py): `METAL` on
  destructible (bot) hits, `ICE` on shield hits (on top of the shield's own
  impact flash), and a material-dependent preset on terrain hits — chosen from
  the `_TERRAIN_SPARK_PRESET` map by the terrain object's declarative
  `material` attribute (`Ocean.material == "water"` → `ICE`,
  `AsteroidField.material == "rock"` → `ROCK`, `"metal"` → `METAL`). Each burst
  inherits the hit object's velocity so sparks ride a moving target.
- On a fraction of destructible hits (`HIT_EXPLOSION_CHANCE`, default 1/3), a
  small secondary explosion is also spawned via `ExplosionPool.spawn_hit()` —
  a contained, low-billboard-count burst (its own `HIT_EXPLOSION_*` knobs in
  `explosion_fx.py`) sharing the sparks' impact point, normal and velocity.

## `speed_dust_cloud.py` — engine speed feel

[`speed_dust_cloud.py`](../src/space_flight/fx/speed_dust_cloud.py)'s
`SpeedDustCloud` gives the player a sense of speed: a fixed pool of small
billboarded dust card sprites scattered in a box around the player's ship,
each `setBillboardPointEye()`'d to always face the camera. Unlike the GPU
particle system, these are plain Panda3D nodes updated from Python each
frame (`dust_update`): every particle drifts backward at the player's current
speed and is recycled to a random position ahead once it passes behind the
ship (`reset_particle`), and the whole cloud's opacity scales with speed
(`MIN_DUST_ALPHA`→`MAX_DUST_ALPHA`) so it reads as more intense at higher
velocity. `build()` can create the particle nodes incrementally in chunks
(`defer_build=True`, used with `yield from`) to spread the one-time node
creation cost across several frames instead of stalling on construction.

## `sfx.py` — 3D sound effects

[`sfx.py`](../src/space_flight/fx/sfx.py)'s `SFX` wraps Panda3D's
`Audio3DManager` for every non-music sound in the game:

- **Sound pools.** `get_sounds_from_asset_manager()` loads a named pool per
  impact category (player crash short/long, laser-on-hull, laser-on-shield,
  distant target hit, terrain hit) via the asset manager, which handles
  randomised pitch and playback slot reuse (`get_sound`/`release_sound`).
  `build_sound_pool()` is a lower-level helper that pre-loads a fixed-size
  pool from a glob pattern, for cases not routed through the asset manager.
- **Distance-aware playback.** `distant_impact_hit()` (used for AI-vs-AI or
  distant impacts, not directly on the player) computes volume from an
  inverse-square falloff against a reference distance and drops the sound
  entirely beyond `MAX_SOUND_DISTANCE_M`, so far-off fights don't spam audio.
- **Positioned one-shots.** `laser_impact_hit_on_player`, `player_crash` and
  `cannon_fire` each attach a sound to either an ad-hoc dummy node (placed at
  the relative hit point and auto-removed after `SFX_MAX_SOUND_DURATION_S`)
  or an existing node (a firing cannon), so Panda3D's 3D audio handles
  panning/attenuation/Doppler automatically. Every scheduled sound is
  released back to its pool after the same fixed duration via
  `game.delayed_methods.do_method_later`, so pools don't leak playing-sound
  references.
- **Placeholders.** `tractor_beam_grab`/`tractor_beam_release` are stubs that
  only log for now — the tractor beam mechanic works without a dedicated
  audio cue yet (see [subsystems.md](subsystems.md)).
- `update_task` drives `Audio3DManager.update()` once per frame via Panda3D's
  own task manager (not `game.method_lists` like everything else in this
  package), since it must run regardless of which actors are alive.

## Where things live

All of it lives directly under
[`src/space_flight/fx/`](../src/space_flight/fx/): the shared particle
framework in `__init__.py`, the explosion effect in `explosion_fx.py`, the
non-particle dust cloud in `speed_dust_cloud.py`, and sound in `sfx.py`. The
auto-generated [code reference](docs/) has the full per-class API.
