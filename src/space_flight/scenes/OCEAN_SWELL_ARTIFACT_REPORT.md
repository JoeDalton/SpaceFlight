# Ocean Geometric-Swell Artifacts — Investigation Report

**Status: NOT SOLVED.** The artifacts are still present in the demo. The fixes
implemented this session help when the camera is *above* the swell crests but
**introduce a worse, hard-edged artifact at low altitude** (camera among/below
the crests), which is exactly the demo's default view (`Z=3`).

This document records the diagnosis, every approach tried, the real results, the
critical methodology mistake that produced false "clean" results, and
recommended next directions. Evidence montages are in `ocean_debug/`.

---

## 1. Symptoms (the bug)

- Dark patches at low exposure / white patches when overexposed, concentrated on
  the **camera-facing slopes of the swell**, near the horizon band.
- Present at **all altitudes** — raising the camera pushes the patch band out
  toward the horizon but does not remove it (angular/grazing effect).
- **Vanish entirely when `geometric_swell` is off.** Disabling only the small
  waves (`uWaveOff=1`) keeps them → not the small-wave field.

The flat ocean (single quad, `geometric_swell=False`) is the only configuration
that is reliably clean.

---

## 2. Diagnosis — what was actually established

There are **two independent mechanisms**, both of which require the vertex
displacement (so they read as one bug and both vanish when the swell geometry is
off):

### 2a. Reflection slide — *genuinely fixed*
The fragment shader shaded the displaced surface but sampled the planar
reflection at the **flat footprint** (`vWorldPos.xy`, z=0) while the geometry was
drawn displaced. Because planar reflection is only exact on the mirror plane, the
reflection slid across the high-contrast horizon as crests rose → big dark/bright
reflected patches.

- Confirmed with debug mode 6 (raw reflected): patches present; debug mode 5
  showed it was **not** the UV edge-clamp.
- Fix: cast the true view ray back to `z=0` (`P*`) and project that on-plane
  point through the reflection MVP. Confirmed clean in `reflected` mode at both
  buffer resolutions. **Evidence: `ocean_debug/exp1.png`, `exp6.png`.**
- This fix is sound *at altitude* and is the one unambiguous win.

### 2b. Grazing normal aliasing — *not solved*
Near grazing, the displaced surface's per-pixel **world footprint balloons and
folds** (perspective foreshortening of the displaced geometry). The swell normal
is computed analytically as the gradient of `swellField(worldPos)`, so it
**aliases/terraces** where the footprint changes fast. `fresnel =
pow(1-NdotV,5)` then amplifies tiny normal tilts into the dark streaks.

The flat ocean avoids this because (1) it is a single quad → the footprint is
smooth everywhere, and (2) `detailAngle` flattens the normal at grazing. On the
displaced surface, `detailAngle` is keyed on **view angle**, which does not catch
the foreshortening, so the flatten misses it.

Ruled out as the cause (each tested):
- **Mesh density** — 256 vs 1024 subdivisions look nearly identical, so it is
  *not* triangle faceting. **Evidence: `ocean_debug/exp8.png`.**
- **Reflection buffer resolution** — `refl_scale` 0.5 vs 2.0 unchanged.
- **MSAA** — no effect on the shading patches.
- **Ripple alone**, **view-vector source** — no effect.

**Evidence: `ocean_debug/exp3.png`** (fresnel terraced, normal banded, worldgrid
showing the fold) and **`exp7.png` / `exp8.png`**.

---

## 3. Everything tried, and the real outcome

| Approach | Shader knob | Result |
|---|---|---|
| Reflection ray-cast to z=0 | `uReflRayToPlane` | Fixes the reflection slide **at altitude**. Sound. |
| View vector from displaced surface | `uViewFromSurface` | No effect. **Reverted/removed.** |
| Footprint normal anti-aliasing | `uAANormal`, `uAALo/uAAHi` | Partially reduces the normal-aliasing patches; needs aggressive thresholds that flatten the near swell. Never fully clean. |
| Shade-as-flat (sample all shading at `P*`) | `uShadeFromPlane` | At altitude: shading ≈ flat ocean, **pixel-clean** (`exp_r.png`). At low altitude: **introduces a hard seam — worse than the original.** |
| Mesh density / MSAA / reflection resolution | (capture only) | Ruled out as primary causes. |

---

## 4. The critical failure — the demo regime (Z=3)

The demo (`scripts/ocean_demo.py`) starts at `CAM_START_POS = (0,-300,3)`, i.e.
**Z=3**, while `swell_amplitude=20` puts crest tops at **~+15** — the camera sits
*below the crests*, in the troughs.

In that regime the shade-as-flat ray-cast (`P* = ray ∩ z=0`) has **no valid
forward intersection** for the large part of the view that shows crests *above*
the camera (`rd.z ≥ 0`). Those pixels fall back to the displaced-footprint
shading, and the footprint-AA hard-flattens where the footprint blows up. The
boundary between the flat-plane-shaded region and the fallback/flattened region
produces a **blatant hard, stair-stepped wedge** that is worse than fixes-off.

**Evidence: `ocean_debug/exp_z3l.png`** (low-exposure reveal at Z=3):
- Row 1 — flat: clean.
- Row 2 — **all fixes ON: hard stair-stepped wedge** (what you see in the demo).
- Row 3 — fixes OFF: smoother swell silhouette (original behaviour).

Also `ocean_debug/exp_z3.png` (same at normal exposure).

---

## 5. Why my verification was wrong (own this)

