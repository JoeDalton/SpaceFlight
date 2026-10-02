# Ocean Geometric-Swell Artifacts — Investigation Report

> **Historical report — does not describe the current code.** None of the §3
> shader toggles (`uReflRayToPlane`, `uShadeFromPlane`, `uAANormal`,
> `uAALo`/`uAAHi`), the `vSurfacePos` varying or the extra debug modes are in
> the code today; `ocean.frag` debug mode 8 is now the FM phase field. The §2a
> reflection fix is not applied either: `ocean.frag` still samples the
> reflection at the flat footprint (`uReflMVP * vec4(vWorldPos.xy, 0.0, 1.0)`).
> The demo script (`scripts/ocean_demo.py`), the capture tooling and the
> `ocean_debug/` evidence images were never committed. Contrary to the §6
> recommendation, `SceneOcean` runs with `geometric_swell=True` (see
> `scenes.py`). The diagnosis below still applies to that mode.

**Status: NOT SOLVED.** The fixes tried help when the camera is *above* the
swell crests but **introduce a worse, hard-edged artifact at low altitude**
(camera among or below the crests), which was the demo's default view (`Z=3`).

---

## 1. Symptoms

- Dark patches at low exposure / white patches when overexposed, concentrated on
  the **camera-facing slopes of the swell**, near the horizon band.
- Present at **all altitudes**: raising the camera pushes the band toward the
  horizon but does not remove it (an angular/grazing effect).
- **Vanish entirely when `geometric_swell` is off.** Disabling only the small
  waves (`uWaveOff=1`) keeps them, so it is not the small-wave field.

The flat ocean (single quad, `geometric_swell=False`) is the only reliably clean
configuration.

---

## 2. Diagnosis

Two independent mechanisms, both requiring the vertex displacement (so they read
as one bug and both vanish with the swell geometry off).

### 2a. Reflection slide — fixable at altitude

The fragment shader shades the displaced surface but samples the planar
reflection at the **flat footprint** (`vWorldPos.xy`, z=0). Planar reflection is
only exact on the mirror plane, so the reflection slides across the
high-contrast horizon as crests rise → large dark/bright reflected patches.
Debug mode 6 (raw reflection) shows them; mode 5 rules out the UV edge clamp.

Fix tried: cast the true view ray back to `z=0` (`P*`) and project that point
through the reflection MVP. Clean in reflected-only mode at both buffer
resolutions — sound *at altitude*, and the one unambiguous win.

### 2b. Grazing normal aliasing — not solved

Near grazing, the displaced surface's per-pixel **world footprint balloons and
folds** (perspective foreshortening). The swell normal is the per-pixel gradient
of `swellField(worldPos)`, so it **aliases/terraces** where the footprint changes
fast, and the fresnel's `pow(1-NdotV, 5)` amplifies tiny normal tilts into dark
streaks.

The flat ocean avoids this because its footprint is smooth everywhere and
`detailAngle` flattens the normal at grazing. On the displaced surface
`detailAngle` is keyed on **view angle**, which misses the foreshortening.

Ruled out (each tested): mesh density (256 vs 1024 subdivisions look nearly
identical, so not faceting), reflection buffer resolution (`refl_scale` 0.5 vs
2.0), MSAA, the ripple alone, and the view-vector source.

---

## 3. Approaches tried

| Approach | Shader knob | Result |
|---|---|---|
| Reflection ray-cast to z=0 | `uReflRayToPlane` | Fixes the reflection slide **at altitude**. Sound. |
| View vector from displaced surface | `uViewFromSurface` | No effect; removed. |
| Footprint normal anti-aliasing | `uAANormal`, `uAALo`/`uAAHi` | Partially reduces the aliasing; needs thresholds aggressive enough to flatten the near swell. Never fully clean. |
| Shade-as-flat (all shading at `P*`) | `uShadeFromPlane` | At altitude ≈ flat ocean, pixel-clean. At low altitude **introduces a hard seam, worse than the original.** |
| Mesh density / MSAA / reflection resolution | (capture only) | Ruled out as primary causes. |

---

## 4. The failure at low altitude (Z=3)

The demo started at `(0, -300, 3)` while `swell_amplitude=20` puts crest tops at
about +15, so the camera sat *below the crests*. There the shade-as-flat ray
(`P* = ray ∩ z=0`) has **no forward intersection** for the part of the view
showing crests above the camera (`rd.z ≥ 0`). Those pixels fall back to
displaced-footprint shading, the footprint AA hard-flattens where the footprint
blows up, and the boundary between the two regions is a **hard, stair-stepped
wedge**, worse than with the fixes off.

Every "clean" capture during the investigation was taken at Z=20 or Z=8, above
all crests, where no fallback region exists — so the seam went unseen until the
end. **Validate any future attempt at Z≈3 (camera among the waves) and in
motion, not only at altitude.**

---

## 5. Root cause

Vertex-displaced swell geometry + per-pixel swell normal + planar reflection
is fundamentally fragile:

- At grazing, the displaced footprint foreshortens and the per-pixel normal (an
  independent field, not derived from the mesh) aliases: geometry and shading
  normal disagree.
- "Shade as a flat plane" is only defined when every pixel has a z=0 footprint,
  i.e. the camera is strictly above the whole surface. Near or below crest
  height it breaks, visibly.

The architecture cannot be patched into correctness for low-altitude views with
these tools.

---

## 6. Recommended next directions

1. **Decide whether low altitude (camera among the waves) is a real use case.**
   If the camera always stays well above the swell, shade-as-flat + AA is
   viable, with `swell_amplitude` clamped small relative to altitude. If low
   flying is required, this architecture is wrong (§5).
2. **For a robust low-altitude ocean**, derive the normal from the **same**
   displacement that moves the vertices (Gerstner/FFT height field), so geometry
   and shading always agree, plus proper LOD and **temporal AA / MSAA with
   sample shading** for grazing specular aliasing. The independent `swellField`
   normal is the core mismatch.
3. **Keep the reflection `P*` fix** — correct in principle — but handle the
   no-z=0-hit fallback gracefully when the camera is low.
4. **Cheapest acceptable option:** ship the flat ocean. It is clean at every
   altitude; only the swell silhouette is lost.

Debug shader modes used (`uDebugMode`): 1 = N, 2 = reflUV, 3 = fresnel,
4 = world grid, 5 = reflUV clamp, 6 = raw reflected, 7 = pre-tonemap saturation;
8 (shade-footprint grid) and 9 (footprint magnitude) were added for the
investigation and are gone.
