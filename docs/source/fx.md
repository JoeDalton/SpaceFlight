# FX

Everything visually or aurally reactive but not part of core gameplay logic —
explosions, engine dust, impact sounds — lives in
[`src/space_flight/fx/`](../../src/space_flight/fx/). This page is the guided
tour; the per-class API is generated from the docstrings in the
[code reference](apidocs/index.rst).

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

[`fx/__init__.py`](../../src/space_flight/fx/__init__.py) is a small framework,
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

## `fire_smoke_fx.py` — fire and smoke

[`fire_smoke_fx.py`](../../src/space_flight/fx/fire_smoke_fx.py) is one shared
fire/smoke billboard system on top of `ParticleBuffer`, fed by three effects:
one-shot explosions, laser-hit puffs, and the continuous per-ship damage/death
trail (`damage_fx.py`, below).

- **`_explosion_shader()`** lazily loads the shared GLSL shader from
  [`datafiles/shaders/explosion.{vert,frag}`](../../src/space_flight/datafiles/shaders/)
  (see [shaders.md](shaders.md)) via `Shader.load`. The vertex shader reads
  each per-particle value straight from its own vertex column, computes
  particle age from `uTime - spawn_time`, grows the billboard over its life,
  and applies a fade-in ramp whose length is the `uFadein` uniform. The
  fragment shader samples the atlas tile whose UV rect arrived in the
  `tile_rect` column — no uniform array or dynamic indexing needed.
- **`_FireSmokeBuffer`** is a thin `ParticleBuffer` subclass: it applies the
  shared shader, sets its layer's `uFadein`, and `spawn_particle()` resolves
  the particle's `tile_index` to its atlas UV rect before calling
  `write_slot` (fire and smoke differ only by `uFadein`).
- **`FireSmokePool`** is the object the rest of the game talks to (see
  `Bot.play_death`, `docs/actors.md`). It owns two `_FireSmokeBuffer`s — fire
  and smoke, each with its own atlas but sharing the one explosion shader —
  and exposes intention-revealing emitters that all share those buffers:
  - **`burst()`** — one one-shot explosion (a ship/subsystem dying): fire
    launches immediately, smoke slightly later (`SMOKE_DELAY`), so smoke
    trails the fire. The delay needs no CPU timer: the smoke particle is
    written with a future `spawn_time` (`write_slot(spawn_delay=...)`), so
    the shader simply sees it as not yet born. Only bursts given a surface
    `normal` fan out in cones around it (fire wide, smoke narrower); death
    explosions pass no normal, so their particles carry only the inherited
    velocity plus a random positional bias. Sizes/speeds/lifetimes are
    randomised within tunable ranges and scaled by the caller's `scale`, so a
    fighter's and a capital ship's deaths reuse the pool at different sizes.
  - **`hit_burst()`** — the small secondary explosion on laser hits (see
    `spark_fx.py`): `burst()` along the impact normal with the
    `HIT_EXPLOSION_*` knobs (low count, reduced speed, smaller scale, same
    cone angles — `HIT_EXPLOSION_JET_ANGLE_SCALE = 1.0`) so hits stay cheap
    next to deaths.
  - **`trail_smoke()` / `trail_fire()`** — one puff of the continuous damage
    trail. They use dedicated short-lived layers (`_TRAIL_SMOKE_LAYER`,
    `_TRAIL_FIRE_LAYER`) so that, emitted every frame across many damaged ships
    into this shared pool, only a handful are alive at once — long-lived trail
    particles would saturate the pool and flood the screen with transparent
    overdraw.
  Fire/smoke emission for every intent is factored into one `_emit_layer`
  helper driven by a `_Layer` config (which carries each layer's explicit
  lifetime range).

## `spark_fx.py` — laser hit sparks

