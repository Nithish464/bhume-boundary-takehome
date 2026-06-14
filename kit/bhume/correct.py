

from __future__ import annotations

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from scipy.signal import fftconvolve
from shapely.affinity import translate
from shapely.geometry.base import BaseGeometry

from bhume.global_shift import estimate_global_shift

LOCAL_MAX_SHIFT_M = 6.0
AREA_RATIO_LO = 0.7
AREA_RATIO_HI = 1.4
MIN_EDGE_DENSITY = 0.01


def _utm_for(geom: BaseGeometry) -> str:
    lon = geom.centroid.x
    return f'EPSG:{32600 + int((lon + 180) // 6) + 1}'


def _area_ratio(row) -> float | None:
    recorded = row.get('recorded_area_sqm')
    pot_kharaba_ha = row.get('pot_kharaba_ha') or 0.0
    if recorded is None or recorded == 0 or recorded != recorded:
        return None
    full_recorded = recorded + (pot_kharaba_ha or 0.0) * 10000.0
    if full_recorded == 0:
        return None
    return row['map_area_sqm'] / full_recorded


def _crop_for_bounds(bounds, hints_src, hints_transform, hints_arr, pad_px):
    minx, miny, maxx, maxy = bounds
    row_min, col_min = hints_src.index(minx, maxy)
    row_max, col_max = hints_src.index(maxx, miny)
    row_min, row_max = sorted([row_min, row_max])
    col_min, col_max = sorted([col_min, col_max])

    r0 = max(0, row_min - pad_px)
    r1 = min(hints_arr.shape[0], row_max + pad_px)
    c0 = max(0, col_min - pad_px)
    c1 = min(hints_arr.shape[1], col_max + pad_px)

    if r1 <= r0 or c1 <= c0:
        return None

    crop = hints_arr[r0:r1, c0:c1].astype(np.float32)
    if crop.size == 0:
        return None

    crop_transform = rasterio.transform.from_origin(
        hints_transform.c + c0 * hints_transform.a,
        hints_transform.f + r0 * hints_transform.e,
        hints_transform.a,
        -hints_transform.e,
    )
    return crop, crop_transform


def _correlate_mask(geom_proj, crop, crop_transform, edge_thresh, max_shift_m, pad_px):
    if geom_proj.geom_type == 'MultiPolygon':
        exteriors = [(g.exterior, 1) for g in geom_proj.geoms]
    else:
        exteriors = [(geom_proj.exterior, 1)]

    mask = rasterize(
        exteriors, out_shape=crop.shape, transform=crop_transform, fill=0, dtype=np.uint8
    ).astype(np.float32)

    edge_density = float((crop > edge_thresh).mean()) if crop.size else 0.0

    if mask.sum() == 0 or crop.std() == 0:
        return 0.0, 0.0, 0.0, edge_density

    a = mask - mask.mean()
    b = crop - crop.mean()
    corr = fftconvolve(b, a[::-1, ::-1], mode='same')

    cy, cx = np.array(corr.shape) // 2
    max_shift_px = min(pad_px - 2, cy, cx)
    if max_shift_px <= 0:
        return 0.0, 0.0, 0.0, edge_density

    sub = corr[cy - max_shift_px:cy + max_shift_px + 1, cx - max_shift_px:cx + max_shift_px + 1]
    peak_idx = np.unravel_index(np.argmax(sub), sub.shape)
    dy_px = peak_idx[0] - max_shift_px
    dx_px = peak_idx[1] - max_shift_px

    dx_m = dx_px * crop_transform.a
    dy_m = dy_px * crop_transform.e

    mag = (dx_m**2 + dy_m**2) ** 0.5
    if mag > max_shift_m and mag > 0:
        scale = max_shift_m / mag
        dx_m *= scale
        dy_m *= scale

    peak_val = sub[peak_idx]
    std = sub.std()
    strength = float((peak_val - np.median(sub)) / (std + 1e-6)) if std > 0 else 0.0

    return float(dx_m), float(dy_m), strength, edge_density


def _local_refine(geom_proj, hints_src, hints_transform, hints_arr, max_shift_m=LOCAL_MAX_SHIFT_M,
                   edge_thresh=None):
    px_res = abs(hints_transform.a)
    pad_px = int(max_shift_m / px_res) + 5
    if edge_thresh is None:
        edge_thresh = np.percentile(hints_arr, 70) if hints_arr.size else 0

    cropped = _crop_for_bounds(geom_proj.bounds, hints_src, hints_transform, hints_arr, pad_px)
    if cropped is None:
        return 0.0, 0.0, 0.0, 0.0
    crop, crop_transform = cropped
    return _correlate_mask(geom_proj, crop, crop_transform, edge_thresh, max_shift_m, pad_px)


