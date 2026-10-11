"""
Command Line Interface
======================
*Created on 16.03.2023 by Cookiecutter Python Library Template*
*Copyright (C) 2023*
*For COPYING and LICENSE details, please refer to the LICENSE file*

This module defines the reusable Typer application for the console script and
``python -m altira`` entry points.

"""

from typing import Annotated

import typer

from .dem import Dem

app = typer.Typer(no_args_is_help=True, help="Download and query digital elevation models.")


@app.callback()
def main() -> None:
    """Define the command group for digital elevation model operations."""


@app.command()
def download(
    image: Annotated[str, typer.Argument(help="Georeferenced raster path with an affine transform and CRS.")],
    cache_dir: Annotated[str, typer.Option(help="Persistent DEM and geoid cache directory.")],
    local_path: Annotated[list[str] | None, typer.Option(help="Local DEM directory; repeat in priority order.")] = None,
    source: Annotated[str, typer.Option(help="DEM source: copernicus, alos, alos-ellipsoidal, srtm, or srtm-ellipsoidal.")] = "copernicus",
    resolution: Annotated[int, typer.Option(help="Native source resolution in meters: 30 or 90.")] = 30,
    max_cache_size_mb: Annotated[float, typer.Option(help="Elevation-array memory cache limit in MiB.")] = 500,
) -> None:
    """Download and preload DEM tiles covering one georeferenced raster.

    Parameters
    ----------
    image : str
        Georeferenced raster path with an affine transform and CRS.
    cache_dir : str
        Persistent directory used for DEM and geoid data.
    local_path : list of str or None, default=None
        Local DEM directories, in priority order.
    source : str, default="copernicus"
        Explicit online dataset to download.
    resolution : {30, 90}, default=30
        Native resolution supported by the selected source.
    max_cache_size_mb : float, default=500
        Maximum in-memory elevation-array cache size in MiB.
    """
    dem = Dem(cache_dir=cache_dir, local_paths=local_path or (), source=source, resolution=resolution, max_cache_size_mb=max_cache_size_mb)
    for tile in dem.preload_image(image):
        typer.echo(tile.info.path)