[`spark_fx.py`](../../src/space_flight/fx/spark_fx.py) is the second concrete
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
  `fire_smoke_pool`) and driven from the laser collision handlers in
  [`collisions.py`](../../src/space_flight/game/collisions.py): on destructible
  (bot) hits, `ICE` when the target fighter's shield is still up else `METAL`;
  `ICE` on capital-ship shield-bubble hits (on top of the shield's own impact
  flash); and a material-dependent preset on terrain hits — chosen from
  the `_TERRAIN_SPARK_PRESET` map by the terrain object's declarative
  `material` attribute (`Ocean.material == "water"` → `ICE`,
  `AsteroidField.material == "rock"` → `ROCK`, `"metal"` → `METAL`).
  Destructible and shield hit bursts inherit the hit object's velocity so
  sparks ride a moving target; terrain bursts don't (the handler passes a
  zero velocity, since terrain is static).
- On a fraction of destructible hits (`HIT_EXPLOSION_CHANCE`, default 1/3,
  defined in `collisions.py` itself), a small secondary explosion is also
  spawned via `FireSmokePool.hit_burst()` — a contained, low-billboard-count
  burst (shaped by the `HIT_EXPLOSION_*` knobs in `fire_smoke_fx.py`)
  sharing the sparks' impact point, normal and velocity.

## `damage_fx.py` — damage & death smoke/fire trail

[`damage_fx.py`](../../src/space_flight/fx/damage_fx.py)'s `DamageFX` is a
per-actor smoke-and-fire trail that tracks how badly the actor is hurt. It owns
no geometry of its own — it emits into the shared `FireSmokePool` via
`trail_smoke()` / `trail_fire()`.

- **Severity-driven.** Each frame `update()` derives a `severity` (0 intact, 1
  smoking below ~2/3 health, 2 on fire below ~1/3, 3 dying) from the owner's
  `health / max_health`, forced to the maximum while `is_dying`. Because it is
  re-derived from health every frame (not stored), the trail a wounded ship
  streams keeps burning — and intensifies — straight through its death spin with
  no visible restart. A `_SEVERITY` table bundles each level's knobs (emit
  interval, count, puff scale) per layer.
- **Duck-typed owner.** Any object exposing `position`, `speed`, `health`,
  `max_health` and (optionally) `is_dying` works, so both ships and subsystems
  carry one; it is registered as a per-frame task and cleaned with its owner.
- **Cheap at scale.** Continuity comes from a few large overlapping puffs rather
  than a dense stream of tiny ones, and the pool's trail layers are short-lived,
  so dozens of ships can trail at once without saturating the shared pool or
  drowning the GPU in transparent overdraw (see `fire_smoke_fx.py`).

## `cockpit_fx.py` — first-person low-health feedback

[`cockpit_fx.py`](../../src/space_flight/fx/cockpit_fx.py)'s `CockpitFX` is the
player-only, display-only counterpart to `DamageFX`: since the exterior smoke/fire
trail is emitted at the hull (i.e. at the camera) it is useless in first person, so
this gives the pilot an in-cockpit read on their own ship. Built by `Player` **only
when not headless** and cleaned with the player; everything keys off the same two
health tiers as the exterior FX (`health_tier()` reuses `damage_fx`'s 2/3 and 1/3
thresholds).

- **Damage vignette + directional hit flash** share one fullscreen `render2d`
  `CardMaker` quad with the `cockpit_overlay.{vert,frag}` shader (on the 2D layer, so
  it composites regardless of the conditional `GraphicsManager` post pass). `update()`
  drives the red vignette from the tier (pulsing when critical); `flash(color,
  screen_dir)` triggers a transient bloom tinted the laser's colour, biased toward the
  incoming direction — wired from the player branch of `munition_into_destructible`
  ([collisions.py](../../src/space_flight/game/collisions.py)) via `Player.on_laser_hit`,
  whose direction math (`screen_direction_from_incoming`) projects the shot's world
  velocity onto the pawn's `right`/`up` basis.
