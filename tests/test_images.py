"""Exercise raster footprints and explicit geographic bounds for DEM selection.

Copyright (C) 2026
"""

import os

import numpy as np
import pytest
from conftest import write_raster
from osgeo import gdal, osr

from altira import Dem
from altira.image import image_bounds
from altira.raster import raster_bounds


@pytest.mark.parametrize(
    ("transform", "expected"),
    [
        ((13, 0.1, 0, 53, 0, -0.1), (13, 13.3, 52.7, 53)),
        ((13, 0.1, 0.02, 53, 0.01, -0.1), (13, 13.36, 52.7, 53.03)),
        ((179.25, 0.5, 0, 0.75, 0, -1 / 6), (179.25, -179.25, 0.25, 0.75)),
        ((179, 1 / 3, 0, 1, 0, -1 / 3), (179, 180, 0, 1)),
        ((-180, 120, 0, 90, 0, -60), (-180, 180, -90, 90)),
    ],
)
def test_affine_raster_footprints(
    tmp_path: os.PathLike[str],
    transform: tuple[float, float, float, float, float, float],
    expected: tuple[float, float, float, float],
) -> None:
    path = write_raster(os.path.join(tmp_path, "scene.tif"), np.zeros((3, 3)), transform)
    assert image_bounds(path) == pytest.approx(expected)


def test_projected_raster_footprint(tmp_path: os.PathLike[str]) -> None:
    path = write_raster(
        os.path.join(tmp_path, "projected.tif"),
        np.zeros((3, 3)),
        (0, 111319.49079327357 / 3, 0, 111325.1428663851, 0, -111325.1428663851 / 3),
    )
    with gdal.ExceptionMgr(useExceptions=True), osr.ExceptionMgr(useExceptions=True), gdal.Open(path, gdal.GA_Update) as dataset:
        projection = osr.SpatialReference()
        projection.ImportFromEPSG(3857)
        dataset.SetProjection(projection.ExportToWkt())
    assert image_bounds(path) == pytest.approx((0, 1, 0, 1))


@pytest.mark.parametrize("use_bounds", [False, True])
def test_raster_antimeridian_preload(tmp_path: os.PathLike[str], use_bounds: bool) -> None:
    folder = os.path.join(tmp_path, "local")
    for west, hemisphere, value in ((179, "E", 11), (-180, "W", 22)):
        write_raster(
            os.path.join(folder, f"TDM1_DEM__10_N00{hemisphere}{abs(west):03d}_DEM.tif"),
            np.full((5, 5), value),
            (west - 0.125, 0.25, 0, 1.125, 0, -0.25),
        )
    image = write_raster(os.path.join(tmp_path, "scene.tif"), np.zeros((3, 3)), (179.25, 0.5, 0, 0.75, 0, -1 / 6))
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(folder,))
    tiles = dem.preload_dem_tiles(179.25, -179.25, 0.25, 0.75) if use_bounds else dem.preload_image(image)
    assert len(tiles) == 2
    assert {tile.info.west for tile in tiles} == {179, -180}
    np.testing.assert_allclose(dem.interpolate_heights([179.5, -179.5], [0.5, 0.5]), [11, 22])
    assert dem.get_height_bounds(179.25, -179.25, 0.25, 0.75, compute_avg_height=True) == (11, 22, 16.5)
    assert not os.path.exists(dem.cache_dir)


@pytest.mark.parametrize("missing", ["transform", "crs", "both"])
def test_raster_without_affine_geolocation_rejected(tmp_path: os.PathLike[str], missing: str) -> None:
    path = os.path.join(tmp_path, "unlocated.tif")
    with (
        gdal.ExceptionMgr(useExceptions=True),
        osr.ExceptionMgr(useExceptions=True),
        gdal.GetDriverByName("GTiff").Create(path, 3, 3, 1) as dataset,
    ):
        if missing == "crs":
            dataset.SetGeoTransform((0, 1, 0, 1, 0, -1))
        if missing == "transform":
            projection = osr.SpatialReference()
            projection.ImportFromEPSG(4326)
            dataset.SetProjection(projection.ExportToWkt())
    assert raster_bounds(path) is None
    with pytest.raises(ValueError, match="affine transform and CRS"):
        image_bounds(path)


def test_nonraster_and_missing_image(tmp_path: os.PathLike[str]) -> None:
    path = os.path.join(tmp_path, "metadata.xml")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("<metadata />")
    assert raster_bounds(path) is None
    with pytest.raises(ValueError, match="affine transform and CRS"):
        image_bounds(path)
    with pytest.raises(FileNotFoundError):
        image_bounds(os.path.join(tmp_path, "missing.tif"))


def test_product_directory_requires_explicit_bounds(tmp_path: os.PathLike[str]) -> None:
    product = os.path.join(tmp_path, "product")
    cache = os.path.join(tmp_path, "cache")
    os.makedirs(product)
    dem = Dem(cache_dir=cache)
    with pytest.raises(ValueError, match="preload_dem_tiles"):
        dem.preload_image(product)
    assert not os.path.exists(cache)
