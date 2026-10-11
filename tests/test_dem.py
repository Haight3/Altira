"""Exercise the actual tile-based DEM API with real rasters.

Copyright (C) 2026
"""

import logging
import os
import tarfile
import zipfile

import numpy as np
import pytest
import requests
from conftest import seed_catalog, write_raster
from osgeo import gdal
from typer.testing import CliRunner

from altira import Dem
from altira.cli import app
from altira.coverage import degree_cells
from altira.datasets import discover_tiles, identify_tile
from altira.downloads import download_file
from altira.provider.copernicus import Copernicus
from altira.raster import Raster, read_raster, validate_raster
from altira.vertical import convert_heights


def test_interpolation_shape_statistics_and_cache(tmp_path: os.PathLike[str]) -> None:
    folder, cache = os.path.join(tmp_path, "local"), os.path.join(tmp_path, "cache")
    heights = np.arange(25, dtype=np.float32).reshape(5, 5)
    path = write_raster(os.path.join(folder, "TDM1_DEM__10_N00E000_DEM.tif"), heights)
    dem = Dem(cache_dir=cache, local_paths=(folder,))
    tiles = dem.preload_dem_tiles(0, 1, 0, 1)
    assert len(tiles) == 1
    assert tiles[0].info.path == path
    assert tiles[0].datum == "wgs84"
    np.testing.assert_array_equal(tiles[0].heights, heights)
    result = dem.interpolate_heights([[0.375, 0.5]], [[0.625, 0.5]])
    np.testing.assert_allclose(result, [[9, 12]])
    assert result.shape == (1, 2)
    assert result.dtype == np.float32
    assert dem.interpolate_heights(0.5, 0.5).shape == ()
    assert dem.get_height_bounds(0, 1, 0, 1, compute_avg_height=True) == (0, 24, 12)
    assert dem.get_height_bounds(0.25, 0.75, 0.25, 0.75) == (6, 18, None)
    assert dem.get_dem_resolution(0, 1, 0, 1) == 30
    assert dem.preload_dem_tiles(0, 1, 0, 1)[0] is tiles[0]
    assert dem.cache_size_mb == pytest.approx(heights.nbytes / (1024 * 1024))
    assert not os.path.exists(cache)  # A covered local tile needs no remote catalog.


def test_bilinear_seam_and_integer_coordinates(tmp_path: os.PathLike[str]) -> None:
    folder = os.path.join(tmp_path, "local")
    for west in (0, 1):
        lon = west + np.arange(4) * 0.25
        lat = 1 - np.arange(4) * 0.25
        heights = lon[None, :] * 100 + lat[:, None] * 10
        write_raster(
            os.path.join(folder, f"TDM1_DEM__10_N00E{west:03d}_DEM.tif"),
            heights,
            (west - 0.125, 0.25, 0, 1.125, 0, -0.25),
        )
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(folder,))
    np.testing.assert_allclose(dem.interpolate_heights([0.875, 1.0, 1.125], [0.5, 0.5, 0.5]), [92.5, 105, 117.5])


def test_nodata_fill_and_exact_post(tmp_path: os.PathLike[str]) -> None:
    folder = os.path.join(tmp_path, "local")
    heights = np.full((3, 3), 10.0)
    heights[0, 1] = -9999
    write_raster(os.path.join(folder, "TDM1_DEM__10_N00E000_DEM.tif"), heights, (-0.25, 0.5, 0, 1.25, 0, -0.5), nodata=-9999)
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(folder,))
    np.testing.assert_allclose(dem.interpolate_heights([0.25], [0.75]), [7.5])
    np.testing.assert_allclose(dem.interpolate_heights([0.25], [0.75], avg_height=20), [12.5])
    assert np.isnan(dem.interpolate_heights([0.25], [0.75], avg_height=float("nan"))).all()
    np.testing.assert_allclose(dem.interpolate_heights([0.0], [0.5], avg_height=float("nan")), [10])
    assert dem.get_height_bounds(0, 1, 0, 1, compute_avg_height=True) == (10, 10, 10)


