"""Exercise explicit provider selection with real HTTP transfers and rasters.

Copyright (C) 2026
"""

import logging
import os

import numpy as np
import pytest
from conftest import write_raster, write_tile_catalog
from typer.testing import CliRunner

from altira import Dem
from altira.cli import app
from altira.provider.opentopography import OpenTopography
from altira.raster import read_raster


@pytest.mark.parametrize(
    ("source", "resolution", "dataset", "catalog_name", "relative", "datum", "height"),
    [
        ("alos", 30, "AW3D30", "AW3D30_global.vrt", "AW3D30_global/ALPSMLC30_N000E000_DSM.tif", "egm96", 145),
        ("alos-ellipsoidal", 30, "AW3D30_E", "AW3D30_E_global.vrt", "AW3D30_E_global/ALPSMLC30_N000E000_DSM_wgs84.tif", "wgs84", 100),
        ("srtm", 30, "SRTM_GL1", "SRTM_GL1_srtm.vrt", "SRTM_GL1_srtm/N00E000.tif", "egm96", 145),
        ("srtm", 90, "SRTM_GL3", "SRTM_GL3_srtm.vrt", "SRTM_GL3_srtm/North/North_0_29/N00E000.tif", "egm96", 145),
        (
            "srtm-ellipsoidal",
            30,
            "SRTM_GL1_Ellip",
            "SRTM_GL1_Ellip_srtm.vrt",
            "SRTM_GL1_Ellip_srtm/North/North_0_29/N00E000_wgs84.tif",
            "wgs84",
            100,
        ),
    ],
)
def test_image_download_datum_queries_and_persistent_reuse(
    tmp_path: os.PathLike[str],
    http_server: tuple[str, list[str]],
    caplog: pytest.LogCaptureFixture,
    source: str,
    resolution: int,
    dataset: str,
    catalog_name: str,
    relative: str,
    datum: str,
    height: float,
) -> None:
    url, requests = http_server
    write_tile_catalog(os.path.join(tmp_path, dataset, catalog_name), (relative,))
    write_raster(os.path.join(tmp_path, dataset, relative), np.full((5, 5), 100))
    cache = os.path.join(tmp_path, "cache")
    if datum == "egm96":
        write_raster(os.path.join(cache, "geoid", "us_nga_egm96_15.tif"), np.full((5, 5), 45))
    image = write_raster(os.path.join(tmp_path, "scene.tif"), np.zeros((3, 3)), (0.25, 0.1, 0, 0.75, 0, -0.1))
    dem = Dem(cache_dir=cache, source=source, resolution=resolution)
    dem.provider.base_url = url
    assert dem.get_dem_resolution(0, 1, 0, 1) == resolution
    assert requests == [f"/{dataset}/{catalog_name}"]  # Discovery downloads no elevation rasters.
    tile = dem.preload_image(image)[0]
    assert tile.info.source_datum == datum
    assert tile.info.path == os.path.join(cache, "opentopography", dataset, *relative.split("/"))
    np.testing.assert_array_equal(tile.heights, height)
    np.testing.assert_array_equal(read_raster(tile.info.path).values, 100)
    np.testing.assert_allclose(dem.interpolate_heights([[0.5]], [[0.5]]), [[height]])
    assert dem.get_height_bounds(0, 1, 0, 1, compute_avg_height=True) == (height, height, height)
    assert requests == [f"/{dataset}/{catalog_name}", f"/{dataset}/{relative}"]
    second = Dem(cache_dir=cache, source=source, resolution=resolution)
    second.provider.base_url = url
    np.testing.assert_array_equal(second.preload_image(image)[0].heights, height)
    assert len(requests) == 2
    with caplog.at_level(logging.WARNING):
        np.testing.assert_array_equal(dem.interpolate_heights([1.5], [0.5], avg_height=42), [42])
        assert dem.preload_dem_tiles(1, 2, 0, 1) == ()
    assert caplog.text.count("No DEM tile available") == 1
    assert dem.provider.label in caplog.text
    assert not os.path.exists(os.path.join(cache, "copernicus-30m"))
    if datum == "wgs84":
        assert not os.path.exists(os.path.join(cache, "geoid"))


@pytest.mark.parametrize(
    ("source", "resolution", "message"),
    [
        ("unknown", 30, "Unknown DEM source"),
        ("alos", 90, "only native 30-meter"),
        ("alos-ellipsoidal", 90, "only native 30-meter"),
        ("srtm-ellipsoidal", 90, "only native 30-meter"),
        ("srtm", 10, "30 or 90"),
    ],
)
def test_unsupported_sources_and_resolutions_fail_before_download(
    tmp_path: os.PathLike[str],
    source: str,
    resolution: int,
    message: str,
) -> None:
    cache = os.path.join(tmp_path, "cache")
    with pytest.raises(ValueError, match=message):
        Dem(cache_dir=cache, source=source, resolution=resolution)
    assert not os.path.exists(cache)


