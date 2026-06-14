
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy.signal import fftconvolve


def estimate_global_shift(village, max_shift_m: float = 30.0):
   
    if village.boundaries_path is None:
        return 0.0, 0.0, 0.0

    with rasterio.open(village.boundaries_path) as src:
        hints = src.read(1).astype(np.float32)
        transform = src.transform
        crs = src.crs

    plots_proj = village.plots.to_crs(crs)

   
    shapes = []
    for geom in plots_proj.geometry:
        if geom is None or geom.is_empty:
            continue
        geoms = geom.geoms if geom.geom_type == 'MultiPolygon' else [geom]
        for g in geoms:
            shapes.append((g.exterior, 1))

    official_mask = rasterize(
        shapes, out_shape=hints.shape, transform=transform, fill=0, dtype=np.uint8
    ).astype(np.float32)

   
    hints_bin = (hints > np.percentile(hints, 60)).astype(np.float32)

  
    a = official_mask - official_mask.mean()
    b = hints_bin - hints_bin.mean()
    corr = fftconvolve(b, a[::-1, ::-1], mode='same')

    cy, cx = np.array(corr.shape) // 2
    px_res = abs(transform.a)
    max_shift_px = int(max_shift_m / px_res)

    sub = corr[cy - max_shift_px:cy + max_shift_px + 1, cx - max_shift_px:cx + max_shift_px + 1]
    peak_idx = np.unravel_index(np.argmax(sub), sub.shape)
    dy_px = peak_idx[0] - max_shift_px
    dx_px = peak_idx[1] - max_shift_px

    
    dx_m = dx_px * transform.a
    dy_m = dy_px * transform.e

    peak_val = sub[peak_idx]
    baseline_val = np.median(sub)
    strength = float((peak_val - baseline_val) / (sub.std() + 1e-6))

    return float(dx_m), float(dy_m), strength