def test_missing_southern_boundary_rows_and_statistics(tmp_path: os.PathLike[str]) -> None:
    folder = os.path.join(tmp_path, "local")
    for south in (0, 1):
        lat = south + 1 - np.arange(4) * 0.25
        write_raster(
            os.path.join(folder, f"TDM1_DEM__10_N{south:02d}E000_DEM.tif"),
            np.broadcast_to(lat[:, None] * 10, (4, 4)),
            (-0.125, 0.25, 0, south + 1.125, 0, -0.25),
        )
    cache = os.path.join(tmp_path, "cache")
    seed_catalog(cache)
    dem = Dem(cache_dir=cache, local_paths=(folder,))
    np.testing.assert_allclose(dem.interpolate_heights([0.5] * 3, [0.875, 1, 1.125]), [8.75, 10, 11.25])
    assert dem.get_height_bounds(0, 0.75, 0, 2, compute_avg_height=True) == (2.5, 20, 11.25)


def test_misnamed_raster_fails_before_use(tmp_path: os.PathLike[str]) -> None:
    write_raster(os.path.join(tmp_path, "TDM1_DEM__10_N00E000_DEM.tif"), np.ones((5, 5)), (10, 0.25, 0, 11, 0, -0.25))
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(os.fspath(tmp_path),))
    with pytest.raises(ValueError, match="named geographic coverage"):
        dem.preload_dem_tiles(0, 1, 0, 1)
    assert dem.cache_size_mb == 0


def test_priority_and_sample_weighted_statistics(tmp_path: os.PathLike[str]) -> None:
    fine, coarse, cache = (os.path.join(tmp_path, name) for name in ("fine", "coarse", "cache"))
    write_raster(os.path.join(fine, "TDM1_DEM__10_N00E001_DEM.tif"), np.full((5, 5), 100), (0.875, 0.25, 0, 1.125, 0, -0.25))
    write_raster(os.path.join(coarse, "srtm_37_12.tif"), np.full((6, 6), 10), (-0.5, 1, 0, 5.5, 0, -1))
    write_raster(os.path.join(cache, "geoid", "us_nga_egm96_15.tif"), np.zeros((6, 6)), (-0.5, 1, 0, 5.5, 0, -1))
    dem = Dem(cache_dir=cache, local_paths=(fine, coarse))
    np.testing.assert_allclose(dem.interpolate_heights([0.0, 1.5], [0.0, 0.5]), [10, 100])
    minimum, maximum, average = dem.get_height_bounds(0, 2, 0, 1, compute_avg_height=True)
    assert (minimum, maximum) == (10, 100)
    assert average == pytest.approx(2520 / 27)
    assert dem.get_dem_resolution(0, 2, 0, 1) == 30


def test_lru_limit_and_disabled_cache(tmp_path: os.PathLike[str]) -> None:
    folder = os.path.join(tmp_path, "local")
    for west in (0, 1):
        write_raster(
            os.path.join(folder, f"TDM1_DEM__10_N00E{west:03d}_DEM.tif"),
            np.zeros((5, 5)),
            (west - 0.125, 0.25, 0, 1.125, 0, -0.25),
        )
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(folder,), max_cache_size_mb=150 / (1024 * 1024))
    tiles = dem.preload_dem_tiles(0, 2, 0, 1)
    assert list(dem.tile_cache) == [tiles[1].info.path]
    assert dem.cache_size_mb <= dem.max_cache_size_mb
    assert dem.load_tile(tiles[0].info) is not tiles[0]
    assert list(dem.tile_cache) == [tiles[0].info.path]
    uncached = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(folder,), max_cache_size_mb=0)
    assert len(uncached.preload_dem_tiles(0, 2, 0, 1)) == 2
    assert uncached.cache_size_mb == 0


def test_missing_coverage_reports_once_and_never_changes_resolution(tmp_path: os.PathLike[str], caplog: pytest.LogCaptureFixture) -> None:
    cache = os.fspath(tmp_path)
    seed_catalog(cache)
    dem = Dem(cache_dir=cache)
    with caplog.at_level(logging.WARNING):
        assert dem.preload_dem_tiles(0, 1, 0, 1) == ()
        np.testing.assert_array_equal(dem.interpolate_heights([0.5], [0.5], avg_height=42), [42])
    assert caplog.text.count("No DEM tile available") == 1
    assert "GLO-30" in caplog.text
    assert not os.path.exists(os.path.join(cache, "copernicus-90m"))
    with pytest.raises(ValueError, match="No valid DEM samples"):
        dem.get_height_bounds(0, 1, 0, 1)
    with pytest.raises(ValueError, match="No DEM tiles"):
        dem.get_dem_resolution(0, 1, 0, 1)


