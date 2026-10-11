"""Convert EGM96 and EGM2008 elevations to WGS84 ellipsoidal heights.

Copyright (C) 2026
"""

import os

import numpy as np
from osgeo import gdal

from .datasets import Datum
from .downloads import download_file
from .raster import Raster, validate_raster


def convert_heights(raster: Raster, *, source_datum: Datum, cache_dir: str) -> None:
    """Convert valid samples in place using the matching PROJ/NGA geoid grid.

    Native source files stay unchanged. Geoid grids are downloaded atomically
    into cache_dir/geoid and resampled to the DEM sample grid. No approximate
    datum substitution or failed-conversion fallback is allowed.

    Parameters
    ----------
    raster : Raster
        Elevation grid whose valid values are converted in place.
    source_datum : Datum
        Vertical datum of the input elevations.
    cache_dir : str
        Directory used to store geoid grids.

    Raises
    ------
    ValueError
        If the datum is unsupported or the grid leaves valid samples uncovered.
    """
    if source_datum == "wgs84" or not np.isfinite(raster.values).any():
        return
    if source_datum == "egm96":
        filename = "us_nga_egm96_15.tif"
    elif source_datum == "egm2008":
        filename = "us_nga_egm08_25.tif"
    else:
        raise ValueError(f"Unsupported vertical datum: {source_datum!r}")
    path = os.path.join(cache_dir, "geoid", filename)
    if not os.path.isfile(path):
        download_file(f"https://cdn.proj.org/{filename}", path, validate=validate_raster)
    height, width = raster.values.shape
    transform = raster.transform
    west, north = transform[0], transform[3]
    east = west + width * transform[1]
    south = north + height * transform[5]
    # Warping a clipped grid keeps the global EGM2008 array out of the DEM cache.
    with (
        gdal.ExceptionMgr(useExceptions=True),
        gdal.Open(path) as grid,
        gdal.Warp(
            "",
            grid,
            format="MEM",
            outputBounds=(west, south, east, north),
            width=width,
            height=height,
            srcSRS="EPSG:4326",
            dstSRS="EPSG:4326",
            resampleAlg="bilinear",
            outputType=gdal.GDT_Float32,
            dstNodata=float("nan"),
            errorThreshold=0,
        ) as shifted,
    ):
        offsets = shifted.ReadAsArray()
    valid = np.isfinite(raster.values)
    if not np.isfinite(offsets[valid]).all():
        raise ValueError(f"Geoid grid does not cover every valid DEM sample: {path}")
    # NGA grids store geoid undulation N: ellipsoidal height h = physical H + N.
    raster.values[valid] += offsets[valid]