@pytest.mark.parametrize(
    "references",
    [
        (),
        ("AW3D30_global/../ALPSMLC30_N000E000_DSM.tif",),
        ("/AW3D30_global/ALPSMLC30_N000E000_DSM.tif",),
        ("AW3D30_global/ALPSMLC30_N090E000_DSM.tif",),
        ("AW3D30_global/ALPSMLC30_N000E000_DSM_wgs84.tif",),
        ("AW3D30_global/ALPSMLC30_N000E000_DSM.tif", "AW3D30_global/ALPSMLC30_N000E000_DSM.tif"),
    ],
)
def test_invalid_catalog_is_not_published(
    tmp_path: os.PathLike[str],
    http_server: tuple[str, list[str]],
    references: tuple[str, ...],
) -> None:
    url, requests = http_server
    write_tile_catalog(os.path.join(tmp_path, "AW3D30", "AW3D30_global.vrt"), references)
    provider = OpenTopography(cache_dir=os.path.join(tmp_path, "cache"))
    provider.base_url = url
    with pytest.raises(ValueError, match="catalog"):
        provider.load_catalog()
    assert not os.path.exists(os.path.join(provider.cache_dir, provider.catalog_name))
    assert os.listdir(provider.cache_dir) == []
    assert requests == ["/AW3D30/AW3D30_global.vrt"]


def test_source_and_resolution_caches_are_independent(tmp_path: os.PathLike[str], http_server: tuple[str, list[str]]) -> None:
    url, requests = http_server
    cache = os.path.join(tmp_path, "cache")
    write_raster(os.path.join(cache, "geoid", "us_nga_egm96_15.tif"), np.full((5, 5), 45))
    products = (
        ("alos", 30, "AW3D30", "AW3D30_global.vrt", "AW3D30_global/ALPSMLC30_N000E000_DSM.tif", 100),
        ("srtm", 30, "SRTM_GL1", "SRTM_GL1_srtm.vrt", "SRTM_GL1_srtm/N00E000.tif", 200),
        ("srtm", 90, "SRTM_GL3", "SRTM_GL3_srtm.vrt", "SRTM_GL3_srtm/North/North_0_29/N00E000.tif", 300),
    )
    paths = []
    for source, resolution, dataset, catalog_name, relative, native_height in products:
        write_tile_catalog(os.path.join(tmp_path, dataset, catalog_name), (relative,))
        write_raster(os.path.join(tmp_path, dataset, relative), np.full((5, 5), native_height))
        dem = Dem(cache_dir=cache, source=source, resolution=resolution)
        dem.provider.base_url = url
        paths.append(dem.preload_dem_tiles(0, 1, 0, 1)[0].info.path)
        np.testing.assert_allclose(dem.interpolate_heights([0.5], [0.5]), [native_height + 45])
    assert len(set(paths)) == 3
    assert len(requests) == 6
    for path, product in zip(paths, products, strict=True):
        np.testing.assert_array_equal(read_raster(path).values, product[-1])


def test_local_priority_and_cli_source_selection(tmp_path: os.PathLike[str]) -> None:
    cache = os.path.join(tmp_path, "cache")
    local = os.path.join(tmp_path, "local")
    write_raster(os.path.join(local, "TDM1_DEM__10_N00E000_DEM.tif"), np.full((5, 5), 17))
    dem = Dem(cache_dir=cache, local_paths=(local,), source="alos-ellipsoidal")
    np.testing.assert_allclose(dem.interpolate_heights([0.5], [0.5]), [17])
    assert not os.path.exists(cache)
    relative = "AW3D30_E_global/ALPSMLC30_N000E000_DSM_wgs84.tif"
    folder = os.path.join(cache, "opentopography", "AW3D30_E")
    write_tile_catalog(os.path.join(folder, "AW3D30_E_global.vrt"), (relative,))
    tile_path = write_raster(os.path.join(folder, *relative.split("/")), np.full((5, 5), 100))
    image_path = write_raster(os.path.join(tmp_path, "scene.tif"), np.zeros((3, 3)), (0.25, 0.1, 0, 0.75, 0, -0.1))
    result = CliRunner().invoke(app, ["download", image_path, "--cache-dir", cache, "--source", "alos-ellipsoidal"])
    assert result.exit_code == 0, result.output
    assert tile_path in result.output
