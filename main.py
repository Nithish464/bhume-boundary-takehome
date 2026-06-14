#!/usr/bin/env python3



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
