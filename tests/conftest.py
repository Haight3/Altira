"""Real raster and HTTP fixtures for DEM integration tests.

Copyright (C) 2026
"""

import functools
import html
import logging
import os
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest
from numpy.typing import ArrayLike
from osgeo import gdal, osr


def write_raster(
    path: str,
    values: ArrayLike,
    transform: tuple[float, float, float, float, float, float] = (-0.125, 0.25, 0, 1.125, 0, -0.25),
    nodata: float | None = None,
) -> str:
    """Write a small real WGS84 GeoTIFF, including its sample grid and nodata.

    Returns
    -------
    str
        Raster filename.
    """
    values = np.asarray(values, dtype=np.float32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with (
        gdal.ExceptionMgr(useExceptions=True),
        osr.ExceptionMgr(useExceptions=True),
        gdal.GetDriverByName("GTiff").Create(path, values.shape[1], values.shape[0], 1, gdal.GDT_Float32) as dataset,
    ):
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        dataset.SetGeoTransform(transform)
        dataset.SetProjection(srs.ExportToWkt())
        dataset.SetMetadataItem("AREA_OR_POINT", "Point")
        band = dataset.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.WriteArray(values)
    return path


def seed_catalog(cache_dir: str, names: tuple[str, ...] = ("Copernicus_DSM_COG_10_N40_00_E040_00_DEM",)) -> str:
    """Write a real-format catalog to control available external coverage.

    Returns
    -------
    str
        Catalog filename.
    """
    path = os.path.join(cache_dir, "copernicus-30m", "tileList.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as catalog:
        catalog.write("\n".join(names) + "\n")
    return path


def write_tile_catalog(path: str, references: tuple[str, ...]) -> str:
    """Write a small VRT index using the provider's real relative-reference format.

    Returns
    -------
    str
        Catalog filename.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as catalog:
        catalog.write('<VRTDataset rasterXSize="5" rasterYSize="5"><VRTRasterBand dataType="Float32" band="1">')
        catalog.writelines(
            '<SimpleSource><SourceFilename relativeToVRT="1">' + html.escape(relative) + "</SourceFilename></SimpleSource>"
            for relative in references
        )
        catalog.write("</VRTRasterBand></VRTDataset>")
    return path


@pytest.fixture
def http_server(tmp_path: os.PathLike[str]) -> Iterator[tuple[str, list[str]]]:
    """Serve real fixture files and record HTTP paths, including a broken transfer.

    Yields
    ------
    tuple[str, list[str]]
        Server base URL and recorded request paths.
    """
    paths = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            paths.append(self.path)
            if self.path == "/truncated.tif":
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"incomplete")
                self.close_connection = True
                return
            super().do_GET()

        def log_message(self, message: str, *args: object) -> None:
            logging.getLogger(__name__).debug("%s: %s", self.client_address, message % args)

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=os.fspath(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
