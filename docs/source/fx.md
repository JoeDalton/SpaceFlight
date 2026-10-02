# FX

Everything visually or aurally reactive but not core gameplay — explosions,
sparks, damage trails, cockpit feedback, speed dust, sound — lives in
[`src/space_flight/fx/`](../../src/space_flight/fx/). This page is the guided
tour; the per-class API is in the [code reference](apidocs/index.rst).

## Mental model

- Particle effects (fire/smoke and hit sparks) are **GPU-driven**: a particle
  is written once at spawn into a pre-allocated vertex buffer, and the vertex
  shader reconstructs its position/size/alpha every frame from those spawn-time
  values. The CPU only updates three uniforms per buffer per frame (`uTime`,
  `uCamRight`, `uCamUp`), so hundreds of live particles are cheap.
- The speed dust cloud is ordinary Panda3D nodes moved by a per-frame Python
  task — fine at its much lower particle count.
- Sound (`SFX`) wraps Panda3D's `Audio3DManager`: sound pools per impact type,
  attached to nodes so 3D positioning and Doppler come for free.

## `fx/__init__.py` — the shared GPU particle system

[`fx/__init__.py`](../../src/space_flight/fx/__init__.py) defines the vertex
format and base class every particle effect builds on; its module docstring
has the exact vertex-column layout and the render-state gotchas.

- **`make_particle_format(columns)`** builds one interleaved format **per
  effect**: the shared billboard columns (`vertex`, `corner`, `spawn_time`)
  plus the effect's own columns (explosion: `velocity`, `size`, `spin`,
  `lifetime`, `tile_rect`; spark: `velocity`, `size`, `lifetime`, `gravity`,
  `spark_color`). GLSL reads each custom column by name — no bit-packing, no
  repurposed `color`/`texcoord` columns.
- **`ParticleBuffer`** owns one `GeomNode` of `POOL_SIZE` (512) billboard
  quads plus the shader and render state (additive or alpha blending, no
  depth write, omni bounds so it skips frustum culling). Slots are tracked
  CPU-side as `(write_time, delay + duration)` pairs, so `alloc_slot()` finds
  a free one without GPU read-back. `write_slot()` writes a quad's four
  identical vertices (only `corner` differs), taking each effect column as a
  keyword argument; `update()` (registered in `game.method_lists`) pushes the
  three uniforms.
- **`load_atlas()`** loads a sprite-atlas PNG and its JSON rect descriptor
  into a `(Texture, rects)` pair. The atlases are built by
  `scripts/build_particle_atlas.py`.

## `fire_smoke_fx.py` — fire and smoke

[`fire_smoke_fx.py`](../../src/space_flight/fx/fire_smoke_fx.py) is one shared
fire/smoke billboard system on top of `ParticleBuffer`.

