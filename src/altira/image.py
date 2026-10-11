"""Resolve georeferenced raster footprints for DEM selection.

Copyright (C) 2026
"""

import os

from .coverage import split_bounds
from .raster import raster_bounds


def image_bounds(image: str) -> tuple[float, float, float, float]:
    """Resolve a georeferenced raster path to WGS84 geographic bounds.

    Parameters
    ----------
    image : str
        Raster path with an affine transform and CRS.

    Returns
    -------
    tuple[float, float, float, float]
        Geographic (west, east, south, north), with west > east when wrapped.

    Raises
    ------
    ValueError
        If the path is not a raster with an affine transform and CRS.
    FileNotFoundError
        If the supplied local path does not exist.
    """
    if not os.path.exists(image):
        raise FileNotFoundError(image)
    bounds = raster_bounds(image) if os.path.isfile(image) else None
    if bounds is None:
        raise ValueError(
            "Expected a georeferenced raster with an affine transform and CRS. "
            "For product metadata, supply geographic bounds to Dem.preload_dem_tiles(west, east, south, north)."
        )
    split_bounds(*bounds)
    return bounds
