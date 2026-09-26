# Design note: view-aligned slices instead of billboards?

**Status: open question, nothing here is implemented.** Parked on 2026-08-24 for
later. The measurements are the valuable part of this file — they were taken
against the deck as it stands and would be tedious to re-derive.

---

## The question

> Wouldn't it be cheaper to slice the space in front of the camera, in
> exponentially thick slices, and display on camera-facing billboards at slice
> borders the line-of-sight integration of the clouds? The billboards would be the
> size of the screen, but could be rendered at lower resolution (it's transparent
> and blurry anyway) and there may be much less of them? It would preserve the
> volumetric effect and the depth sort would be much simpler.

This is a real technique — it is what froxel-based volumetric fog does in UE and
Frostbite.

---

## Measurements taken to answer it

All against the six-shell HIGH cumulus deck (104,499 billboards), horizon view,
70° FOV, on Intel Arc integrated graphics. Scripts were scratchpad-only.

### Cost vs resolution, at fixed billboard count

Frame time with the deck minus frame time with it hidden:

| resolution | pixels | cloud cost |
|---|---|---|
| 640×360 | 230k | 1.47 ms |
| 960×540 | 518k | 1.35 ms |
| 1280×720 | 922k | 2.43 ms |
| 1920×1080 | 2.07M | 3.02 ms |
| 2560×1440 | 3.69M | 2.71 ms |

**A 16× pixel range costs at most 2×.** The deck is only weakly fill-bound.

### Cost vs billboard count, at fixed 1280×720

From the quality ladder (`CloudQuality`):

| level | billboards | ms/frame |
|---|---|---|
| Low | 26,123 | 2.3 |
| Mid | 52,248 | 3.6 |
| High | 104,499 | 5.8 |
| Ultra | 209,001 | 11.4 |

**Very nearly linear in count.**

### CPU side alone

`field.update()` with no drawing at all — wind, toroidal recycle, incremental
re-sort — costs **~3–6 ms of CPU per frame** with a moving camera. (A stationary
camera never triggers a recycle and flatters this, so the probe moved the camera
60 m per frame.)

### Conclusion from the above

Cost is dominated by **per-billboard work and per-frame CPU**, not by fill rate.
That corrects an earlier claim of mine that "the billboard count is where the
frame time is *because fill rate tracks it*" — the count part holds, the fill part
does not.

### A measurement that did NOT work, recorded so it is not repeated

`GraphicsEngine.render_frame()` only queues work, so timing a draw without a sync
measures submission, not the GPU. `GraphicsStateGuardian` exposes no `finish()`.
Forcing a sync via `win.get_screenshot()` per frame produced GPU figures (15 ms at
1280×720) flatly inconsistent with the un-synced wall clock (~9 ms total for the
same frame), so the readback is doing more than synchronising. **The un-synced
sweeps above are the trustworthy data; there is no reliable clean CPU/GPU split
yet.** Getting one would need real GPU timer queries.

---

## Where the idea genuinely wins

1. **The sort machinery disappears — worth 3–6 ms of CPU.** Gone: cell-distance
   ordering, the lexsort over a ragged layout, the 8-frame round-robin restage,
   the cellParams texture, `_CELLS_PER_ROW` wrapping, index-buffer reuploads.
   View-aligned slices are ordered by construction.
2. **Ordering becomes exact.** Both the "cross-cell interleaving is only
   approximate" caveat and the 8-frame draw-order staleness vanish.
3. **Primitive count collapses**: 100k quads / 400k verts → tens. Given cost is
   linear in count, this is the axis that matters.
4. **The integrator is unchanged.** Premultiplied-over back-to-front across slices
   still gives `Π exp2(-od_i) = exp2(-Σ od_i)`, the identity the current billboards
   rely on. Nothing is lost here.

## Where it loses

