"""Loading a village bundle and writing predictions in the contract format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd


@dataclass
class Village:
    slug: str
    dir: Path
    plots: gpd.GeoDataFrame
    imagery_path: Path
    boundaries_path: Path | None
    example_truths: gpd.GeoDataFrame | None

    def plot(self, plot_number: str):
        return self.plots.loc[str(plot_number), 'geometry']


def load(village_dir: str | Path) -> Village:
    d = Path(village_dir)
    input_path = d / 'input.geojson'
    imagery_path = d / 'imagery.tif'
    if not input_path.exists():
        raise FileNotFoundError(f'{input_path} not found — download the village bundle into {d}/')
    if not imagery_path.exists():
        raise FileNotFoundError(f'{imagery_path} not found — download the village bundle into {d}/')

    plots = gpd.read_file(input_path)
    plots['plot_number'] = plots['plot_number'].astype(str)
    plots = plots.set_index('plot_number', drop=False)

    boundaries_path = d / 'boundaries.tif'
    truths_path = d / 'example_truths.geojson'
    example_truths = None
    if truths_path.exists():
        example_truths = gpd.read_file(truths_path)
        example_truths['plot_number'] = example_truths['plot_number'].astype(str)
        example_truths = example_truths.set_index('plot_number', drop=False)

    return Village(
        slug=d.name,
        dir=d,
        plots=plots,
        imagery_path=imagery_path,
        boundaries_path=boundaries_path if boundaries_path.exists() else None,
        example_truths=example_truths,
    )


def write_predictions(path: str | Path, predictions: gpd.GeoDataFrame) -> Path:
    required = {'plot_number', 'status', 'geometry'}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f'predictions is missing required columns: {sorted(missing)}')

    gdf = predictions.copy()
    if gdf.crs is None:
        gdf = gdf.set_crs('EPSG:4326')
    else:
        gdf = gdf.to_crs('EPSG:4326')

    keep = [c for c in ('plot_number', 'status', 'confidence', 'method_note', 'geometry') if c in gdf.columns]
    out = Path(path)
    out.write_text(gdf[keep].to_json())
    return out


def read_predictions(path: str | Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if 'plot_number' in gdf.columns:
        gdf['plot_number'] = gdf['plot_number'].astype(str)
        gdf = gdf.set_index('plot_number', drop=False)
    return gdf
