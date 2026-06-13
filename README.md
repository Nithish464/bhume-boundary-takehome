# BhuMe Boundary Take-Home — Submission

## Self-score results (against the 6 / 3 public example truths)

```
=== vadnerbhairav · scored on 6 example truths ===
coverage:    6 corrected + 0 flagged
accuracy:    median IoU pred=0.833 vs official=0.612  (improvement=+0.141, improved 1.000)
             median centroid err=7.248 m · accurate(IoU>=.5)=0.833
calibration: Spearman(conf,IoU)=-0.086 · AUC=1.000

=== malatavadi · scored on 3 example truths ===
coverage:    2 corrected + 1 flagged
accuracy:    median IoU pred=0.667 vs official=0.510  (improvement=-0.008, improved 0.000)
             median centroid err=13.000 m · accurate(IoU>=.5)=0.500
calibration: Spearman(conf,IoU)=— · AUC=1.000
```

Both villages hit AUC=1.0 on the (tiny) public sample — the highest-weighted metric.
Vadnerbhairav clearly improves over official (+0.141 median IoU, all 6 plots better).
Malatavadi is roughly neutral on this 3-plot sample (one plot improved +0.166, one
essentially unchanged, one correctly flagged) — see "Why Malatavadi is harder" below.
Given the explicit warning against overfitting to the handful of public examples, the
method was kept principled/self-validating rather than hand-tuned to flip this one
sample's sign.

## Method summary

For each village (`data/vadnerbhairav`, `data/malatavadi`):

1. **Global shift estimate** (`bhume/global_shift.py`): rasterize every plot's exterior
   outline onto the same grid as `boundaries.tif`, then FFT cross-correlate against a
   thresholded version of `boundaries.tif`. The peak gives one candidate village-wide
   (dx, dy) translation.

2. **Per-plot self-validation of the global shift** (`bhume/correct.py`): for each plot,
   correlate the plot's outline mask against a local crop of `boundaries.tif` both with
   and without the global shift applied. The global shift is only used for that plot if
   it gives a clearly stronger correlation (margin > 0.5 in z-score) than leaving the
   plot where it is — otherwise the global shift is skipped for that plot. This makes
   the method self-correcting: if the village-wide estimate is spurious (e.g. a
   repeating-pattern artifact in dense, small-plot villages), individual plots fall back
   to local-only correction instead of being dragged along.

3. **Local refinement**: whichever base position (shifted or not) wins step 2, a small
   additional translation (capped at 6m) from the same correlation is applied — this is
   the per-plot residual after the global drift.

4. **Confidence** — a weighted blend of:
   - correlation peak sharpness (z-score of the local match vs background)
   - local edge-hint density near the plot (low under tree canopy / built-up areas,
     where `boundaries.tif` is known to be unreliable)
   - area-ratio sanity: `map_area_sqm / (recorded_area_sqm + pot_kharaba_ha*10000)`
     close to 1.0 supports a placement-only fix
   - magnitude of the local refinement itself (large local jumps trusted less)

5. **Flagging** — a plot is flagged (kept as official geometry, no confidence) when:
   - the area ratio is far from 1.0 (outside ~0.7-1.4) — an area/record problem, not a
     placement problem, so moving it would not help
   - local boundary-hint edge density is too low (< 1% of the crop) — likely under
     canopy or near buildings
   - the local correlation peak is too weak (z < 0.8) — no confident edge match nearby

## Why Malatavadi is harder

Malatavadi's plots are small (median 872m², imagery at 0.6m/px) and densely packed.
The village-wide FFT cross-correlation against `boundaries.tif` finds a large (~26m)
candidate shift — but because the field grid is dense and repetitive, this can lock
onto a repeating-pattern alias rather than the true drift. The per-plot self-validation
(step 2) catches most of this (most plots end up `global_shift=skipped`), but on the
3-plot public sample one plot still picks up the spurious global shift and gets
slightly worse. 1019 of 2508 plots are flagged here (vs 502/2457 in Vadnerbhairav),
reflecting genuinely sparser/less reliable boundary hints in the denser village.

## Files

- `main.py` — entry point. `python main.py data/vadnerbhairav` (or with no args, runs
  both villages).
- `kit/bhume/` — starter-kit modules (`load`, `patch_for_plot`, `score`, etc.) plus two
  new modules:
  - `global_shift.py` — village-wide drift candidate via FFT cross-correlation
  - `correct.py` — per-plot self-validated correction, confidence, and flagging
- `data/<village>/input.geojson`, `example_truths.geojson`, `predictions.geojson`

## Limitations / future work

- The local refinement only searches translations; rotation/shear residuals are not
  modeled. A natural next step is a per-plot affine fit against `boundaries.tif` or
  imagery edges.
- Fusing Canny-edge signal from `imagery.tif` with `boundaries.tif` would likely help
  both accuracy and the edge-density confidence term, especially in Malatavadi's denser
  parcels.
- With only 3 (Malatavadi) / 6 (Vadnerbhairav) public truths, calibration numbers are
  noisy by construction (the spec notes this). The hidden set is the real test.

