"""Read and sample geographic rasters using GDAL pixel-edge geotransforms.

Copyright (C) 2026
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from osgeo import gdal, osr

GeoTransform = tuple[float, float, float, float, float, float]


def raster_bounds(path: str) -> tuple[float, float, float, float] | None:
    """Read affine raster coverage and transform its envelope to WGS84.

    Parameters
    ----------
    path : str
        Raster path to inspect.

    Returns
    -------
    tuple[float, float, float, float] or None
        Geographic (west, east, south, north), with west > east when wrapped.
        None for nonrasters or rasters lacking an affine transform or CRS.
        Rotated grids use a conservative envelope; projected edges are densified.

    Raises
    ------
    ValueError
        If the coordinate transformation cannot produce finite geographic bounds.
    """
    with gdal.ExceptionMgr(useExceptions=True), osr.ExceptionMgr(useExceptions=True):
        if gdal.IdentifyDriver(path) is None:
            return None
        with gdal.Open(path) as dataset:
            transform = dataset.GetGeoTransform(can_return_null=True)
            source = dataset.GetSpatialRef()
            if transform is None or source is None:
                return None
            corners = np.asarray([
                gdal.ApplyGeoTransform(transform, column, row)
                for column, row in ((0, 0), (dataset.RasterXSize, 0), (dataset.RasterXSize, dataset.RasterYSize), (0, dataset.RasterYSize))
            ])
            source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            target = osr.SpatialReference()
            target.ImportFromEPSG(4326)
            target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            conversion = osr.CoordinateTransformation(source, target)
            west, south, east, north = conversion.TransformBounds(*corners.min(axis=0), *corners.max(axis=0), 21)
    if not np.isfinite((west, east, south, north)).all():
        raise ValueError(f"Raster CRS transformation did not produce finite geographic bounds: {path}")
    if east - west >= 360:
        west, east = -180.0, 180.0
    else:
        west = (west + 180) % 360 - 180
        east = (east + 180) % 360 - 180 if east != 180 else 180.0
    return west, east, south, north


@dataclass(eq=False)
class Raster:
    """A geographic raster with invalid samples represented by NaN.

    Attributes
    ----------
    values : ndarray
        Two-dimensional float32 sample grid.
    transform : GeoTransform
        GDAL pixel-edge geotransform for the grid.
    """

    values: NDArray[np.float32]
    transform: GeoTransform

    def pixel_coordinates(self, lon: NDArray[np.float64], lat: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Convert coordinates to sample-center indices, preserving their shape.

        Parameters
        ----------
        lon, lat : ndarray
            Matching arrays of geographic coordinates.

        Returns
        -------
        tuple of ndarray
            Fractional column and row indices relative to sample centers.
        """
        inverse = gdal.InvGeoTransform(self.transform)
        x = inverse[0] + inverse[1] * lon + inverse[2] * lat - 0.5
        y = inverse[3] + inverse[4] * lon + inverse[5] * lat - 0.5
        return x, y


def validate_raster(path: str) -> None:
    """Require a readable, nonempty single-band raster, decoding every block.

    Parameters
    ----------
    path : str
        Raster path to validate.

    Raises
    ------
    ValueError
        If the raster is empty or has multiple bands.
    """
    with gdal.ExceptionMgr(useExceptions=True), gdal.Open(path) as dataset:
        if dataset.RasterCount != 1 or dataset.RasterXSize < 1 or dataset.RasterYSize < 1:
            raise ValueError(f"Expected a nonempty single-band raster: {path}")
        dataset.GetRasterBand(1).Checksum()


def read_raster(path: str) -> Raster:
    """Read a north-up WGS84 raster, honoring band nodata and its validity mask.

    Parameters
    ----------
    path : str
        Raster path to read.

    Returns
    -------
    Raster
        Float32 elevations and pixel-edge transform, with NaN for invalid samples.

    Raises
    ------
    ValueError
        If the raster lacks a valid north-up WGS84 grid or has multiple bands.
    """
    with gdal.ExceptionMgr(useExceptions=True), osr.ExceptionMgr(useExceptions=True), gdal.Open(path) as dataset:
        if dataset.RasterCount != 1:
            raise ValueError(f"Expected a single-band elevation raster: {path}")
        transform = dataset.GetGeoTransform(can_return_null=True)
        if transform is None or transform[1] <= 0 or transform[5] >= 0 or transform[2] != 0 or transform[4] != 0:
            raise ValueError(f"Expected a north-up geographic raster with a valid geotransform: {path}")
        spatial_ref = dataset.GetSpatialRef()
        wgs84 = osr.SpatialReference()
        wgs84.ImportFromEPSG(4326)
        if spatial_ref is None or not spatial_ref.IsGeographic() or not spatial_ref.IsSameGeogCS(wgs84):
            raise ValueError(f"Expected a WGS84 geographic elevation raster: {path}")
        band = dataset.GetRasterBand(1)
        values = band.ReadAsArray().astype(np.float32)
        valid = band.GetMaskBand().ReadAsArray() != 0
        nodata = band.GetNoDataValue()
        if nodata is not None:
            valid &= values != nodata
        values[~valid | ~np.isfinite(values)] = np.nan
    return Raster(values=values, transform=tuple(transform))


def bilinear_values(
    samples: tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.float32], NDArray[np.float32]],
    dx: NDArray[np.float64],
    dy: NDArray[np.float64],
    default_value: float,
) -> NDArray[np.float32]:
    """Interpolate four posts, replacing contributing invalid posts with a default.

    Parameters
    ----------
    samples : tuple of ndarray
        Four float32 corner sample arrays ordered by upper-left, upper-right,
        lower-left, and lower-right positions.
    dx, dy : ndarray
        Fractional column and row offsets for each interpolation position.
    default_value : float
        Value substituted for invalid samples that have a nonzero weight.

    Returns
    -------
    ndarray
        Float32 bilinear values with the fractional-coordinate shape.
    """
    weights = ((1 - dx) * (1 - dy), dx * (1 - dy), (1 - dx) * dy, dx * dy)
    result = np.zeros(dx.shape, dtype=np.float64)
    for sample, weight in zip(samples, weights, strict=True):
        contributing = weight > 1e-12
        result[contributing] += np.where(np.isfinite(sample[contributing]), sample[contributing], default_value) * weight[contributing]
    return result.astype(np.float32)
