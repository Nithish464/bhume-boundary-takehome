#!/usr/bin/env python3
"""
BhuMe boundary take-home — main pipeline.

For each village in data/<village>/, reads input.geojson + imagery.tif + boundaries.tif
and writes predictions.geojson next to it.

Method (classical CV, no training):
  1. Global shift: rasterize all plot-edge lines and cross-correlate (FFT phase
     correlation) against the boundaries.tif edge-hint raster to find one village-wide
     translation (dx, dy). This captures the dominant georeferencing drift.
  2. Per-plot local refinement: after applying the global shift, crop a small window of
     boundaries.tif around each plot and cross-correlate the plot's outline mask against
     the local edge hints to find a small additional translation (capped at a few
     metres). This handles plots whose drift differs from the village average.
  3. Confidence: a weighted combination of (a) correlation peak sharpness (z-score),
     (b) local edge-hint density (how much real signal boundaries.tif has near the
     plot — low under canopy/buildings), (c) how close the drawn area is to the
     recorded area + pot-kharaba (near 1.0 -> placement problem, fixable; far -> not),
     and (d) the magnitude of the local refinement itself (large local jumps are less
     trustworthy).
  4. Flagging: a plot is flagged (kept as-is, no confidence) if the area ratio is far
     from 1.0 (this is an area/record problem, not a placement problem — moving it
     won't help), if boundary-hint edge density nearby is too sparse to trust (likely
     tree cover or built-up area), or if the local correlation peak is too weak/flat to
     indicate a real edge match.

Run:
    python main.py data/vadnerbhairav
    python main.py data/malatavadi
    python main.py            # runs both
"""

from __future__ import annotations

import sys
from pathlib import Path

from bhume import load, write_predictions
from bhume.correct import correct_village
from bhume.global_shift import estimate_global_shift

DEFAULT_VILLAGES = ['data/vadnerbhairav', 'data/malatavadi']


def run(village_dir: str) -> None:
    village = load(village_dir)
    print(f'Loaded {village.slug}: {len(village.plots)} plots')

    dx, dy, strength = estimate_global_shift(village)
    print(f'  global shift: dx={dx:.2f}m dy={dy:.2f}m (corr strength z={strength:.2f})')

    preds = correct_village(village, global_dx=dx, global_dy=dy)
    n_corrected = (preds.status == 'corrected').sum()
    n_flagged = (preds.status == 'flagged').sum()
    print(f'  {n_corrected} corrected, {n_flagged} flagged')

    out = write_predictions(Path(village_dir) / 'predictions.geojson', preds)
    print(f'  wrote {out}')

    if village.example_truths is not None:
        from bhume import score
        print(score(preds, village))


if __name__ == '__main__':
    targets = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_VILLAGES
    for t in targets:
        run(t)
        print()
