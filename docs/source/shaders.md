# Shaders

`datafiles/shaders/` holds every GLSL source the game loads directly (as
opposed to shaders baked into imported models). Each file pairs with the
Python code that compiles and drives it via uniforms — this page is the
guided tour of what each shader does and where its Python counterpart lives,
since the shaders themselves have no docstring-based reference.

All of it lives in
[`src/space_flight/datafiles/shaders/`](../src/space_flight/datafiles/shaders/).

## Mental model

- Every shader is `#version 140` GLSL, loaded via `Shader.load`/`Shader.make`
  from Python and driven entirely by uniforms set each frame — there is no
  runtime shader-side state beyond what's passed in.
- Several fragment shaders share the same small noise/tonemap building
  blocks (`hash`/`smoothNoise`/`fbmNoise`), copy-pasted rather than shared
  via `#include`, since Panda3D's shader loader has no include mechanism
  here — comments in the ocean/shield shaders explicitly note where a field
  is "identical to" its counterpart in the other file.
- Shaders that render into an offscreen buffer and composite it back
  (render-scale/AA, the ocean reflection, hyperspace) all handle the same
  power-of-two texture-padding correction: sample only the `texScale`
  fraction of the texture, since Panda3D may pad an offscreen render target
  up to the next power of two.

## Hyperspace loading-screen shaders

Driven by
[`game/hyperspace_loading_state.py`](../src/space_flight/game/hyperspace_loading_state.py)
(see [docs/game.md](game.md)) — three fullscreen fragment shaders for the
three phases of the jump animation, sharing one passthrough vertex shader:

- **[`hyperspace.vert`](../src/space_flight/datafiles/shaders/hyperspace.vert)**
  is a bare position-only passthrough shared by all three fragment shaders.
- **[`hyperspace_into.frag`](../src/space_flight/datafiles/shaders/hyperspace_into.frag)**
  ("entering hyperspace") draws star streak trails converging into a central
  lens flare that grows and whites out the screen, adapted from a public
  ShaderToy source (credited in the header comment). Trails are procedural
  per-"slice" line segments (`sdLine`) with randomised offset/speed/length
  seeded per slice index (`rand`), eased in over `iIntoDuration` (fed from
  Python so the shader's whiteout timing always matches the Python-side
  phase duration — "one source of truth" per the code comment). Time is
  **clamped**, not wrapped, once the flare fills the screen, so the white
  frame holds steady for the cross-fade into the tunnel rather than
  restarting the trail animation.
- **[`hyperspace_inside.frag`](../src/space_flight/datafiles/shaders/hyperspace_inside.frag)**
  is the seamlessly looping warp-tunnel effect held while the level builds
  in the background, adapted from another ShaderToy source. Its core is a
  3D simplex-noise fractal Brownian motion (`loopFbm`) sampled around a
  circle in depth-phase space rather than tiled with a hard `mod()` wrap —
  the comment explains this specifically avoids the visible seam a naive
  tiling would produce, since every fBm octave then traverses the circle an
  integer number of times over one loop period (`T_LOOP`).
- **[`hyperspace_outof.frag`](../src/space_flight/datafiles/shaders/hyperspace_outof.frag)**
  ("dropping out of hyperspace") is the reverse of `hyperspace_into.frag` —
  streak trails collapsing from full brightness into the revealed level,
  fading from an initial whiteout.

## Render-scale / anti-aliasing pipeline shaders

Driven by
[`GraphicsManager.begin_scene_render`](../src/space_flight/global_architecture/graphics_manager.py)
(see [docs/global_architecture.md](global_architecture.md)) to composite the
(possibly downscaled) offscreen 3D render back onto the window:

- **[`composite.vert`](../src/space_flight/datafiles/shaders/composite.vert)**
  is the shared fullscreen-quad passthrough vertex shader for both
  post-composite shaders below.
- **[`blit.frag`](../src/space_flight/datafiles/shaders/blit.frag)** is the
  plain path when FXAA is off: sample the scene texture (scaled by
  `texScale` to stay inside its non-padded region) and let the GPU's own
  texture filtering handle any upscaling.
- **[`fxaa.frag`](../src/space_flight/datafiles/shaders/fxaa.frag)** is a
  simplified port of Timothy Lottes' FXAA3 algorithm, run as the
  alternative post-process pass when FXAA is enabled: it estimates a local
  edge direction from the luma of the four diagonal neighbours, samples
  twice along that direction, and blends between a 2-tap and 4-tap result
  depending on whether the 2-tap sample falls outside the local luma range
  (`lumaMin`/`lumaMax`) — a lightweight edge-aware blur.

## Ocean shaders

Driven by
[`scenes/ocean.py`](../src/space_flight/scenes/ocean.py) (see
[docs/scenes.md](scenes.md)):