Every "clean" capture I reported was taken at **Z=20 or Z=8 — camera above all
crests**. In that regime there is no fallback region, so the seam from §4 never
appeared and shade-as-flat looked perfect. **I never captured the demo's actual
Z=3 view until the end.** The offscreen harness was right; the *test conditions*
were unrepresentative. Any future iteration must be validated at Z≈3 (camera
among the waves) and in motion, not only at altitude.

---

## 6. Root-cause assessment

The combination of **vertex-displaced swell geometry + per-pixel analytic normal
+ planar reflection** is fundamentally fragile:

- At grazing, the displaced footprint foreshortens → the analytic normal (an
  independent field, not derived from the actual mesh) aliases. Geometry and
  shading-normal disagree.
- "Shade as a flat plane" only has a well-defined answer when a z=0 footprint
  exists for every pixel — i.e. **camera strictly above the whole surface**. Near
  or below crest height it breaks, and the breakage is in-frame and ugly.

In short: the current architecture cannot be patched into correctness for
low-altitude views with these tools.

---

## 7. Current state of the code (⚠ makes the demo worse at Z=3)

Changed files:
- `src/space_flight/datafiles/shaders/ocean.vert` — added `vSurfacePos` varying
  (the actual displaced world position).
- `src/space_flight/datafiles/shaders/ocean.frag` — computes `planeXY` (`P*`),
  `shadeXY`, `reflXY`; routes shading/reflection through them; toggles
  `uReflRayToPlane`, `uShadeFromPlane`, `uAANormal` (+ `uAALo/uAAHi`); added
  debug modes 8 (shade-footprint grid) and 9 (footprint magnitude). Removed the
  dead `uViewFromSurface`.
- `src/space_flight/scenes/ocean.py` — the three toggles default **on**; restored
  `uWaveOff=0`, `uExposure=2`.

**Immediate recommendation:** since the shipping defaults make Z=3 worse, either
- set `uShadeFromPlane=0` and `uAANormal=0` (keep only `uReflRayToPlane`), or
- revert the geometric-swell shading changes entirely, or
- run with `geometric_swell=False` (flat ocean — no artifacts) until a real
  approach is chosen.

A clean `git diff`/revert of this branch's shader+ocean.py changes is a
reasonable reset point.

---

## 8. Recommended next directions

1. **Decide whether low-altitude (camera among the waves) is a real use case.**
   - If the camera is always well above the swell, shade-as-flat + AA is viable;
     additionally clamp `swell_amplitude` small relative to expected altitude.
   - If low flying is required, the analytic-normal + displaced-geometry approach
     is the wrong architecture (see §6).
2. **For a robust low-altitude ocean**, use the standard approach: derive the
   normal from the **same** displacement that moves the vertices (Gerstner/FFT
   height field), so geometry and shading always agree, plus proper LOD and
   **temporal AA / MSAA with sample shading** for grazing specular aliasing.
   The independent `swellField` normal is the core mismatch.
3. **Keep the reflection `P*` fix** — it is correct in principle; just ensure the
   fallback (no z=0 hit) is handled gracefully when the camera is low.
4. **Cheapest acceptable option:** ship the flat ocean (no geometric swell). It
   is clean at every altitude; you lose only the swell silhouette.

---

## 9. Tooling produced (in scratchpad, plus debug modes in-shader)

- **`cap.py`** — headless offscreen capture harness. Env-driven:
  `CAP_GEOM, CAP_SHADEPLANE, CAP_REFLRAY, CAP_AANORMAL, CAP_AALO, CAP_AAHI,
  CAP_Z, CAP_FOV, CAP_LOOKX, CAP_AMP, CAP_DRIFT, CAP_RIPPLE, CAP_WAVEOFF,
  CAP_EXP, CAP_RSCALE, CAP_SUBDIVS, CAP_MSAA, CAP_MODE, CAP_TIME, CAP_NAME`.
  Renders 4 frames offscreen and saves `ocean_debug/<CAP_NAME>.png`.
  **Always include a `CAP_Z=3` (demo regime) case in any future test.**
- **`montage.py`** — stacks labelled horizon-band crops of several captures into
  one image. Env: `M_X0,M_X1,M_Y0,M_Y1` (crop fractions), `M_SX,M_SY` (scale).
- **Debug shader modes** (`uDebugMode`): 1=N, 2=reflUV, 3=fresnel, 4=worldgrid,
  5=reflUV-clamp, 6=raw reflected, 7=pre-tonemap saturation, **8=shade-footprint
  grid**, **9=footprint magnitude**.

---

## 10. Evidence index (`ocean_debug/`)

| File | Shows |
|---|---|
| `exp1.png` | Reflection slide present (no-fix) and fixed; reflected vs normal. |
| `exp3.png` | Fresnel terracing, normal banding, worldgrid fold (root of 2b). |
| `exp8.png` | Mesh density 256 vs 1024 ≈ identical → not faceting. |
| `exp10.png` | Footprint-AA threshold sweep. |
| `exp_r.png` | Shade-from-plane + ripple 0 = pixel-clean **at Z=20**. |
| `exp_q.png` | shadeXY grid / footprint / fresnel / reflected under shade-plane. |
| `exp_fin3.png` | Realistic (waves) look at Z=20/8 — looked clean (misleadingly). |
| **`exp_z3l.png`** | **THE KEY RESULT: at Z=3 the fixes ON produce a hard wedge, worse than OFF.** |
| `exp_z3.png` | Z=3 at normal exposure. |