1. **Empty sky — the decisive objection.** At 0.29 coverage only ~24% of screen
   pixels have any cloud (measured 0.234). Billboards draw *nothing* in the other
   76%; N full-screen slices evaluate the density field N times for every pixel.

   And critically: **N independent draw calls cannot early-out or skip empty
   space.** The reference shader's `dt = abs(den) + 0.2` (stride through clear air)
   and `if (sum.a > 0.995) break` both require a loop. Each slice is an
   unconditional full-screen rasterisation. So slices are strictly worse than the
   single-pass raymarch they emulate, and they give up the one structural edge
   billboards have over a raymarch: samples exist only where cloud does.

2. **Exponential spacing is uncorrelated with where cloud is.** The deck is a 1 km
   slab reaching 512 km. Looking horizontally at cloud altitude a ray stays in the
   slab for hundreds of km; looking up it exits in 1 km. Slices allocated by
   distance-from-camera have no relationship to slab intersection, so at many
   altitudes most near slices sit in clear air.

   Far-field undersampling is *not* the objection: at 512 km a 2 km feature
   subtends ~4 µrad, well under a pixel, and is fully haze-coloured by 400 km.

   Slab-parallel horizontal slices fix the vertical case and break the horizontal
   one — the dual failure, not a fix.

3. **Per-fragment depth against scene geometry.** Today each fragment depth-tests
   individually, so a ship half-buried in cloud just works (what the demo's
   oversized smiley checks). A screen-sized slice sits at one depth and so passes
   or fails wholesale, giving hard cuts where geometry intersects. Fixing it needs
   the scene depth texture; low-res compositing additionally needs depth-aware
   (bilateral) upsampling or there are halos around every ship silhouette.

   That is the plumbing `trials/cloud_harris/pure-shader/v20..v42` rejected after
   23 prototypes. Infrastructure catch: `GraphicsManager` only builds an offscreen
   pipeline when render scale < 1 or MSAA/FXAA is on, so a low-res slice buffer
   would need that path made unconditional.

4. **"Transparent and blurry anyway" — worth pushing back on.** Cumulus edges
   against blue sky are the sharpest feature in the frame, and the narrow
   smoothstep threshold that produces them is what this whole design exists for
   (see `noise.DensityField.edge_softness`). Quarter-res would blur precisely
   that. The cloud *interior* is genuinely low-frequency, though — which is the
   real insight in the question, and points at the hybrid below.

5. **Slice-crossing shimmer.** As the camera moves or rotates, slice planes sweep
   through the volume and features pop between them (the classic wood-grain
   artifact), needing per-frame jitter plus temporal reprojection. Note IQ's
   rainforest shader does both — Bayer-dithered ray origin, explicit reprojection
   "to smooth out the render" — evidence that even at 128 steps this needed
   handling.

---

## The hybrid that looks actually right: far field only

Every objection above inverts in the distance.

The outer LOD shells hold thousands of billboards each covering a handful of
pixels — the worst case for quad rasterisation, since a 4-pixel quad still costs
full primitive setup and 4 vertices, and cost is linear in count. Meanwhile the
far field is sub-pixel in detail, fully haze-coloured by 400 km
(`HORIZON_DISTANCE`), never flown through, and never intersected by ships. Blur is
free there; depth is irrelevant there.

This does **not** contradict the rejection of impostors in
`trials/cloud_harris/cards/v10..v13`: that rejection was specifically because
impostors cannot be flown through. The far field never is.

So: keep billboards for the near shells, where the silhouette, the fly-through and
the per-fragment depth test all matter; replace the outer shells with a few
integrated slices or one re-projected far layer. That targets the most numerous,
cheapest-looking, least visually critical billboards in the system.

---

## What would change the verdict for the near field

- **Overcast targets.** At stratus's 0.82 coverage rather than scattered cumulus's
  0.29, the empty-sky objection largely evaporates and slices become genuinely
  competitive.
- **Light shafts / godrays.** A froxel grid is their natural home, which would
  change the accounting entirely.

## Next measurement to take before committing either way

How much of that 3–6 ms of CPU is the **sort** specifically, versus wind and
recycling. If the sort dominates, there may be a cheaper win with no change to the
rendering model at all — a coarser cell grid, or a longer `resort_frames`, since
exact ordering only matters where clouds overlap *on screen*.