- **`_FireSmokeBuffer`** applies the shared
  [`explosion.{vert,frag}`](shaders.md#explosion-particle-shaders) shader
  (loaded once by `_explosion_shader()`), sets its layer's `uFadein`, and
  `spawn_particle()` resolves a random atlas tile index to its UV rect for the
  `tile_rect` column. Fire and smoke differ only by atlas and `uFadein`.
- **`FireSmokePool`** (`game.fire_smoke_pool`) owns the fire and smoke buffers
  and exposes three emitters that share them (and their pool budget):
  - **`burst()`** — a one-shot explosion (ship/subsystem death, e.g.
    `Bot.play_death`, see [actors.md](actors.md)). Smoke trails the fire by
    `SMOKE_DELAY` with no CPU timer: it is written with a future `spawn_time`
    (`write_slot(spawn_delay=...)`), so the shader treats it as not yet born.
    Only bursts given a surface `normal` fan out in cones (fire wider than
    smoke); death explosions pass none, so particles carry only the inherited
    velocity plus a random positional bias. Sizes, speeds and bias are scaled
    by the caller's `scale`, so fighters and capital ships share the pool.
  - **`hit_burst()`** — the small secondary explosion on laser hits:
    `burst()` along the impact normal with the `HIT_EXPLOSION_*` knobs (few
    billboards, lower speed) so hits stay cheap.
  - **`trail_smoke()` / `trail_fire()`** — one puff of the continuous damage
    trail (`damage_fx.py`). They use short-lived layers (`_TRAIL_SMOKE_LAYER`,
    `_TRAIL_FIRE_LAYER`) so that, emitted every frame by many ships, only a
    handful are alive at once; long-lived trail particles would saturate the
    pool and flood the screen with transparent overdraw.

  All three go through `_emit_layer`, driven by a `_Layer` config carrying
  each layer's cone, ranges, lifetime and delay.

## `spark_fx.py` — laser hit sparks

[`spark_fx.py`](../../src/space_flight/fx/spark_fx.py): a short, bright burst
of round glowing sparks thrown out of a laser impact.

- **`SparkPool`** (`game.spark_fx_pool`, created in `FlightState` beside
  `fire_smoke_pool`) is a `ParticleBuffer` with the
  [`spark.{vert,frag}`](shaders.md#spark-particle-shaders) shader, the
  `spark.png` sprite and additive blending.
  `spawn(position, normal, base_velocity, preset)` emits a cone of sparks
  around the normal, each on a ballistic (gravity-pulled) path, shrinking as
  it ages.
- **`SparkPreset`** (`METAL`, `ICE`, `ROCK`, `MAGIC`) bundles two colours,
  count, speed, cone spread, gravity, lifetime and size. Colour and gravity
  are written **per particle** so bursts of different presets coexist in the
  one buffer; each spark's colour is premixed CPU-side from its random size
  (the largest get `color_inner`). `SPARK_SIZE_SCALE`, `SPARK_SPEED_SCALE`
  and `SPARK_JET_ANGLE_SCALE` scale every preset at once.
- Wiring, in the laser handlers of
  [`collisions.py`](../../src/space_flight/game/collisions.py):
  - bot hits: `ICE` if the target's shield was still up, else `METAL`;
  - capital-ship shield-bubble hits: `ICE`, on top of the shield's own flash;
  - terrain hits: `_TERRAIN_SPARK_PRESET[terrain.material]` (`"water"` →
    `ICE`, `"rock"` → `ROCK`, `"metal"` → `METAL`; `ROCK` if absent).

  Bot and shield bursts inherit the target's velocity; terrain bursts get
  zero. On a fraction of bot hits (`HIT_EXPLOSION_CHANCE` in `collisions.py`,
  1/3) `FireSmokePool.hit_burst()` is also spawned at the same point, normal
  and velocity.

## `damage_fx.py` — damage & death smoke/fire trail

[`damage_fx.py`](../../src/space_flight/fx/damage_fx.py)'s `DamageFX` is a
per-actor smoke-and-fire trail emitted into the shared `FireSmokePool` via
`trail_smoke()` / `trail_fire()`; it owns no geometry.

- **Severity-driven.** Each frame `update()` derives a severity (0 intact,
  1 smoking at ≤ 2/3 health, 2 on fire at ≤ 1/3, 3 while `is_dying`) from the
  owner's `health / max_health`. Because it is re-derived every frame, a
  wounded ship's trail keeps burning — and intensifies — through its death
  spin with no restart. `_SEVERITY` holds each level's emit interval, count
  and puff scale.
- **Duck-typed owner.** Anything with `position`, `speed`, `health`,
  `max_health` and optionally `is_dying` works; ships and subsystems each
  carry one, registered as a per-frame task and cleaned with the owner.
- **Cheap at scale.** Continuity comes from a few large overlapping puffs, and
  the trail layers are short-lived, so dozens of ships can trail at once.

## `cockpit_fx.py` — first-person low-health feedback

[`cockpit_fx.py`](../../src/space_flight/fx/cockpit_fx.py)'s `CockpitFX` is the
player-only, display-only counterpart to `DamageFX`, whose trail is emitted at
the hull, i.e. at the camera, and so is useless in first person. `Player`
builds it **only when not headless**. Everything keys off two health tiers
(`health_tier()`, reusing `damage_fx`'s 2/3 and 1/3 thresholds).

- **Damage vignette + directional hit flash** share one fullscreen `render2d`
  quad with the [`cockpit_overlay`](shaders.md#cockpit-damage-overlay-shaders)
  shader (on the 2D layer, so it composites whether or not the
  `GraphicsManager` post pass is active). `update()` drives the vignette from
  the tier (pulsing when critical). `flash(color, screen_dir)` is called by
  `Player.on_laser_hit` from `munition_into_destructible`
  ([collisions.py](../../src/space_flight/game/collisions.py)); its direction
  comes from `screen_direction_from_incoming`, which projects the shot's world
  velocity onto the pawn's `right`/`up` axes.
- **Electrical sparks** reuse `game.spark_fx_pool` with a small cockpit
  `SparkPreset` and `spawn(..., size_scale=, speed_scale=)` to shrink them
  against the pool's distance-tuned globals. Each burst fires a random subset
  of the ship's authored emitters (body-frame positions + normals from the
  YAML file named by the `cockpit_spark_emitters` config key; the three TIE
  variants share `models/ships/tie_common/cockpit/spark_emitters.yaml`),
  transformed to world through the ship node.
- **Cockpit rattle + engine sputter** are one effect: `update()` schedules
  random discrete stutter events (more frequent and stronger when critical)
  and exposes their `[0, 1]` envelope via `sputter_intensity()`.
  `Player.move_camera` adds `rattle_offset()`, a fast multi-frequency
  vibration scaled by that envelope, and `Ship.adjust_engine_pitch` reads the
  same value to cut the engine play rate, so shake and engine cut stay in
  lockstep. Only a controller with a `cockpit_fx` (the player) sputters.

## `speed_dust_cloud.py` — engine speed feel

[`speed_dust_cloud.py`](../../src/space_flight/fx/speed_dust_cloud.py)'s
`SpeedDustCloud` is a fixed pool of small `setBillboardPointEye()` dust cards
parented to the player's ship, in a box ahead of it. `dust_update` moves each
card backward at the player's speed and recycles it ahead
(`reset_particle`) once it passes behind; the cloud's opacity scales with
speed (`MIN_DUST_ALPHA` → `MAX_DUST_ALPHA`). With `defer_build=True`,
`build()` is a generator (`yield from`) that spreads node creation across
frames.

## `sfx.py` — 3D sound effects

[`sfx.py`](../../src/space_flight/fx/sfx.py)'s `SFX` handles every non-music
sound:

- **Sound pools.** `get_sounds_from_asset_manager()` loads one pool per
  category (player crash short/long, laser on player hull/shield, distant
  target hit, terrain hit). The pools come from `build_sound_pool` in
  [`global_architecture/asset_pools.py`](../../src/space_flight/global_architecture/asset_pools.py)
  and handle random pitch and slot reuse (`get_sound`/`release_sound`);
  `SFX.build_sound_pool()` is an unused legacy helper.
- **Distant impacts.** `distant_impact_hit()` (hits not on the player) uses an
  inverse-square falloff from `SOUND_VOLUME_REFERENCE_DISTANCE_M`, drops the
  sound beyond `MAX_SOUND_DISTANCE_M`, and multiplies by the per-surface
  `TARGET_HIT_SOUND_MULTIPLIER` / `TERRAIN_HIT_SOUND_MULTIPLIER` and by
  `PLAYER_DISTANT_IMPACT_VOLUME` or `NPC_DISTANT_IMPACT_VOLUME`.
  `CollisionSystem`'s three call sites (target, terrain, shield) pass
  `is_player=munition.origin_ship_id == game.player.pawn.id`.
- **Positioned one-shots.** `laser_impact_hit_on_player` and `player_crash`
  attach their sounds to a dummy node at the relative hit point (removed after
  `SFX_MAX_SOUND_DURATION_S`); `cannon_fire` attaches to the firing cannon's
  node, with `PLAYER_CANNON_FIRE_VOLUME` or `NPC_CANNON_FIRE_VOLUME` chosen by
  `is_player` from `LaserCannon.fire()`. Every sound is released to its pool
  after `SFX_MAX_SOUND_DURATION_S` via `game.delayed_methods.do_method_later`
  (`player_crash` releases each of its up to three sounds).
- **Place before playing.** `attach_sound()` also sets the sound's position
  immediately: `Audio3DManager` only moves attached sounds on its next update,
  so a sound played in between would start at its previous position or at the
  render origin — which is on the listener (see
  [the floating render origin](game.md#the-floating-render-origin)), giving a
  loud blip.
- **Placeholders.** `tractor_beam_grab`/`tractor_beam_release` only log (see
  [subsystems.md](subsystems.md)).
- **Update.** `update_task` calls `Audio3DManager.update()` from Panda3D's
  task manager (not `game.method_lists`), since it must run whatever actors are
  alive. The manager also registers its own `Audio3DManager-updateTask`
  (sort 51, after `igLoop`), so the update currently runs twice per frame.
- **Doppler from physics.** `PhysicsAudio3DManager` takes velocities from
  physics: Panda3D's stock velocities are `getPosDelta(render) / dt`, which is
  zero for nodes moved with plain `setPos` — every node in the game.
  `attach_sound(sound, node, velocity_source=…)` gives each sound a weakly
  referenced *velocity source* (any object with a world-frame `speed`), read
  at every update:
  - engine sounds: their `Ship` / `CapitalShip`;
  - cannon shots: `LaserCannon.parent` (a fighter, or a turret, whose `speed`
    is its host ship's);
  - hits on and crashes of the player, and the listener (set by
    `Player.initialize_camera`, cleared in `Player.clean`): the player's
    pawn, so player-centred sounds carry no shift.

  A destroyed source reads as zero velocity. Velocities stay world-frame while
  positions are render-relative: `render` only translates with the player,
  and OpenAL's Doppler needs velocities relative to the medium.

  `DISTANCE_FACTOR` is 1: Panda3D's OpenAL backend sets the speed of sound to
  `343.3 × distance_factor` units/s and the game's unit is the metre (it does
  not change attenuation). `DOPPLER_FACTOR` 0.5 halves the shift at low speed;
  since OpenAL scales the velocities, not the shift, it cuts more than half
  when approaching and less when receding. A 1 kHz source at 170 m/s gives
  1329 Hz approaching (1981 Hz at factor 1) and 801 Hz receding (669 Hz).
  OpenAL goes silent as a source's closing speed × Doppler factor nears the
  speed of sound (686 m/s at 0.5), which nothing in the game reaches.

## Where things live

One module per section above, all under
[`src/space_flight/fx/`](../../src/space_flight/fx/); the shaders they drive
are described in [shaders.md](shaders.md).
