# FX

Everything visually or aurally reactive but not part of core gameplay logic —
explosions, engine dust, impact sounds — lives in
[`src/space_flight/fx/`](../src/space_flight/fx/). This page is the guided
tour; the per-class API is generated from the docstrings in the
[code reference](docs/).

## Mental model

- Particle effects (explosions, and eventually hit sparks) are **GPU-driven**:
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
(worth reading directly for the exact packing bit-layout).

- **`make_geom_vertex_format()` / `FMT`** — one interleaved vertex format
  shared by every particle buffer: `vertex` (spawn position), `color.xyz`
  (velocity) + `color.w` (an effect-specific packed payload), `texcoord.xy`
  (billboard corner selector) + `texcoord.z` (spawn time) + `texcoord.w`
  (a second effect-specific packed payload).
- **`ParticleBuffer`** — owns one `GeomNode` of `POOL_SIZE` (512) billboard
  quads, plus the shader and render state (additive or alpha blending,
  no depth-write, always-visible bounds so it skips frustum culling cheaply).
  Slots are tracked CPU-side as `(spawn_time, duration)` pairs so
  `alloc_slot()` can find or reclaim a free slot without reading back GPU
  memory; `write_slot()` writes one quad's four identical vertices (only the
  `corner.xy` selector differs) and reserves its slot for `delay + duration`.
  `update()` runs once per frame per buffer, pushing `uTime`, `uCamRight`,
  `uCamUp` — everything else (position, size, spin, fade) is computed
  entirely on the GPU from those spawn-time values, so a live particle never
  touches the CPU again after `write_slot`.
- **`load_atlas()`** — loads a sprite-atlas PNG plus its companion JSON rect
  descriptor into a `(Texture, rects)` pair, ready to be bound and indexed
  by a shader.

Two packing schemes reuse the same two "spare" floats (`color.w`,
`texcoord.w`) differently per effect — explosion packs two values per float
(size+spin, tile+lifetime) to fit everything in the fixed vertex layout,
while the (currently unimplemented) sparkle effect described in the module
docstring would store size and lifetime raw, unpacked. Only the explosion
side of this design is implemented today (see below); the docstring's mention
of a Sparkle hit-spark effect is a design placeholder, not yet backed by
code.

## `explosion_fx.py` — fire and smoke bursts

[`explosion_fx.py`](../src/space_flight/fx/explosion_fx.py) builds one
concrete effect on top of `ParticleBuffer`:

- **`build_expl_vert()` / `build_expl_frag()`** generate the explosion's GLSL
  source as Python-formatted strings (so `Shader.make` can cache the exact
  text) rather than using runtime `#define`s. The vertex shader unpacks
  `size_spin`/`tile_life` back out of `color.w`/`texcoord.w`, computes particle
  age from `uTime - spawn_time`, and derives billboard size from a
  caller-supplied GLSL size-curve expression (e.g. `"base_size * (0.3 + frac
  * 0.7)"` — grows over the particle's life) plus a fade-in ramp. The
  fragment shader picks the right atlas tile via an `if/else` chain — GLSL
  140 forbids dynamically indexing a uniform array, so each atlas rect is
  its own uniform (`uTileRect0`, `uTileRect1`, …).
- **`_ExplosionBuffer`** is a thin `ParticleBuffer` subclass: it uploads the
  atlas rects as uniforms once at construction, and `spawn_particle()` does
  the size/spin and tile/lifetime packing before calling `write_slot`.
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