@pytest.mark.parametrize(("datum", "filename", "offset"), [("egm96", "us_nga_egm96_15.tif", -30), ("egm2008", "us_nga_egm08_25.tif", 45)])
def test_correct_datum_grid_and_sign(tmp_path: os.PathLike[str], datum: str, filename: str, offset: float) -> None:
    write_raster(os.path.join(tmp_path, "geoid", filename), np.full((5, 5), offset))
    heights = np.full((5, 5), 100, dtype=np.float32)
    heights[2, 2] = np.nan
    raster = Raster(heights, (-0.125, 0.25, 0, 1.125, 0, -0.25))
    convert_heights(raster, source_datum=datum, cache_dir=os.fspath(tmp_path))
    assert np.isnan(raster.values[2, 2])
    np.testing.assert_array_equal(raster.values[np.isfinite(raster.values)], 100 + offset)


def test_geoid_failure_is_not_silently_ignored(tmp_path: os.PathLike[str]) -> None:
    grid_path = os.path.join(tmp_path, "geoid", "us_nga_egm08_25.tif")
    write_raster(grid_path, np.ones((5, 5)), (10, 0.25, 0, 10, 0, -0.25))
    raster = Raster(np.ones((5, 5), dtype=np.float32), (-0.125, 0.25, 0, 1.125, 0, -0.25))
    with pytest.raises(ValueError, match="does not cover"):
        convert_heights(raster, source_datum="egm2008", cache_dir=os.fspath(tmp_path))
    np.testing.assert_array_equal(raster.values, 1)


@pytest.mark.parametrize("archive_type", ["zip", "tar"])
def test_archive_discovery_and_real_loading(tmp_path: os.PathLike[str], archive_type: str) -> None:
    path = write_raster(os.path.join(tmp_path, "source", "TDM1_DEM__10_N00E000_DEM.tif"), np.full((5, 5), 17))
    folder = os.path.join(tmp_path, "local")
    os.makedirs(folder)
    archive_path = os.path.join(folder, f"TDM1_DEM__10_N00E000.{archive_type}")
    if archive_type == "zip":
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.write(path, "nested/" + os.path.basename(path))
    else:
        with tarfile.open(archive_path, "w") as archive:
            archive.add(path, arcname="nested/" + os.path.basename(path))
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(folder,))
    tile = dem.preload_dem_tiles(0, 1, 0, 1)[0]
    assert tile.info.path.startswith(f"/vsi{archive_type}/")
    np.testing.assert_array_equal(tile.heights, 17)
    np.testing.assert_allclose(dem.interpolate_heights([0.5], [0.5]), [17])


