
from __future__ import annotations

import statistics

import geopandas as gpd
from shapely.affinity import translate


def _utm_for(geom) -> str:
    lon = geom.centroid.x
    return f'EPSG:{32600 + int((lon + 180) // 6) + 1}'


def global_median_shift(village, dx=None, dy=None, confidence: float = 0.5) -> gpd.GeoDataFrame:
    """Apply one translation (dx, dy in metres, UTM) to every plot.

    If dx/dy not given and example_truths exist, estimate from those.
    """
    utm = _utm_for(village.plots.geometry.iloc[0])
    official_u = village.plots.to_crs(utm)

    if dx is None or dy is None:
        if village.example_truths is None:
            raise ValueError('no dx/dy given and no example_truths to estimate from')
        truth_u = village.example_truths.to_crs(utm)
        dxs, dys = [], []
        for pn in village.example_truths.index:
            if pn in official_u.index:
                o = official_u.loc[pn, 'geometry'].centroid
                t = truth_u.loc[pn, 'geometry'].centroid
                dxs.append(t.x - o.x)
                dys.append(t.y - o.y)
        dx, dy = statistics.median(dxs), statistics.median(dys)

    shifted = official_u.copy()
    shifted['geometry'] = shifted.geometry.apply(lambda g: translate(g, dx, dy))
    preds = shifted.to_crs('EPSG:4326')
    preds['status'] = 'corrected'
    preds['confidence'] = confidence
    preds['method_note'] = f'global median shift dx={dx:.1f}m dy={dy:.1f}m'
    return preds[['plot_number', 'status', 'confidence', 'method_note', 'geometry']]