- **[`ocean.vert`](../src/space_flight/datafiles/shaders/ocean.vert)** is
  mostly a passthrough, but implements the optional `uGeometricSwell`
  prototype mode: it displaces the vertex vertically by sampling the same
  `swellField` height function the fragment shader also samples (the
  comment is explicit that the two copies must stay identical, since the
  geometry and the shading normal must derive from one source of truth),
  tapered to zero near the dense grid's edge so the displaced centre joins
  the flat outer border seamlessly. The reflection lookup coordinate is
  computed from the *undisplaced* flat-plane position, so surface
  displacement never skews which reflection texel gets sampled.
- **[`ocean.frag`](../src/space_flight/datafiles/shaders/ocean.frag)** is
  the most elaborate fragment shader in the game:
  - **Iterative wave field.** `getwaves`/`waveGradient` accumulate multiple
    Gerstner-like wave octaves (`wavedx`) along precomputed per-iteration
    directions (`iWaveDirs`, uploaded from Python — see
    [docs/scenes.md](scenes.md)'s `compute_wave_dirs`). `waveGradient`
    computes the height-field slope analytically in one pass, rather than
    the finite-difference three-sample approach a naive normal calculation
    would use, since each wave term's derivative is known in closed form.
  - **Level-of-detail by angle and distance.** `detailAngle` (from the
    view-ray's elevation) and `distFade` (from camera distance) both fade
    wave detail toward a flat mirror — angle-based specifically so the look
    stays consistent regardless of camera altitude, not just raw distance.
    Iteration counts (`normalIter`, `warpIter`) shrink with both factors so
    distant/grazing water costs less per pixel.
  - **Swell + frequency modulation.** A separate large-scale `swellField`
    (two drifting value-noise layers multiplied together, so the pattern
    interferes and changes shape rather than rigidly scrolling) tilts the
    normal unconditionally (no distance fade — swells are visible from far
    away) and also perturbs the small-wave phase (`fmPhase`) so the dominant
    octave's tiling pattern drifts instead of repeating identically.
  - **Reflection sampling.** The reflection UV is recomputed per-fragment
    from the flat surface position (not interpolated from vertex clip
    space), explicitly to stay correct when the geometric-swell mode
    displaces vertices — interpolating a vertex-computed value would skew
    the projective divide per triangle. The ripple perturbation is clamped
    to the buffer's actual rendered region (`uReflUVScale`) so it can never
    sample the power-of-two padding beyond it.
  - **ACES tonemapping** (`aces_tonemap`) is applied as the final step to
    the fresnel-blended reflection/scatter colour.
  - Nine numbered `uDebugMode` branches (normal, reflection UV, fresnel,
    world-position grid, clamp indicator, raw reflection, pre-tonemap
    clipping, FM phase field) let each intermediate quantity be visualised
    directly for debugging.

## Shield shaders

Driven by
[`actors/capital_ship/shield_model.py`](../src/space_flight/actors/capital_ship/shield_model.py)
(see [docs/subsystems.md](subsystems.md) and [docs/actors.md](actors.md)):

- **[`shield.vert`](../src/space_flight/datafiles/shaders/shield.vert)** is
  a passthrough that additionally forwards both *object-space* and
  *world-space* position/normal — object-space because the surface pattern
  and the death-retraction sink points are anchored to the hull mesh (so
  they stay fixed as the ship rotates), world-space because the fresnel rim
  glow needs the true view direction.
- **[`shield.frag`](../src/space_flight/datafiles/shaders/shield.frag)**
  layers a "living" bubble look with an optional death/appearance animation
  on top:
  - **Living look.** A triplanar value-noise field (`surfacePattern`,
    blended across the three world-normal-weighted planar projections so
    there are no seams or poles regardless of mesh topology) drives a slow
    morphing interior pattern (`smoothField`, itself domain-warped by a
    second noise layer for organic drift), combined with a fresnel rim
    glow, a health-driven colour ramp (blue → violet → pink as health drops
    to zero), and per-impact glow flashes (`impactGlow`, one radial falloff
    per recent hit in `uImpacts`, aged out after `uImpactLife`).
  - **Death/appearance animation** ("fluid retracting into random points",
    per the file's own header comment) is a pure per-fragment mask over the
    living shader, driven by a single `uDeath` parameter Python ramps 0→1 to
    die or 1→0 to reappear — no mesh changes needed. A handful of random
    `uSinks` points on the surface each have a shrinking coverage radius;
    material only renders where it's within some sink's radius
    (`nearestSink`), so as the radius shrinks to zero the "fluid" appears to
    drain into the sink points. The coverage boundary is roughened by
    animated noise (`isoNoise`) so it breaks into irregular blobs rather
    than shrinking as clean circles, and carries a bright `bead` highlight
    riding the retracting edge to read as a liquid meniscus. This is the
    GPU-side half of `Shield`'s death/appearance state machine (see
    [docs/subsystems.md](subsystems.md)) — the Python side only drives
    `uDeath` and the sink points; every visual detail of the collapse lives
    here.

## Explosion particle shaders

Driven by the GPU particle system in
[`fx/explosion_fx.py`](../src/space_flight/fx/explosion_fx.py) /
[`fx/__init__.py`](../src/space_flight/fx/__init__.py) (see [docs/fx.md](fx.md)).
One shader pair, shared by both the fire and smoke buffers (they differ only
by the `uFadein` uniform):

- **[`explosion.vert`](../src/space_flight/datafiles/shaders/explosion.vert)**
  reconstructs each billboard particle's current state on the GPU from its
  spawn-time parameters — read straight from dedicated vertex columns
  (`velocity`, `size`, `spin`, `spawn_time`, `lifetime`, `tile_rect`), with no
  bit-packing to undo. It derives age from `uTime - spawn_time`, moves the
  particle linearly, grows the billboard over its life, spins the quad,
  projects the corner onto the camera's right/up axes to face the screen, and
  outputs a combined fade-out/fade-in/alive alpha. No vertex data is touched
  after spawn, so hundreds of live particles cost only the three per-frame
  uniforms (`uTime`, `uCamRight`, `uCamUp`).
- **[`explosion.frag`](../src/space_flight/datafiles/shaders/explosion.frag)**
  samples the sprite atlas for this particle's tile and multiplies by the
  vertex-computed alpha (early-discarding fully transparent fragments). The
  tile's UV rect arrives per-particle as the `vTileRect` varying, so — unlike
  a uniform-array-of-rects approach — the fragment shader needs neither a
  tile-count cap nor dynamic array indexing to pick the right sprite.

## Spark particle shaders

Driven by the GPU particle system in
[`fx/spark_fx.py`](../src/space_flight/fx/spark_fx.py) (see [docs/fx.md](fx.md))
for laser hit sparks. One shader pair, shared by every burst regardless of
preset (metal / ice / magic):

- **[`spark.vert`](../src/space_flight/datafiles/shaders/spark.vert)**
  reconstructs each spark from its spawn-time vertex columns (`velocity`,
  `size`, `spawn_time`, `lifetime`, `gravity`, `spark_color`). Unlike the
  explosion, it follows a **ballistic** path — linear velocity plus a
  per-particle downward `gravity` — and shrinks the billboard as it ages.
  Colour and gravity are per-particle (not uniforms) so bursts of different
  hit types stay independent in one buffer.
- **[`spark.frag`](../src/space_flight/datafiles/shaders/spark.frag)** renders
  each quad as a round glowing spark: an SDF circle discards the corners, a
  soft glow plus a hard core build the shape (floored by the `spark.png` red
  channel so it still reads if the texture is flat), and the per-spark
  `vColor` tints it. Additive-blended for a bright glow.

## Laser bolt shaders

Driven by `LaserShot` in
[`actors/laser_cannon.py`](../src/space_flight/actors/laser_cannon.py) (see
[docs/actors.md](actors.md)). Each bolt is a single camera-facing quad that the
fragment shader turns into a glowing 3D capsule — an *analytic capsule
impostor*. There is no mesh and no surface, so it reads as a solid glowing tube
from any angle, including straight down its own axis (as when the player fires
forward), where it shows as a bright disc rather than a flat sliver.

- **[`laser.vert`](../src/space_flight/datafiles/shaders/laser.vert)** billboards
  the card to face the camera. It works in the projectile node's **model space**
  (the `Munition` base translates the node every frame and orients its local +Z
  along the bolt's travel, which is also where the swept collision segment
  lives), so the core is the fixed model-space segment `[uA, uB]` along local Z.
  The camera position comes from column 3 of `p3d_ViewMatrixInverse` — the eye
  of *whatever* camera is drawing the current pass — so bolts are correct in the
  main view, the rear-view mirror and the ocean reflection alike, with no
  per-frame CPU work and no shared uniforms. (Column 3 is the world position,
  unambiguous in any convention; the basis columns are deliberately avoided.)
- **[`laser.frag`](../src/space_flight/datafiles/shaders/laser.frag)** casts a
  ray from the eye through each pixel and measures its distance to the core
  segment (a signed-distance field): distance → a white-hot core plus a soft
  coloured (`uColor`) halo. Correct at every angle — a long streak side-on, a
  round disc head-on. Additive-blended with depth-write off; it writes
  `gl_FragDepth` from the point nearest the core so opaque geometry occludes
  bolts correctly while they never occlude each other or translucent geometry.

## Where things live

Every shader in this page lives directly under
[`src/space_flight/datafiles/shaders/`](../src/space_flight/datafiles/shaders/):
the hyperspace overlay's three phase shaders plus shared vertex passthrough,
the render-scale/AA composite pair, the ocean's vertex/fragment pair, the
shield's vertex/fragment pair, the laser bolt's vertex/fragment pair, and the
explosion and spark particle vertex/fragment pairs. Each is loaded and driven by
the Python module named in
its section above — there is no separate shader-only reference, since GLSL
isn't covered by the docstring-generated [code reference](docs/).