def test_real_srtm_hgt_and_zipped_hgt(tmp_path: os.PathLike[str]) -> None:
    folder, cache = os.path.join(tmp_path, "local"), os.path.join(tmp_path, "cache")
    os.makedirs(folder)
    path = os.path.join(folder, "N00E000.hgt")
    np.full((1201, 1201), 100, dtype=">i2").tofile(path)
    with zipfile.ZipFile(os.path.join(folder, "N00E001.hgt.zip"), "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(path, "N00E001.hgt")
    write_raster(os.path.join(cache, "geoid", "us_nga_egm96_15.tif"), np.full((5, 9), -30))
    infos = discover_tiles(folder)
    assert len(infos) == 2
    assert {info.resolution for info in infos} == {90}
    dem = Dem(cache_dir=cache, local_paths=(folder,))
    np.testing.assert_allclose(dem.interpolate_heights([0.5, 1.5], [0.5, 0.5]), [70, 70], atol=1e-5)


def test_legacy_copernicus_mapping_archive(tmp_path: os.PathLike[str]) -> None:
    folder, cache = os.path.join(tmp_path, "local"), os.path.join(tmp_path, "cache")
    path = write_raster(os.path.join(tmp_path, "source", "delivery.tif"), np.full((5, 5), 100))
    os.makedirs(folder)
    filename = "DEM1_SAR_DGE_30_20200101T000000_20200101T000001_scene.DEM.zip"
    with zipfile.ZipFile(os.path.join(folder, filename), "w") as archive:
        archive.write(path, "nested/DEM/delivery.tif")
    with open(os.path.join(folder, "mapping.csv"), "w", encoding="utf-8") as mapping:
        mapping.write(f"filename;latitude;longitude\n{filename};N00;E000\n")
    write_raster(os.path.join(cache, "geoid", "us_nga_egm08_25.tif"), np.full((5, 5), 45))
    dem = Dem(cache_dir=cache, local_paths=(folder,))
    assert dem.get_dem_resolution(0, 1, 0, 1) == 30
    np.testing.assert_allclose(dem.interpolate_heights([0.5], [0.5]), [145])


@pytest.mark.parametrize(
    ("filename", "bounds", "datum", "resolution"),
    [
        ("srtm_01_01.tif", (-180, -175, 55, 60), "egm96", 90),
        ("e013/n52.dt2", (13, 14, 52, 53), "egm96", 30),
        ("TDM1_DEM__30_S80W010_DEM.tif", (-10, -6, -80, -79), "wgs84", 90),
        ("W010S20_DSM.tif", (-10, -9, -20, -19), "egm2008", 12),
        ("Copernicus_DSM_10_N52_00_E013_00_DEM.dt2", (13, 14, 52, 53), "egm2008", 30),
        ("Copernicus_DSM_COG_30_S20_00_W010_00_DEM.tif", (-10, -9, -20, -19), "egm2008", 90),
    ],
)
def test_format_coordinates_and_datum(filename: str, bounds: tuple[float, ...], datum: str, resolution: float) -> None:
    info = identify_tile(filename)
    assert info is not None
    assert (info.west, info.east, info.south, info.north) == bounds
    assert info.source_datum == datum
    assert info.resolution == resolution


def test_dted_prefers_highest_level(tmp_path: os.PathLike[str]) -> None:
    for level in (0, 1, 2):
        write_raster(os.path.join(tmp_path, "e000", f"n00.dt{level}"), np.full((5, 5), level))
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(os.fspath(tmp_path),))
    assert dem.find_tiles(0, 1, 0, 1)[0].path.endswith(".dt2")
    assert dem.get_dem_resolution(0, 1, 0, 1) == 30


def test_download_catalog_tile_and_reuse_cache(tmp_path: os.PathLike[str], http_server: tuple[str, list[str]]) -> None:
    url, paths = http_server
    name = "Copernicus_DSM_COG_10_N00_00_E000_00_DEM"
    with open(os.path.join(tmp_path, "tileList.txt"), "w", encoding="utf-8") as catalog:
        catalog.write(name + "\n")
    write_raster(os.path.join(tmp_path, name, name + ".tif"), np.full((4, 4), 100))
    write_raster(os.path.join(tmp_path, "us_nga_egm08_25.tif"), np.full((5, 5), 45))
    cache = os.path.join(tmp_path, "cache")
    # The URLs are the actual external boundary; acquisition and decoding remain real.
    download_file(url + "/us_nga_egm08_25.tif", os.path.join(cache, "geoid", "us_nga_egm08_25.tif"), validate=validate_raster)
    dem = Dem(cache_dir=cache)
    dem.provider.base_url = url
    tile = dem.preload_dem_tiles(0, 1, 0, 1)[0]
    np.testing.assert_array_equal(tile.heights, 145)
    np.testing.assert_array_equal(read_raster(tile.info.path).values, 100)  # Disk stays in native EGM2008.
    np.testing.assert_allclose(dem.interpolate_heights([0.5], [0.5]), [145])
    assert paths == ["/us_nga_egm08_25.tif", "/tileList.txt", f"/{name}/{name}.tif"]
    second = Dem(cache_dir=cache)
    second.provider.base_url = url
    np.testing.assert_array_equal(second.preload_dem_tiles(0, 1, 0, 1)[0].heights, 145)
    assert len(paths) == 3


def test_failed_download_preserves_destination(tmp_path: os.PathLike[str], http_server: tuple[str, list[str]]) -> None:
    url, _ = http_server
    destination = os.path.join(tmp_path, "cache", "tile.tif")
    write_raster(destination, np.full((5, 5), 17))
    with pytest.raises(requests.exceptions.RequestException):
        download_file(url + "/truncated.tif", destination, validate=validate_raster)
    np.testing.assert_array_equal(read_raster(destination).values, 17)
    assert os.listdir(os.path.dirname(destination)) == ["tile.tif"]
    with open(os.path.join(tmp_path, "invalid.tif"), "w", encoding="utf-8") as invalid:
        invalid.write("This is not a raster.")
    with pytest.raises(RuntimeError):
        download_file(url + "/invalid.tif", destination, validate=validate_raster)
    np.testing.assert_array_equal(read_raster(destination).values, 17)
    assert os.listdir(os.path.dirname(destination)) == ["tile.tif"]