def correct_village(village, global_dx=None, global_dy=None) -> gpd.GeoDataFrame:
    if global_dx is None or global_dy is None:
        global_dx, global_dy, _ = estimate_global_shift(village)

    with rasterio.open(village.boundaries_path) as hints_src:
        hints_arr = hints_src.read(1)
        hints_transform = hints_src.transform
        hints_crs = hints_src.crs

    plots_proj = village.plots.to_crs(hints_crs)
    edge_thresh = float(np.percentile(hints_arr, 70)) if hints_arr.size else 0.0
    px_res = abs(hints_transform.a)
    pad_px = int(LOCAL_MAX_SHIFT_M / px_res) + 5

    records = []
    with rasterio.open(village.boundaries_path) as hints_src:
        for pn, row in village.plots.iterrows():
            geom = plots_proj.loc[pn, 'geometry']
            if geom is None or geom.is_empty:
                records.append(dict(plot_number=pn, status='flagged', confidence=None,
                                     method_note='empty geometry', geometry=row.geometry))
                continue

            ratio = _area_ratio(row)

            shifted_with = translate(geom, global_dx, global_dy)
            combined_bounds = (
                min(geom.bounds[0], shifted_with.bounds[0]),
                min(geom.bounds[1], shifted_with.bounds[1]),
                max(geom.bounds[2], shifted_with.bounds[2]),
                max(geom.bounds[3], shifted_with.bounds[3]),
            )
            cropped = _crop_for_bounds(combined_bounds, hints_src, hints_transform, hints_arr, pad_px)
            if cropped is None:
                records.append(dict(plot_number=pn, status='flagged', confidence=None,
                                     method_note='plot outside imagery extent', geometry=row.geometry))
                continue
            crop, crop_transform = cropped

            dx_w, dy_w, strength_w, density_w = _correlate_mask(
                shifted_with, crop, crop_transform, edge_thresh, LOCAL_MAX_SHIFT_M, pad_px
            )
            dx_wo, dy_wo, strength_wo, density_wo = _correlate_mask(
                geom, crop, crop_transform, edge_thresh, LOCAL_MAX_SHIFT_M, pad_px
            )

            margin = strength_w - strength_wo
            if margin > 0.5:
                base_dx, base_dy = global_dx, global_dy
                shifted = shifted_with
                dx_local, dy_local, strength, edge_density = dx_w, dy_w, strength_w, density_w
                used_global = True
            else:
                base_dx, base_dy = 0.0, 0.0
                shifted = geom
                dx_local, dy_local, strength, edge_density = dx_wo, dy_wo, strength_wo, density_wo
                used_global = False

            final_geom_proj = translate(shifted, dx_local, dy_local)

            method_parts = [f'global_shift={"used" if used_global else "skipped"}=({base_dx:.1f},{base_dy:.1f})m']
            flag_reasons = []

            if ratio is not None and not (AREA_RATIO_LO <= ratio <= AREA_RATIO_HI):
                flag_reasons.append(f'area ratio {ratio:.2f} far from 1.0 (likely area/record mismatch, not placement)')

            if edge_density < MIN_EDGE_DENSITY:
                flag_reasons.append(f'sparse boundary hints (edge density {edge_density:.3f}), likely canopy/building')

            if strength < 0.8:
                flag_reasons.append(f'weak local correlation (z={strength:.2f})')

            if flag_reasons:
                status = 'flagged'
                confidence = None
                method_note = '; '.join(flag_reasons)
                out_geom_proj = geom
            else:
                status = 'corrected'
                method_parts.append(f'local_refine=({dx_local:.1f},{dy_local:.1f})m')
                method_parts.append(f'corr_strength={strength:.2f}')
                method_parts.append(f'edge_density={edge_density:.3f}')
                if ratio is not None:
                    method_parts.append(f'area_ratio={ratio:.2f}')
                method_note = '; '.join(method_parts)
                out_geom_proj = final_geom_proj

                strength_score = float(np.clip((strength - 0.8) / 3.0, 0, 1))
                density_score = float(np.clip(edge_density / 0.15, 0, 1))
                if ratio is not None:
                    ratio_score = float(np.clip(1 - abs(ratio - 1.0) / 0.3, 0, 1))
                else:
                    ratio_score = 0.5
                shift_mag = (dx_local ** 2 + dy_local ** 2) ** 0.5
                shift_score = float(np.clip(1 - shift_mag / LOCAL_MAX_SHIFT_M, 0, 1))

                confidence = float(np.clip(
                    0.35 * strength_score + 0.30 * density_score + 0.20 * ratio_score + 0.15 * shift_score,
                    0.05, 0.97
                ))

            out_gdf = gpd.GeoSeries([out_geom_proj], crs=hints_crs).to_crs('EPSG:4326')
            records.append(dict(
                plot_number=pn,
                status=status,
                confidence=confidence,
                method_note=method_note,
                geometry=out_gdf.iloc[0],
            ))

    out = gpd.GeoDataFrame(records, geometry='geometry', crs='EPSG:4326')
    return out