- **Electrical sparks** reuse the hit-spark pool and shader directly
  (`game.spark_fx_pool`, `spark.{vert,frag}`) — no separate cockpit pool — with a small
  cockpit `SparkPreset` and `spawn(..., size_scale=, speed_scale=)` so the close-up
  sparks are scaled down against the pool's distance-tuned globals. Each burst fires a
  random subset of the ship's **authored cockpit emitters** — 3D positions + normals in
  the ship body frame, loaded from `cockpit/spark_emitters.yaml` via the
  `cockpit_spark_emitters` config key (the three TIE variants share one file under
  `models/ships/tie_common/cockpit/`) — transformed to world through the ship node so
  sparks fly out of fixed cockpit points.
- **Cockpit rattle + engine sputter** are one synchronized effect: `update()` runs a
  random damage-*stutter* scheduler (discrete jolt events at random intervals, more
  frequent/stronger by tier — not a continuous vibration), exposing a single `[0,1]`
  envelope via `sputter_intensity()`. `Player.move_camera` reads it through
  `rattle_offset()`, which fades a fast multi-frequency camera vibration in and out by
  that envelope; `Ship.adjust_engine_pitch` reads the *same* value to cut the interior
  engine play-rate at the same instant. Computing
  it once here keeps the shake and the engine cut in lockstep. `Ship` only sputters when
  its controller carries a `cockpit_fx` (the player), so bots and headless are unaffected.

## `speed_dust_cloud.py` — engine speed feel

[`speed_dust_cloud.py`](../../src/space_flight/fx/speed_dust_cloud.py)'s
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

[`sfx.py`](../../src/space_flight/fx/sfx.py)'s `SFX` wraps Panda3D's
`Audio3DManager` for every non-music sound in the game:

- **Sound pools.** `get_sounds_from_asset_manager()` loads a named pool per
  impact category (player crash short/long, laser-on-hull, laser-on-shield,
  distant target hit, terrain hit) via the asset manager, which handles
  randomised pitch and playback slot reuse (`get_sound`/`release_sound`).
  The actual pooled loading is `build_sound_pool` in
  [`global_architecture/asset_pools.py`](../../src/space_flight/global_architecture/asset_pools.py);
  `SFX.build_sound_pool()` is an unused legacy helper.
- **Distance-aware playback.** `distant_impact_hit()` (used for AI-vs-AI or
  distant impacts, not directly on the player) computes volume from an
  inverse-square falloff against a reference distance and drops the sound
  entirely beyond `MAX_SOUND_DISTANCE_M`, so far-off fights don't spam audio.
- **Positioned one-shots.** `laser_impact_hit_on_player`, `player_crash` and
  `cannon_fire` each attach a sound to either an ad-hoc dummy node (placed at
  the relative hit point and auto-removed after `SFX_MAX_SOUND_DURATION_S`)
  or an existing node (a firing cannon), so Panda3D's 3D audio handles
  panning/attenuation/Doppler automatically. Scheduled sounds are released
  back to their pool after the same fixed duration via
  `game.delayed_methods.do_method_later`, so pools don't leak playing-sound
  references — `player_crash` schedules a release for each of the up to
  three sounds it plays (terrain hit, short crash, long crash).
- **Placeholders.** `tractor_beam_grab`/`tractor_beam_release` are stubs that
  only log for now — the tractor beam mechanic works without a dedicated
  audio cue yet (see [subsystems.md](subsystems.md)).
- `update_task` drives `Audio3DManager.update()` once per frame via Panda3D's
  own task manager (not `game.method_lists` like everything else in this
  package), since it must run regardless of which actors are alive.

## Where things live

All of it lives directly under
[`src/space_flight/fx/`](../../src/space_flight/fx/): the shared particle
framework in `__init__.py`, the fire/smoke pool in `fire_smoke_fx.py`, the
damage/death trail in `damage_fx.py`, the cockpit low-health feedback in
`cockpit_fx.py`, the sparks in `spark_fx.py`, the non-particle dust cloud in
`speed_dust_cloud.py`, and sound in `sfx.py`. The auto-generated
[code reference](apidocs/index.rst) has the full per-class API.
