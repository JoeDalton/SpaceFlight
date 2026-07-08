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

## Where things live

Every shader in this page lives directly under
[`src/space_flight/datafiles/shaders/`](../src/space_flight/datafiles/shaders/):
the hyperspace overlay's three phase shaders plus shared vertex passthrough,
the render-scale/AA composite pair, the ocean's vertex/fragment pair, and the
shield's vertex/fragment pair. Each is loaded and driven by the Python module
named in its section above — there is no separate shader-only reference,
since GLSL isn't covered by the docstring-generated [code reference](docs/).