def test_invalid_catalog_does_not_enter_cache(tmp_path: os.PathLike[str], http_server: tuple[str, list[str]]) -> None:
    url, _ = http_server
    with open(os.path.join(tmp_path, "tileList.txt"), "w", encoding="utf-8") as catalog:
        catalog.write("../unexpected.tif\n")
    provider = Copernicus(cache_dir=os.path.join(tmp_path, "cache"))
    provider.base_url = url
    with pytest.raises(ValueError, match="catalog entry"):
        provider.load_catalog()
    assert not os.path.exists(os.path.join(provider.cache_dir, "tileList.txt"))


def test_real_image_path_and_cli(tmp_path: os.PathLike[str]) -> None:
    image_path = write_raster(os.path.join(tmp_path, "image", "scene.tif"), np.zeros((3, 3)), (0.25, 0.1, 0, 0.75, 0, -0.1))
    folder, cache = os.path.join(tmp_path, "local"), os.path.join(tmp_path, "cache")
    tile_path = write_raster(os.path.join(folder, "TDM1_DEM__10_N00E000_DEM.tif"), np.full((5, 5), 17))
    dem = Dem(cache_dir=cache, local_paths=(folder,))
    assert dem.preload_image(image_path)[0].info.path == tile_path
    result = CliRunner().invoke(app, ["download", image_path, "--cache-dir", cache, "--local-path", folder])
    assert result.exit_code == 0, result.output
    assert tile_path in result.output


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ((0, 1, 0, 1), ((0, 0),)),
        ((1, 1, 1, 1), ((1, 1),)),
        ((-1.2, -0.2, -1.2, -0.2), ((-2, -2), (-1, -2), (-2, -1), (-1, -1))),
        ((179.5, -179.5, 0, 1), ((179, 0), (-180, 0))),
        ((180, 180, 90, 90), ((-180, 89),)),
    ],
)
def test_boundary_cell_selection(bounds: tuple[float, ...], expected: tuple[tuple[int, int], ...]) -> None:
    assert degree_cells(*bounds) == expected


def test_invalid_inputs_and_all_nodata(tmp_path: os.PathLike[str]) -> None:
    folder = os.path.join(tmp_path, "local")
    write_raster(os.path.join(folder, "TDM1_DEM__10_N00E000_DEM.tif"), np.full((5, 5), -9999), nodata=-9999)
    dem = Dem(cache_dir=os.path.join(tmp_path, "cache"), local_paths=(folder,))
    with pytest.raises(ValueError, match="No valid DEM samples"):
        dem.get_height_bounds(0, 1, 0, 1)
    with pytest.raises(ValueError, match="same shape"):
        dem.interpolate_heights([0], [[0]])
    with pytest.raises(ValueError, match="finite"):
        dem.interpolate_heights([float("nan")], [0])
    with pytest.raises(ValueError, match="longitude"):
        dem.interpolate_heights([181], [0])
    with pytest.raises(ValueError, match="nonnegative"):
        Dem(cache_dir="unused", max_cache_size_mb=-1)
    with pytest.raises(ValueError, match="30 or 90"):
        Dem(cache_dir="unused", resolution=12)
    assert dem.interpolate_heights([], []).shape == (0,)
    with pytest.raises(ValueError, match="longitude"):
        degree_cells(0, 1, 2, 1)


def test_raster_mask_is_respected(tmp_path: os.PathLike[str]) -> None:
    path = write_raster(os.path.join(tmp_path, "masked.tif"), np.full((5, 5), 7))
    with gdal.ExceptionMgr(useExceptions=True), gdal.Open(path, gdal.GA_Update) as dataset:
        band = dataset.GetRasterBand(1)
        band.CreateMaskBand(gdal.GMF_PER_DATASET)
        mask = np.full((5, 5), 255, dtype=np.uint8)
        mask[2, 2] = 0
        band.GetMaskBand().WriteArray(mask)
    raster = read_raster(path)
    assert np.isnan(raster.values[2, 2])
    assert np.count_nonzero(np.isfinite(raster.values)) == 24
